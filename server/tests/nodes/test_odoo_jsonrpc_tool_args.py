"""Per-call instance override for the Odoo JSON-RPC tool (2026-10-20).

The agent may target a DIFFERENT Odoo instance than the one configured on
the node by passing the COMPLETE connection (host/db/username/api_key);
omitting the connection fields keeps the persisted node config. The
override is atomic — a partial one must be rejected so a hallucinated
host can never be paired with the persisted credentials of another
instance (the failure mode the connection lock was built to prevent).
"""

from typing import Any, List, Optional, Tuple
from unittest.mock import patch

import pytest

from nodes.tool.odoo_jsonrpc import (
    OdooJsonRpcNode,
    OdooJsonRpcParams,
    OdooJsonRpcToolInput,
)
from services.plugin import NodeContext, NodeUserError

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

PERSISTED = OdooJsonRpcParams(
    host="configured.odoo.com",
    db="cfg-db",
    username="cfg@addval.cl",
    api_key="cfg-key",
    timeout=30,
)

OVERRIDE_ARGS = {
    "host": "target.odoo.com",
    "db": "target-db",
    "username": "target@addval.cl",
    "api_key": "target-key",
}


def _ctx(cfg: Optional[OdooJsonRpcParams] = PERSISTED) -> NodeContext:
    raw: dict = {}
    if cfg is not None:
        raw["_tool_config"] = cfg
    return NodeContext(
        node_id="odoo-1",
        node_type="odooJsonRpc",
        workflow_id="wf-test",
        raw=raw,
    )


@pytest.fixture()
def rpc_log(monkeypatch):
    """Capture _rpc calls; fake login -> uid 2, execute_kw -> {"ok": 1}."""
    calls: List[Tuple[str, str, list]] = []

    async def fake_rpc(self, client, url, service, method, args):
        calls.append((url, service, list(args)))
        if service == "common" and method == "login":
            return 2
        return {"records": 1}

    monkeypatch.setattr(OdooJsonRpcNode, "_rpc", fake_rpc)
    return calls


# --------------------------------------------------------------------------- #
# Schema validation — the atomic override contract
# --------------------------------------------------------------------------- #


def test_partial_override_is_rejected():
    with pytest.raises(ValueError, match="all-or-nothing"):
        OdooJsonRpcToolInput(
            model="res.partner",
            method="search_count",
            host="target.odoo.com",
        )


def test_partial_override_without_credentials_is_rejected():
    # host + db without username/api_key would pair a new host with the
    # PERSISTED credentials — exactly the mix the lock prevents.
    with pytest.raises(ValueError, match="all-or-nothing"):
        OdooJsonRpcToolInput(
            model="res.partner",
            method="search_count",
            host="target.odoo.com",
            db="target-db",
        )


def test_complete_override_validates():
    args = OdooJsonRpcToolInput(
        model="res.partner", method="search_count", **OVERRIDE_ARGS
    )
    assert args.host == "target.odoo.com"
    assert args.api_key == "target-key"


def test_no_override_validates():
    args = OdooJsonRpcToolInput(model="res.partner", method="search_count")
    assert args.host == ""  # empty string = not provided (plain str, no anyOf)


# --------------------------------------------------------------------------- #
# Dispatch — fallback vs override
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_without_override_uses_persisted_config(rpc_log):
    node = OdooJsonRpcNode()
    out = await node.query(
        _ctx(),
        OdooJsonRpcToolInput(model="res.partner", method="search_count"),
    )
    assert out.ok is True
    login_url, service, login_args = rpc_log[0]
    assert login_url == "https://configured.odoo.com/jsonrpc"
    assert service == "common"
    assert login_args == ["cfg-db", "cfg@addval.cl", "cfg-key"]
    exec_url, exec_service, exec_args = rpc_log[1]
    assert exec_service == "object"
    # execute_kw args carry the PERSISTED db + api_key, not the override.
    assert exec_args[:3] == ["cfg-db", 2, "cfg-key"]


@pytest.mark.asyncio
async def test_complete_override_connects_to_target_instance(rpc_log):
    node = OdooJsonRpcNode()
    out = await node.query(
        _ctx(),
        OdooJsonRpcToolInput(
            model="res.partner", method="search_count", **OVERRIDE_ARGS
        ),
    )
    assert out.ok is True
    login_url, _service, login_args = rpc_log[0]
    assert login_url == "https://target.odoo.com/jsonrpc"
    assert login_args == ["target-db", "target@addval.cl", "target-key"]
    exec_url, exec_service, exec_args = rpc_log[1]
    assert exec_url == "https://target.odoo.com/jsonrpc"
    assert exec_service == "object"
    assert exec_args[:3] == ["target-db", 2, "target-key"]


@pytest.mark.asyncio
async def test_override_host_is_sanitized_like_the_operator_field(rpc_log):
    node = OdooJsonRpcNode()
    await node.query(
        _ctx(),
        OdooJsonRpcToolInput(
            model="res.partner",
            method="search_count",
            host="https://target.odoo.com/some/path",
            db="target-db",
            username="target@addval.cl",
            api_key="target-key",
        ),
    )
    assert rpc_log[0][0] == "https://target.odoo.com/jsonrpc"


@pytest.mark.asyncio
async def test_override_keeps_persisted_timeout(rpc_log):
    """timeout is an operational knob, not instance identity."""
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    async def fake_rpc(self, client, url, service, method, args):
        return 2 if service == "common" else {"ok": 1}

    with patch("nodes.tool.odoo_jsonrpc.httpx.AsyncClient", FakeClient):
        with patch.object(OdooJsonRpcNode, "_rpc", fake_rpc):
            await OdooJsonRpcNode().query(
                _ctx(),
                OdooJsonRpcToolInput(
                    model="res.partner", method="search_count", **OVERRIDE_ARGS
                ),
            )
    assert captured["timeout"] == 30.0


# --------------------------------------------------------------------------- #
# Unconfigured node — the actionable error mentions both remediation paths
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_unconfigured_node_error_names_the_override_path(rpc_log):
    node = OdooJsonRpcNode()
    with pytest.raises(NodeUserError, match="complete instance connection"):
        await node.query(
            _ctx(cfg=OdooJsonRpcParams()),
            OdooJsonRpcToolInput(model="res.partner", method="search_count"),
        )


# --------------------------------------------------------------------------- #
# Output language knob (2026-11-11) — optional operator-side context.lang.
# Raw RPC reads answer in the source language (en_US) even when the target
# instance has es_CL installed; injecting context.lang makes translated
# fields (account names, taxes, products) come back localized.
# --------------------------------------------------------------------------- #


SPANISH = OdooJsonRpcParams(
    host="configured.odoo.com",
    db="cfg-db",
    username="cfg@addval.cl",
    api_key="cfg-key",
    timeout=30,
    lang="es_CL",
)


@pytest.mark.asyncio
async def test_node_lang_is_injected_as_context_lang(rpc_log):
    node = OdooJsonRpcNode()
    out = await node.query(
        _ctx(cfg=SPANISH),
        OdooJsonRpcToolInput(model="account.account", method="search_read"),
    )
    assert out.ok is True
    _url, _service, exec_args = rpc_log[1]
    kwargs = exec_args[-1]
    assert kwargs["context"]["lang"] == "es_CL"


@pytest.mark.asyncio
async def test_empty_lang_keeps_kwargs_untouched(rpc_log):
    """Default behaviour: no context key at all — identical to pre-knob calls."""
    node = OdooJsonRpcNode()
    await node.query(
        _ctx(),
        OdooJsonRpcToolInput(model="res.partner", method="search_read"),
    )
    _url, _service, exec_args = rpc_log[1]
    assert "context" not in exec_args[-1]


@pytest.mark.asyncio
async def test_node_lang_wins_over_model_lang_and_keeps_other_keys(rpc_log):
    """Operator intent is deterministic: forced lang, preserved extra keys."""
    node = OdooJsonRpcNode()
    await node.query(
        _ctx(cfg=SPANISH),
        OdooJsonRpcToolInput(
            model="res.partner",
            method="search_read",
            kwargs={"context": {"lang": "en_US", "tz": "America/Santiago"}},
        ),
    )
    _url, _service, exec_args = rpc_log[1]
    context = exec_args[-1]["context"]
    assert context["lang"] == "es_CL"
    assert context["tz"] == "America/Santiago"


@pytest.mark.asyncio
async def test_lang_applies_to_every_method_shape(rpc_log):
    """The kwargs dict is always the last positional arg for every method."""
    node = OdooJsonRpcNode()
    methods = [
        OdooJsonRpcToolInput(model="res.partner", method="search_count"),
        OdooJsonRpcToolInput(model="res.partner", method="read", ids=[1]),
        OdooJsonRpcToolInput(model="res.partner", method="create", values={"name": "x"}),
        OdooJsonRpcToolInput(
            model="res.partner", method="call", method_name="some_custom_method"
        ),
    ]
    for tool_input in methods:
        rpc_log.clear()
        await node.query(_ctx(cfg=SPANISH), tool_input)
        _url, _service, exec_args = rpc_log[1]
        assert exec_args[-1]["context"]["lang"] == "es_CL", tool_input.method


@pytest.mark.asyncio
async def test_lang_survives_per_call_instance_override(rpc_log):
    """lang/timeout are operational knobs, not instance identity."""
    node = OdooJsonRpcNode()
    await node.query(
        _ctx(cfg=SPANISH),
        OdooJsonRpcToolInput(
            model="res.partner", method="search_count", **OVERRIDE_ARGS
        ),
    )
    login_url, _service, _login_args = rpc_log[0]
    assert login_url == "https://target.odoo.com/jsonrpc"
    _url, _service, exec_args = rpc_log[1]
    assert exec_args[-1]["context"]["lang"] == "es_CL"
