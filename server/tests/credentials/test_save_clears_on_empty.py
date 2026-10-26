"""Saving an EMPTY credential value = CLEAR it.

The credentials panel's secondary fields (e.g. the optional Telegram
owner chat id) save through ``handle_save_api_key``. An operator clearing
the field expects the stored row to GO AWAY — storing an empty ciphertext
instead kept the field reading back as "" forever while the row lingered
(the "no permite guardar/borrar" symptom on the Telegram panel).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.credentials import handlers as cred_handlers


pytestmark = pytest.mark.credentials


def _ws():
    return SimpleNamespace(state=SimpleNamespace(active_namespace="tenant-a"))


def _patches(auth):
    idempotency = MagicMock()
    idempotency.run = lambda request_id, fn: fn()
    return (
        patch.object(cred_handlers.container, "auth_service", lambda: auth),
        patch.object(cred_handlers, "get_status_broadcaster", lambda: MagicMock(
            broadcast_credential_event=AsyncMock(),
        )),
        patch("services.idempotency.get_idempotency_store", lambda _ns: idempotency),
    )


@pytest.mark.asyncio
async def test_empty_save_clears_instead_of_storing():
    auth = MagicMock()
    auth.store_api_key = AsyncMock()
    auth.remove_api_key = AsyncMock(return_value=True)

    with _patches(auth)[0], _patches(auth)[1], _patches(auth)[2]:
        result = await cred_handlers.handle_save_api_key(
            {"provider": "telegram_owner_chat_id", "api_key": "   "},
            _ws(),
        )

    assert result["success"] is True
    assert result["cleared"] is True
    auth.remove_api_key.assert_awaited_once_with(
        "telegram_owner_chat_id",
        session_id="default",
        credential_customer_id="tenant-a",
    )
    auth.store_api_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_empty_save_stores_normally():
    auth = MagicMock()
    auth.store_api_key = AsyncMock(return_value=True)
    auth.remove_api_key = AsyncMock()

    with _patches(auth)[0], _patches(auth)[1], _patches(auth)[2]:
        result = await cred_handlers.handle_save_api_key(
            {"provider": "telegram_owner_chat_id", "api_key": "8386124997"},
            _ws(),
        )

    assert result["success"] is True
    assert result.get("cleared") is None
    auth.store_api_key.assert_awaited_once()
    auth.remove_api_key.assert_not_awaited()
