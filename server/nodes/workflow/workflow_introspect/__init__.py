"""Workflow Introspect — read-only structural reader for workflows across namespaces.

One locked multi-operation tool (``workflow_introspect``) over the
per-namespace ``workflow.db`` files under ``{data_dir}/namespaces/``.
Built for the IAuditor pattern (2026-10): auditing a prompt/skill set
*as deployed* means reading the target workflow's real graph — nodes,
edges with their handles, and every node's persisted parameters
(system prompts, ``skills_config``) — not a prose copy of it.

Security posture:

- **Read-only.** Every connection opens with SQLite URI ``mode=ro``; a
  write attempt raises ``OperationalError: readonly database``.
- **Only ``workflow.db``.** The credentials DB of any namespace is never
  opened, never listed, never touched.
- **Namespace names are validated** against ``NAMESPACE_PATTERN``
  (services.tenancy) *before* any path join, so a hostile namespace
  argument cannot traverse out of ``namespaces/``. The reserved-set
  check in :func:`services.tenancy.is_valid_namespace` is deliberately
  NOT applied: ``default`` is a legitimate namespace to read even
  though tenants may not be *created* under it.
- **Optional operator allowlist**: set ``AUDITABLE_NAMESPACES``
  (comma/space separated) to restrict which namespaces are visible.
  Unset = every namespace with a ``workflow.db`` on this host.

Size discipline: a large workflow's full definition is hundreds of KB.
The tool truncates long strings (per-string and whole-payload caps,
reported in ``truncated``) and its tool_description instructs the
agent to persist the result into the workspace with ``file_modify``
rather than echo it back into context.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.logging import get_logger
from services.plugin import NodeContext, NodeUserError, Operation, TaskQueue, ToolNode

logger = get_logger(__name__)

#: Operator allowlist. Comma/space separated namespace names; unset or
#: empty means every namespace with a ``workflow.db`` on disk.
ALLOWLIST_ENV = "AUDITABLE_NAMESPACES"

#: Per-string truncation cap (system prompts and inline skills are the
#: big values; 20k chars covers any prompt seen in production ~8x).
_STR_CAP = 20_000
#: Whole-payload character cap for ``get_workflow`` — the per-string cap
#: is halved and re-applied until the payload fits (floor 2,000).
_TOTAL_CAP = 600_000
_TOTAL_CAP_FLOOR = 2_000

_TRUNC_SUFFIX = "…[truncated, +{} chars]"

WorkflowIntrospectOperation = Literal[
    "list_namespaces", "list_workflows", "get_workflow",
]

_INCLUDE = {"displayOptions": {"show": {"operation": ["get_workflow"]}}}
_WORKFLOW = _INCLUDE
_NAMESPACE = {
    "displayOptions": {
        "show": {"operation": ["list_workflows", "get_workflow"]},
    }
}


def _namespaces_root() -> Path:
    """Root of the per-namespace data tree (``{data_dir}/namespaces``)."""
    from core.config import Settings

    return Path(Settings()._resolve_under_data("namespaces"))  # noqa: SLF001


def _env_allowlist() -> Optional[frozenset[str]]:
    raw = os.environ.get(ALLOWLIST_ENV, "")
    names = {n.strip() for n in raw.replace(",", " ").split() if n.strip()}
    return frozenset(names) if names else None


def _on_disk_namespaces() -> List[str]:
    """Namespace directories that carry a ``workflow.db``.

    Dot-prefixed directories are operator backups (``.owner-*-20261016``,
    …) and never surface; they are not namespaces.
    """
    root = _namespaces_root()
    found: List[str] = []
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            if not (entry / "workflow.db").is_file():
                continue
            found.append(entry.name)
    return found


def _resolve_namespace(namespace: str) -> Path:
    """Validate ``namespace`` and return its ``workflow.db`` path.

    Raises :class:`NodeUserError` (LLM-correctable) with the available
    namespace list so the calling agent can self-correct in one turn.
    """
    name = (namespace or "").strip()
    if not name:
        raise NodeUserError(
            "namespace is required for this operation. "
            "Call list_namespaces first to see what this host exposes."
        )
    from services.tenancy import NAMESPACE_PATTERN

    # Fullmatch against the tenancy pattern rejects ``..``, separators,
    # dots, uppercase and over-long names in one shot — the string is
    # safe to place inside a path join afterwards.
    import re

    if not re.fullmatch(NAMESPACE_PATTERN, name):
        raise NodeUserError(
            f"Invalid namespace {name!r}: must match {NAMESPACE_PATTERN} "
            "(lowercase, DNS-ish). Call list_namespaces for the valid set."
        )
    allowed = _env_allowlist()
    if allowed is not None and name not in allowed:
        raise NodeUserError(
            f"Namespace {name!r} is not in the auditable allowlist "
            f"(${ALLOWLIST_ENV}). Available: {', '.join(sorted(allowed))}"
        )
    db_path = _namespaces_root() / name / "workflow.db"
    if not db_path.is_file():
        available = _on_disk_namespaces()
        raise NodeUserError(
            f"Namespace {name!r} has no workflow.db on this host. "
            f"Available: {', '.join(available) if available else '(none)'}"
        )
    return db_path


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open ``db_path`` strictly read-only (SQLite URI ``mode=ro``)."""
    con = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def _truncate(value: str, cap: int) -> str:
    if len(value) <= cap:
        return value
    return value[:cap] + _TRUNC_SUFFIX.format(len(value) - cap)


def _truncate_deep(value: Any, cap: int, touched: List[str], key: str) -> Any:
    """Recursively cap string lengths inside a JSON-shaped value."""
    if isinstance(value, str):
        clipped = _truncate(value, cap)
        if clipped is not value:
            touched.append(key)
        return clipped
    if isinstance(value, dict):
        return {
            k: _truncate_deep(v, cap, touched, f"{key}.{k}" if key else str(k))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _truncate_deep(v, cap, touched, f"{key}[{i}]")
            for i, v in enumerate(value)
        ]
    return value


def _fit_parameters(parameters: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    """Cap strings so the JSON payload fits ``_TOTAL_CAP``.

    Always truncates from the ORIGINAL dict — re-truncating an already
    truncated string would compound the markers and lie about how much
    was cut. The cap halves until the serialized form fits (floor keeps
    a readable minimum even for pathological workflows).
    """
    cap = _STR_CAP
    while True:
        touched: List[str] = []
        capped = _truncate_deep(parameters, cap, touched, "")
        size = len(json.dumps(capped, ensure_ascii=False, default=str))
        if size <= _TOTAL_CAP or cap <= _TOTAL_CAP_FLOOR:
            return capped, touched
        cap = max(cap // 2, _TOTAL_CAP_FLOOR)


class WorkflowIntrospectParams(BaseModel):
    operation: WorkflowIntrospectOperation = "list_namespaces"
    namespace: str = Field(
        default="",
        description="Target namespace (from list_namespaces).",
        json_schema_extra=_NAMESPACE,
    )
    workflow: str = Field(
        default="",
        description="Workflow to inspect: name, id or slug (case-insensitive).",
        json_schema_extra=_WORKFLOW,
    )
    include: Literal["all", "graph", "params"] = Field(
        default="all",
        description="graph = nodes+edges only; params = persisted node parameters only.",
        json_schema_extra=_INCLUDE,
    )
    model_config = ConfigDict(extra="ignore")


class WorkflowIntrospectOutput(BaseModel):
    operation: Optional[str] = None
    namespace: Optional[str] = None
    namespaces: Optional[List[str]] = None
    workflows: Optional[List[Dict[str, Any]]] = None
    count: Optional[int] = None
    workflow: Optional[Dict[str, Any]] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    parameters: Optional[Dict[str, Dict[str, Any]]] = None
    truncated: Optional[List[str]] = None
    model_config = ConfigDict(extra="allow")


class WorkflowIntrospectNode(ToolNode):
    type = "workflowIntrospect"
    display_name = "Workflow Introspect"
    subtitle = "Cross-Namespace Reader"
    group = ("workflow", "tool")
    description = (
        "Read-only reader of workflow definitions across namespaces: "
        "graphs, edges, prompts and inline skills, for structural audits"
    )
    tool_name = "workflow_introspect"
    tool_description = (
        "Read-only introspection of OpenCompany workflows across namespaces on this "
        "host. list_namespaces: which namespaces exist. list_workflows(namespace): "
        "id/name/slug/description/updated_at per workflow. get_workflow(namespace, "
        "workflow, include): the full structural material — nodes (id/type/label), "
        "edges (source/target/sourceHandle/targetHandle — which agent owns which "
        "tool), and every node's persisted parameters (system_message prompts, "
        "skills_config with inline skills). Payloads are large: get_workflow output "
        "is audit MATERIAL, not chat text — save it into the workspace with "
        "file_modify and analyze the file instead of echoing it. Read-only: "
        "credentials databases are never read and nothing can be written."
    )
    component_kind = "tool"
    handles = (
        {"name": "input-main", "kind": "input", "position": "left", "label": "Input", "role": "main"},
        {"name": "output-tool", "kind": "output", "position": "top", "label": "Tool", "role": "tools"},
    )
    task_queue = TaskQueue.REST_API
    Params = WorkflowIntrospectParams
    Output = WorkflowIntrospectOutput

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    @Operation("list_namespaces")
    async def list_namespaces(
        self, ctx: NodeContext, params: WorkflowIntrospectParams
    ) -> WorkflowIntrospectOutput:
        allowed = _env_allowlist()
        namespaces = [
            ns for ns in _on_disk_namespaces()
            if allowed is None or ns in allowed
        ]
        return WorkflowIntrospectOutput(
            operation="list_namespaces", namespaces=namespaces, count=len(namespaces)
        )

    @Operation("list_workflows")
    async def list_workflows(
        self, ctx: NodeContext, params: WorkflowIntrospectParams
    ) -> WorkflowIntrospectOutput:
        db_path = _resolve_namespace(params.namespace)
        namespace = db_path.parent.name

        def _query() -> List[Dict[str, Any]]:
            con = _connect_readonly(db_path)
            try:
                rows = con.execute(
                    "SELECT id, name, slug, description, updated_at "
                    "FROM workflows ORDER BY updated_at DESC"
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                con.close()

        workflows = await asyncio.to_thread(_query)
        return WorkflowIntrospectOutput(
            operation="list_workflows",
            namespace=namespace,
            workflows=workflows,
            count=len(workflows),
        )

    @Operation("get_workflow")
    async def get_workflow(
        self, ctx: NodeContext, params: WorkflowIntrospectParams
    ) -> WorkflowIntrospectOutput:
        db_path = _resolve_namespace(params.namespace)
        namespace = db_path.parent.name
        target = (params.workflow or "").strip()
        if not target:
            raise NodeUserError(
                "workflow is required for get_workflow — a name, id or slug "
                "(list_workflows shows them)."
            )

        def _query() -> Dict[str, Any]:
            con = _connect_readonly(db_path)
            try:
                rows = con.execute(
                    "SELECT id, name, slug, description, updated_at, data "
                    "FROM workflows ORDER BY updated_at DESC"
                ).fetchall()
                key = target.lower()
                exact = [
                    r for r in rows
                    if key in ((r["name"] or "").lower(), (r["id"] or "").lower(), (r["slug"] or "").lower())
                ]
                # LLM ergonomics: the model says "CartolaTax", the workflow is
                # "CartolaTax — Statement Import". Exact match wins; otherwise
                # substring over name/slug — and if that is still ambiguous,
                # name the candidates instead of guessing.
                fuzzy = [
                    r for r in rows
                    if key in (r["name"] or "").lower()
                    or key in (r["slug"] or "").lower()
                ]
                matches = exact or fuzzy
                if not matches:
                    listing = [f"{r['name']} ({r['slug']})" for r in rows]
                    raise NodeUserError(
                        f"Workflow {target!r} not found in namespace "
                        f"{namespace!r}. Available: "
                        f"{'; '.join(listing) if listing else '(none)'}"
                    )
                if len(matches) > 1:
                    listing = [f"{r['name']} ({r['slug']})" for r in matches]
                    raise NodeUserError(
                        f"Workflow {target!r} is ambiguous in namespace "
                        f"{namespace!r}: {'; '.join(listing)}. Use the exact "
                        "name, id or slug."
                    )
                row = matches[0]
                params_rows = con.execute(
                    "SELECT node_id, parameters FROM node_parameters "
                    "WHERE node_id LIKE ? ORDER BY node_id",
                    (row["id"] + ":%",),
                ).fetchall()
                return {"row": dict(row), "params_rows": [dict(r) for r in params_rows]}
            finally:
                con.close()

        result = await asyncio.to_thread(_query)
        row = result["row"]
        try:
            data = json.loads(row.get("data") or "{}")
        except (TypeError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}

        prefix = row["id"] + ":"
        nodes: List[Dict[str, Any]] = []
        for node in data.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_data = node.get("data") or {}
            nodes.append(
                {
                    "id": node.get("id"),
                    "type": node.get("type") or node_data.get("type"),
                    "label": node_data.get("label") or node_data.get("name") or "",
                }
            )
        edges: List[Dict[str, Any]] = []
        for edge in data.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            edges.append(
                {
                    k: edge.get(k)
                    for k in ("source", "target", "sourceHandle", "targetHandle")
                    if edge.get(k) is not None
                }
            )

        parameters: Dict[str, Dict[str, Any]] = {}
        for pr in result["params_rows"]:
            node_id = pr.get("node_id") or ""
            short = node_id[len(prefix):] if node_id.startswith(prefix) else node_id
            try:
                parsed = json.loads(pr.get("parameters") or "{}")
            except (TypeError, ValueError):
                parsed = {"_raw": pr.get("parameters")}
            parameters[short] = parsed if isinstance(parsed, dict) else {"_raw": parsed}

        output = WorkflowIntrospectOutput(
            operation="get_workflow",
            namespace=namespace,
            workflow={
                "id": row["id"],
                "name": row["name"],
                "slug": row["slug"],
                "description": row["description"],
                "updated_at": row["updated_at"],
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
        )
        if params.include in ("all", "graph"):
            output.nodes = nodes
            output.edges = edges
        if params.include in ("all", "params"):
            capped, touched = _fit_parameters(parameters)
            output.parameters = capped
            output.truncated = touched
        return output
