"""Tests for the per-message namespace re-seal on the browser WebSocket.

The browser WS seals its namespace once at connect (JWT claim). A future
soft namespace switch — no page reload — needs the message loop to
re-seal from the message, VALIDATED against the user's namespace
membership: the field must never become a tenant-escape hatch.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.namespace_context import get_active_namespace, set_active_namespace
from routers.websocket import _reseal_message_namespace


pytestmark = pytest.mark.node_contract


@pytest.fixture(autouse=True)
def _default_ns():
    set_active_namespace("default")
    yield
    set_active_namespace("default")


def _ws(active_namespace: str = "connect-time-ns", user_id: str = "user-1"):
    state = SimpleNamespace(active_namespace=active_namespace, user_id=user_id)
    return SimpleNamespace(state=state)


@pytest.mark.asyncio
async def test_no_namespace_field_is_a_noop():
    ws = _ws()
    await _reseal_message_namespace(ws, {"type": "ping"})
    assert get_active_namespace() == "default"
    assert ws.state.active_namespace == "connect-time-ns"


@pytest.mark.asyncio
async def test_member_user_gets_resealed():
    settings = SimpleNamespace(multi_tenant_namespaces=True)
    database = MagicMock()
    database.is_user_in_namespace = AsyncMock(return_value=True)

    with patch("core.container.container") as container:
        container.settings.return_value = settings
        container.database.return_value = database
        ws = _ws()
        await _reseal_message_namespace(ws, {"credential_customer_id": "tenant-a"})

    assert get_active_namespace() == "tenant-a"
    assert ws.state.active_namespace == "tenant-a"
    database.is_user_in_namespace.assert_awaited_once_with("user-1", "tenant-a")


@pytest.mark.asyncio
async def test_non_member_is_refused_fail_closed():
    settings = SimpleNamespace(multi_tenant_namespaces=True)
    database = MagicMock()
    database.is_user_in_namespace = AsyncMock(return_value=False)

    with patch("core.container.container") as container:
        container.settings.return_value = settings
        container.database.return_value = database
        ws = _ws()
        await _reseal_message_namespace(ws, {"credential_customer_id": "other-tenant"})

    # Fail-closed: the connect-time seal survives a non-member's request.
    assert get_active_namespace() == "default"
    assert ws.state.active_namespace == "connect-time-ns"


@pytest.mark.asyncio
async def test_multi_tenant_off_never_reseals():
    settings = SimpleNamespace(multi_tenant_namespaces=False)

    with patch("core.container.container") as container:
        container.settings.return_value = settings
        ws = _ws()
        await _reseal_message_namespace(ws, {"credential_customer_id": "tenant-a"})

    assert get_active_namespace() == "default"
