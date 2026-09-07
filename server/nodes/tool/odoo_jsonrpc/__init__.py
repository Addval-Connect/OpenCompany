"""Odoo JSON-RPC tool — a credential-locked External API tool for Odoo.

Why this exists instead of a bare ``httpRequest``: the generic HTTP node is an
``ActionNode`` whose model-supplied ``tool_args`` override the persisted node
params (``{**node_params, **tool_args}``), and its ``url`` field is required.
When an LLM drives it against Odoo it *invents* the instance hostname from the
statement's bank name (``inversiones.odoo.com``, ``am635a.odoo.com`` …), which
never authenticates and loops forever.

This node is a ``ToolNode`` with a split schema: the connection (host / db /
username / api_key) lives in ``Params`` — server-controlled, never exposed to
the model — while the LLM only chooses the *business* call (model, method,
domain/fields/values). The server builds ``https://{host}/jsonrpc`` and performs
the two-step ``common.login`` -> ``object.execute_kw`` handshake itself, so the
host can never be hallucinated.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.plugin import (
    NodeContext,
    NodeUserError,
    Operation,
    TaskQueue,
    ToolNode,
)


# --------------------------------------------------------------------------- #
# Persisted connection config — SERVER-CONTROLLED, never a model argument.
# --------------------------------------------------------------------------- #
class OdooJsonRpcParams(BaseModel):
    """Odoo connection settings, edited by the operator in the node panel."""

    host: str = Field(
        default="",
        title="Odoo Host",
        description=(
            "Odoo instance hostname WITHOUT scheme or path, e.g. "
            "my-db.dev.odoo.com. The node calls https://<host>/jsonrpc."
        ),
    )
    db: str = Field(
        default="",
        title="Database",
        description="Odoo database name.",
    )
    username: str = Field(
        default="",
        title="Username",
        description="Odoo login (usually the account email).",
    )
    api_key: str = Field(
        default="",
        title="API Key",
        description="Odoo API key / password used for JSON-RPC login.",
        json_schema_extra={"secret": True, "password": True},
    )
    timeout: int = Field(
        default=60, ge=1, le=600, description="Request timeout in seconds."
    )

    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------- #
# Model-visible tool input — the LLM only ever picks a business call.
# --------------------------------------------------------------------------- #
OdooMethod = Literal[
    "search_read",
    "read",
    "search",
    "search_count",
    "create",
    "write",
    "unlink",
    "fields_get",
    "load",
    "call",
]


class OdooJsonRpcToolInput(BaseModel):
    """One locked schema visible to the LLM. No host/db/credentials here."""

    model: str = Field(
        description=(
            "Odoo model name, e.g. 'product.product', 'res.partner', "
            "'kardex.import.log'."
        )
    )
    method: OdooMethod = Field(
        description=(
            "Odoo ORM method: search_read/read/search/search_count/create/"
            "write/unlink/fields_get/load, or 'call' for an arbitrary method "
            "named in method_name. For importing rows that carry an external "
            "id, prefer 'load' over 'create': it is idempotent (re-running "
            "updates instead of duplicating) and it registers the xmlid for "
            "you. 'create' cannot register an xmlid, and writing one by hand "
            "into ir.model.data fails on the second run with a duplicate-key "
            "error."
        )
    )
    method_name: Optional[str] = Field(
        default=None,
        description="Method to invoke when method='call' (e.g. a custom method).",
    )
    domain: Optional[List[Any]] = Field(
        default=None,
        description=(
            "Search domain for search/search_read/search_count, e.g. "
            "[['default_code','=','ABC']]. Omit for [] (all records)."
        ),
    )
    fields: Optional[List[str]] = Field(
        default=None,
        description=(
            "Field names to return for read/search_read. For load, the column "
            "header of the import: the first entry must be 'id' (the xmlid "
            "column) and relational columns use the '<field>/id' form, e.g. "
            "['id', 'name', 'categ_id/id']."
        ),
    )
    ids: Optional[List[int]] = Field(
        default=None,
        description="Record ids for read/write/unlink.",
    )
    values: Optional[Any] = Field(
        default=None,
        description=(
            "Record payload for create (a dict) or write (a dict applied to "
            "ids). For create with line_ids use the Odoo (0,0,{...}) command "
            "tuples. For load, the data rows: a list of rows, each row a list "
            "of strings positionally matching 'fields'. Every value is a "
            "string, including numbers and booleans ('1'/'0')."
        ),
    )
    limit: Optional[int] = Field(
        default=None, ge=1, le=1000, description="Max rows for search/search_read."
    )
    offset: Optional[int] = Field(
        default=None, ge=0, description="Row offset for pagination."
    )
    order: Optional[str] = Field(
        default=None, description="Sort clause, e.g. 'id desc'."
    )
    args: Optional[List[Any]] = Field(
        default=None,
        description=(
            "Positional args when method='call'. Ignored for the ORM helpers "
            "above (they are built from domain/ids/values)."
        ),
    )
    kwargs: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Keyword args when method='call'.",
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_by_method(self) -> "OdooJsonRpcToolInput":
        if self.method == "call" and not self.method_name:
            raise ValueError("method='call' requires method_name")
        if self.method in ("read", "write", "unlink") and not self.ids:
            raise ValueError(f"{self.method} requires ids")
        if self.method == "create" and self.values is None:
            raise ValueError("create requires values")
        if self.method == "write" and self.values is None:
            raise ValueError("write requires values")
        if self.method == "load":
            if not self.fields:
                raise ValueError("load requires fields (the import header, starting with 'id')")
            if not isinstance(self.values, list) or not self.values:
                raise ValueError("load requires values as a non-empty list of data rows")
            if not all(isinstance(row, list) for row in self.values):
                raise ValueError("load requires every row in values to be a list of strings")
            width = len(self.fields)
            bad = [i for i, row in enumerate(self.values) if len(row) != width]
            if bad:
                raise ValueError(
                    f"load: rows {bad[:5]} do not have {width} values, one per entry in fields"
                )
        return self


class OdooJsonRpcOutput(BaseModel):
    ok: bool
    model: Optional[str] = None
    method: Optional[str] = None
    result: Any = None
    error: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")


class OdooJsonRpcNode(ToolNode):
    type = "odooJsonRpc"
    display_name = "Odoo JSON-RPC"
    subtitle = "Odoo ORM over JSON-RPC"
    group = ("tool", "ai")
    description = (
        "Call the Odoo ORM (search_read/read/create/write/…) over JSON-RPC. "
        "Connection host and credentials are configured on the node; the model "
        "only chooses the business call."
    )
    component_kind = "tool"
    tool_name = "odoo_jsonrpc"
    tool_description = (
        "Query or write Odoo records over JSON-RPC. Choose model (e.g. "
        "product.product, res.partner, kardex.import.log) and method "
        "(search_read/read/search/search_count/create/write/unlink/fields_get/"
        "load, or call with method_name). Provide domain/fields/ids/values as "
        "needed. To import rows that carry an external id use method='load' "
        "with fields as the header (first entry 'id') and values as the data "
        "rows — it is idempotent and registers xmlids, which create cannot. "
        "You never provide a URL, database, or credentials — they are fixed on "
        "the node. Returns {ok, result} or {ok:false, error}."
    )
    handles = (
        {
            "name": "output-tool",
            "kind": "output",
            "position": "top",
            "label": "Odoo",
            "role": "tools",
        },
    )
    ui_hints = {"isToolPanel": True, "hideInputSection": True, "hideRunButton": True}
    annotations = {"destructive": True, "readonly": False, "open_world": True}
    task_queue = TaskQueue.REST_API

    Params = OdooJsonRpcParams
    ToolInput = OdooJsonRpcToolInput
    Output = OdooJsonRpcOutput
    tool_schema_locked = True

    # ------------------------------------------------------------------ #
    async def _rpc(
        self,
        client: httpx.AsyncClient,
        url: str,
        service: str,
        method: str,
        args: list,
    ) -> Any:
        """One JSON-RPC call; raises NodeUserError on transport / Odoo error."""
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": 1,
        }
        try:
            resp = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise NodeUserError(
                f"Could not reach Odoo at {url}: {exc}. Check the node's host."
            ) from exc
        if resp.status_code != 200:
            raise NodeUserError(
                f"Odoo returned HTTP {resp.status_code} for {url}. "
                "Check the node's host/database configuration."
            )
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise NodeUserError(
                f"Odoo response was not JSON (host misconfigured?): "
                f"{resp.text[:200]}"
            ) from exc
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            msg = (
                err.get("data", {}).get("message")
                if isinstance(err.get("data"), dict)
                else None
            ) or err.get("message") or str(err)
            raise NodeUserError(f"Odoo error: {msg}")
        return data.get("result") if isinstance(data, dict) else data

    def _build_execute_args(
        self, cfg: OdooJsonRpcParams, uid: int, args: OdooJsonRpcToolInput
    ) -> list:
        """Build the execute_kw positional args from the business input."""
        base = [cfg.db, uid, cfg.api_key, args.model]
        if args.method == "call":
            return base + [args.method_name, args.args or [], args.kwargs or {}]

        domain = args.domain or []
        kwargs: Dict[str, Any] = dict(args.kwargs or {})
        if args.method == "search_read":
            if args.fields is not None:
                kwargs["fields"] = args.fields
            if args.limit is not None:
                kwargs["limit"] = args.limit
            if args.offset is not None:
                kwargs["offset"] = args.offset
            if args.order is not None:
                kwargs["order"] = args.order
            return base + ["search_read", [domain], kwargs]
        if args.method == "search":
            if args.limit is not None:
                kwargs["limit"] = args.limit
            if args.offset is not None:
                kwargs["offset"] = args.offset
            if args.order is not None:
                kwargs["order"] = args.order
            return base + ["search", [domain], kwargs]
        if args.method == "search_count":
            return base + ["search_count", [domain], kwargs]
        if args.method == "read":
            if args.fields is not None:
                kwargs["fields"] = args.fields
            return base + ["read", [args.ids], kwargs]
        if args.method == "create":
            return base + ["create", [args.values], kwargs]
        if args.method == "write":
            return base + ["write", [args.ids, args.values], kwargs]
        if args.method == "unlink":
            return base + ["unlink", [args.ids], kwargs]
        if args.method == "fields_get":
            return base + ["fields_get", args.args or [], kwargs]
        if args.method == "load":
            # load(fields, data) — the native importer. Transactional per call:
            # one rejected row rolls the whole batch back, and the rejection is
            # reported in result['messages'] with ok=True, not as an RPC error.
            return base + ["load", [args.fields, args.values], kwargs]
        # Should be unreachable given the Literal.
        raise NodeUserError(f"Unsupported method: {args.method}")

    @Operation("query")
    async def query(
        self,
        ctx: NodeContext,
        params: OdooJsonRpcToolInput | OdooJsonRpcParams,
    ) -> OdooJsonRpcOutput:
        # Recover the connection config. Two dispatch paths reach here:
        #   1. execute_as_tool split-schema (WS / Context-V2): the validated
        #      Params live in ctx.raw["_tool_config"], and `params` is the
        #      ToolInput the model supplied.
        #   2. Temporal per-type activity (node.odooJsonRpc.v1): the node runs
        #      like a normal workflow node, so there is no _tool_config and the
        #      persisted node params arrive as ctx.raw["_raw_parameters"]
        #      merged with the model's args. Recover host/db/etc from there.
        cfg = ctx.raw.get("_tool_config")
        if not isinstance(cfg, OdooJsonRpcParams):
            raw = ctx.raw.get("_raw_parameters")
            if isinstance(raw, dict):
                cfg = OdooJsonRpcParams.model_validate(raw)
            elif isinstance(params, OdooJsonRpcParams):
                # Last resort: the merged model IS the config (Params branch).
                cfg = params
            else:
                cfg = OdooJsonRpcParams()

        # `params` is the business call. In the per-type path it may have been
        # validated as Params (config-only) when the model supplied a full
        # merged dict; re-validate the model-facing args from raw parameters.
        # The merged dict also carries the connection fields (host/db/…), so
        # project onto ToolInput's own fields before validating (extra=forbid).
        if isinstance(params, OdooJsonRpcParams):
            raw = ctx.raw.get("_raw_parameters")
            if isinstance(raw, dict):
                allowed = set(OdooJsonRpcToolInput.model_fields)
                projected = {k: v for k, v in raw.items() if k in allowed}
                try:
                    params = OdooJsonRpcToolInput.model_validate(projected)
                except Exception as exc:  # noqa: BLE001
                    raise NodeUserError(
                        "No Odoo call provided. Supply model + method "
                        f"(and domain/fields/values as needed): {exc}"
                    ) from exc
            else:
                raise NodeUserError(
                    "No Odoo call provided. The model must supply model + method."
                )

        missing = [
            name
            for name in ("host", "db", "username", "api_key")
            if not getattr(cfg, name)
        ]
        if missing:
            raise NodeUserError(
                "Odoo node is not configured: missing "
                + ", ".join(missing)
                + ". Set them on the node panel."
            )

        host = cfg.host.strip().rstrip("/")
        # Defend against an operator pasting a full URL into the host field.
        host = host.replace("https://", "").replace("http://", "").split("/")[0]
        url = f"https://{host}/jsonrpc"

        async with httpx.AsyncClient(timeout=float(cfg.timeout)) as client:
            uid = await self._rpc(
                client, url, "common", "login",
                [cfg.db, cfg.username, cfg.api_key],
            )
            if not uid or not isinstance(uid, int):
                raise NodeUserError(
                    "Odoo login failed (uid is false). The database, username, "
                    "or api_key is wrong — do NOT retry with a different host."
                )
            exec_args = self._build_execute_args(cfg, uid, params)
            result = await self._rpc(
                client, url, "object", "execute_kw", exec_args
            )

        return OdooJsonRpcOutput(
            ok=True, model=params.model, method=params.method, result=result
        )


__all__ = [
    "OdooJsonRpcNode",
    "OdooJsonRpcParams",
    "OdooJsonRpcToolInput",
    "OdooJsonRpcOutput",
]
