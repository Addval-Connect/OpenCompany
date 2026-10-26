"""The WS initial_status snapshot is tenant-scoped for plugin status slots.

A browser that connects AFTER a tenant's bot connected must receive THAT
tenant's telegram snapshot in ``initial_status`` — the pre-fix spread of
the raw ``_status`` delivered the legacy global slot (which only mirrors
the default namespace), so a live tenant bot displayed "Not connected"
until the next status change happened to re-broadcast.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.status_broadcaster import StatusBroadcaster


pytestmark = pytest.mark.asyncio


@pytest.fixture
def broadcaster():
    b = StatusBroadcaster()
    b._status["telegram"] = {"connected": True, "bot_username": "default_ns_bot"}  # legacy mirror (default only)
    b._status["telegram_by_ns"] = {
        "addval-connect": {"connected": True, "bot_username": "veronicatask_bot"},
    }
    return b


async def _connect_and_capture(b, tenant: str) -> dict:
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()

    with patch(
        "services.status_broadcaster._resolve_connection_namespace",
        new=AsyncMock(return_value=tenant),
    ), patch.object(
        StatusBroadcaster, "_send_deployment_snapshot", new=AsyncMock()
    ), patch("core.container.container") as container:
        container.workflow_service.return_value._get_deployment_manager.return_value.get_deployed_workflows.return_value = []
        await b.connect(ws)

    frames = [c.args[0] for c in ws.send_json.await_args_list]
    return next(f for f in frames if f.get("type") == "initial_status")


async def test_initial_status_carries_the_tenant_bot(broadcaster):
    frame = await _connect_and_capture(broadcaster, "addval-connect")
    assert frame["data"]["telegram"]["bot_username"] == "veronicatask_bot"


async def test_initial_status_is_clean_for_a_tenant_without_bot(broadcaster):
    frame = await _connect_and_capture(broadcaster, "bluedoc")
    assert frame["data"]["telegram"]["connected"] is False
    assert frame["data"]["telegram"]["bot_username"] is None


async def test_initial_status_does_not_leak_the_legacy_global_bot(broadcaster):
    frame = await _connect_and_capture(broadcaster, "addval-connect")
    assert frame["data"]["telegram"]["bot_username"] != "default_ns_bot"
