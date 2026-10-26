"""Contract tests for telegram_social nodes.

Covers: telegramSend, telegramReceive, socialSend, socialReceive.

These tests freeze the input -> output behaviour documented in
`docs-internal/node-logic-flows/telegram_social/`. A refactor that breaks any
of these indicates the docs (and the user-visible contract) must be updated.

All external boundaries are mocked:
  - TelegramService singleton is replaced via ``get_telegram_service`` patch.
  - event_waiter is patched at the module-attribute level inside both
    ``services.node_executor`` and ``services.handlers.triggers`` so the
    generic trigger path resolves a canned event without blocking.
  - The WhatsApp send router is patched for socialSend.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force import so unittest.mock.patch("nodes.telegram._service.X") can
# resolve the attribute path. The TelegramService now lives inside the
# plugin folder; nothing telegram-specific remains under ``services/``.
import nodes.telegram._service  # noqa: F401

from tests.nodes._mocks import patched_broadcaster, patched_container


pytestmark = pytest.mark.node_contract


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _make_telegram_service(*, connected: bool = True, owner_chat_id=None):
    """Build a stub TelegramService singleton mirroring the real interface."""
    svc = MagicMock(name="TelegramService")
    svc.connected = connected
    svc.owner_chat_id = owner_chat_id
    svc.set_owner = AsyncMock(return_value=None)
    svc.send_message = AsyncMock(
        return_value={
            "message_id": 42,
            "chat_id": 111,
            "date": "2026-04-15T00:00:00",
            "text": "hi",
        }
    )
    svc.send_photo = AsyncMock(return_value={"message_id": 43, "chat_id": 111, "date": "2026-04-15T00:00:00"})
    svc.send_document = AsyncMock(return_value={"message_id": 44, "chat_id": 111, "date": "2026-04-15T00:00:00"})
    svc.send_location = AsyncMock(return_value={"message_id": 45, "chat_id": 111, "date": "2026-04-15T00:00:00"})
    svc.send_contact = AsyncMock(return_value={"message_id": 46, "chat_id": 111, "date": "2026-04-15T00:00:00"})
    return svc


def _patch_telegram_service(svc):
    """Patch the get_telegram_service accessor at its canonical path."""
    return patch("nodes.telegram._service.get_telegram_service", return_value=svc)


# ============================================================================
# telegramSend
# ============================================================================


class TestTelegramSend:
    async def test_text_happy_path_with_self_recipient(self, harness):
        svc = _make_telegram_service(connected=True, owner_chat_id=9999)

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramSend",
                {"recipient_type": "self", "message_type": "text", "text": "hello"},
            )

        harness.assert_envelope(result, success=True)
        payload = result["result"]
        assert payload["message_id"] == 42
        assert payload["chat_id"] == 111
        assert payload["message_type"] == "text"
        svc.send_message.assert_awaited_once()
        call_kwargs = svc.send_message.await_args.kwargs
        assert call_kwargs["chat_id"] == 9999
        assert call_kwargs["text"] == "hello"

    async def test_not_connected_short_circuits(self, harness):
        svc = _make_telegram_service(connected=False)

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramSend",
                {"recipient_type": "self", "message_type": "text", "text": "x"},
            )

        harness.assert_envelope(result, success=False)
        assert "not connected" in result["error"].lower()
        svc.send_message.assert_not_awaited()

    async def test_self_recipient_restores_owner_from_credentials(self, harness):
        # Service has no owner in memory, but credentials DB has one saved.
        svc = _make_telegram_service(connected=True, owner_chat_id=None)

        with _patch_telegram_service(svc), patched_container(auth_api_keys={"telegram_owner_chat_id": "7777"}):
            result = await harness.execute(
                "telegramSend",
                {"recipient_type": "self", "message_type": "text", "text": "hi"},
            )

        harness.assert_envelope(result, success=True)
        svc.set_owner.assert_awaited_once_with(7777)
        # send_message chat_id should be the restored owner id
        assert svc.send_message.await_args.kwargs["chat_id"] == 7777

    async def test_self_recipient_with_no_owner_returns_error(self, harness):
        svc = _make_telegram_service(connected=True, owner_chat_id=None)

        with _patch_telegram_service(svc), patched_container(auth_api_keys={}):
            result = await harness.execute(
                "telegramSend",
                {"recipient_type": "self", "message_type": "text", "text": "hi"},
            )

        harness.assert_envelope(result, success=False)
        assert "owner" in result["error"].lower()
        svc.send_message.assert_not_awaited()

    async def test_user_recipient_requires_chat_id(self, harness):
        svc = _make_telegram_service(connected=True)

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramSend",
                {"recipient_type": "user", "message_type": "text", "text": "x"},
            )

        harness.assert_envelope(result, success=False)
        assert "chat_id" in result["error"].lower()

    async def test_text_message_without_text_short_circuits(self, harness):
        svc = _make_telegram_service(connected=True, owner_chat_id=1)

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramSend",
                {"recipient_type": "self", "message_type": "text"},
            )

        harness.assert_envelope(result, success=False)
        assert "text is required" in result["error"].lower()

    async def test_photo_requires_media_url(self, harness):
        svc = _make_telegram_service(connected=True, owner_chat_id=1)

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramSend",
                {"recipient_type": "self", "message_type": "photo"},
            )

        harness.assert_envelope(result, success=False)
        assert "media_url" in result["error"].lower()

    async def test_photo_happy_path_passes_caption_and_parse_mode(self, harness):
        svc = _make_telegram_service(connected=True, owner_chat_id=1)

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramSend",
                {
                    "recipient_type": "user",
                    "chat_id": "123",
                    "message_type": "photo",
                    "media_url": "https://example.com/x.jpg",
                    "caption": "ok",
                    "parse_mode": "HTML",
                    "silent": True,
                },
            )

        harness.assert_envelope(result, success=True)
        svc.send_photo.assert_awaited_once()
        kwargs = svc.send_photo.await_args.kwargs
        assert kwargs["photo"] == "https://example.com/x.jpg"
        assert kwargs["caption"] == "ok"
        assert kwargs["parse_mode"] == "HTML"
        assert kwargs["disable_notification"] is True

    async def test_location_requires_coordinates(self, harness):
        svc = _make_telegram_service(connected=True, owner_chat_id=1)

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramSend",
                {"recipient_type": "self", "message_type": "location"},
            )

        harness.assert_envelope(result, success=False)
        assert "latitude" in result["error"].lower()

    async def test_unsupported_message_type(self, harness):
        svc = _make_telegram_service(connected=True, owner_chat_id=1)

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramSend",
                {"recipient_type": "self", "message_type": "hologram"},
            )

        harness.assert_envelope(result, success=False)
        assert "invalid parameters" in result["error"].lower()

    async def test_sent_flag_is_emitted_on_success(self, harness):
        """``sent`` was declared on the Output model but never populated, so
        ``exclude_unset=True`` meant the data picker advertised a phantom
        field. It must now appear in the payload."""
        svc = _make_telegram_service(connected=True, owner_chat_id=9999)

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramSend",
                {"recipient_type": "self", "message_type": "text", "text": "hello"},
            )

        harness.assert_envelope(result, success=True)
        assert result["result"]["sent"] is True

    async def test_multipart_send_reports_the_whole_chain(self, harness):
        """A text over 4096 becomes several Telegram messages; the caller
        needs every id, not just the first."""
        svc = _make_telegram_service(connected=True, owner_chat_id=1)
        svc.send_message = AsyncMock(
            return_value={
                "message_id": 42,
                "chat_id": 111,
                "date": "2026-04-15T00:00:00",
                "text": "hi",
                "parts": 3,
                "message_ids": [42, 43, 44],
            }
        )

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramSend",
                {"recipient_type": "self", "message_type": "text", "text": "x" * 9000},
            )

        payload = result["result"]
        assert payload["parts"] == 3
        assert payload["message_ids"] == [42, 43, 44]

    async def test_caption_spill_surfaces_on_the_output(self, harness):
        svc = _make_telegram_service(connected=True, owner_chat_id=1)
        svc.send_photo = AsyncMock(
            return_value={
                "message_id": 43,
                "chat_id": 111,
                "date": "2026-04-15T00:00:00",
                "caption_truncated": True,
                "follow_up_message_ids": [44],
            }
        )

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramSend",
                {
                    "recipient_type": "self",
                    "message_type": "photo",
                    "media_url": "https://example.com/a.jpg",
                    "caption": "A" * 2000,
                },
            )

        payload = result["result"]
        assert payload["caption_truncated"] is True
        assert payload["follow_up_message_ids"] == [44]


# ============================================================================
# telegramReceive (trigger via generic handle_trigger_node + event_waiter)
# ============================================================================


def _make_waiter_stub(*, canned_event=None, is_trigger=True, wait_side_effect=None):
    """Fake event_waiter module with just the methods the trigger path calls.

    Scaling-branch plugin trigger does `waiter = event_waiter.register(...)`
    (sync) and then `await waiter.future`, so `register` is a sync MagicMock
    and `waiter.future` is a pre-resolved asyncio.Future (or raises the
    side-effect exception when awaited).
    """
    import asyncio

    loop = asyncio.get_event_loop()
    future = loop.create_future()
    if wait_side_effect is not None:
        future.set_exception(wait_side_effect)
    else:
        future.set_result(canned_event or {})

    waiter_obj = MagicMock(name="Waiter")
    waiter_obj.id = "waiter-test-id"
    waiter_obj.future = future

    stub = MagicMock(name="event_waiter_module")
    stub.is_trigger_node = MagicMock(return_value=is_trigger)
    stub.get_trigger_config = MagicMock(
        return_value=MagicMock(
            node_type="telegramReceive",
            event_type="telegram_message_received",
            display_name="Telegram Message",
        )
    )
    stub.register = AsyncMock(return_value=waiter_obj)
    # Kept for back-compat with tests still asserting wait_for_event calls.
    if wait_side_effect is not None:
        stub.wait_for_event = AsyncMock(side_effect=wait_side_effect)
    else:
        stub.wait_for_event = AsyncMock(return_value=canned_event or {})
    stub.run_trigger_precheck = AsyncMock(return_value=None)
    stub.get_backend_mode = MagicMock(return_value="asyncio.Future")
    stub.cancel = MagicMock(return_value=True)
    stub.dispatch = MagicMock(return_value=1)
    return stub


class TestTelegramReceive:
    CANNED = {
        "message_id": 10,
        "chat_id": 555,
        "chat_type": "private",
        "chat_title": None,
        "from_id": 777,
        "from_username": "alice",
        "from_first_name": "Alice",
        "from_last_name": None,
        "is_bot": False,
        "text": "hello from alice",
        "content_type": "text",
        "date": "2026-04-15T12:00:00",
        "reply_to_message_id": None,
    }

    async def test_happy_path_returns_canned_event(self, harness):
        svc = _make_telegram_service(connected=True, owner_chat_id=42)
        waiter = _make_waiter_stub(canned_event=self.CANNED)

        with _patch_telegram_service(svc), patched_broadcaster(), patch("services.event_waiter", waiter):
            result = await harness.execute(
                "telegramReceive",
                {"sender_filter": "all", "content_type_filter": "all"},
            )

        harness.assert_envelope(result, success=True)
        assert result["result"]["text"] == "hello from alice"
        assert result["result"]["chat_id"] == 555
        # Plugin trigger calls register synchronously and awaits waiter.future.
        waiter.register.assert_called_once()

    async def test_media_event_survives_the_trigger_envelope(self, harness):
        """A voice message must reach the workflow with its normalized media
        block intact — before this, video/audio/voice/sticker file_ids were
        dropped entirely."""
        svc = _make_telegram_service(connected=True, owner_chat_id=42)
        event = {
            **self.CANNED,
            "text": "",
            "content_type": "voice",
            "has_media": True,
            "voice": {"file_id": "VOICE-1", "duration": 4, "mime_type": "audio/ogg"},
            "media": {
                "kind": "voice",
                "file_id": "VOICE-1",
                "mime_type": "audio/ogg",
                "file_name": "uv.ogg",
                "duration": 4,
                "file_path": None,
                "downloaded": False,
            },
        }
        waiter = _make_waiter_stub(canned_event=event)

        with _patch_telegram_service(svc), patched_broadcaster(), patch("services.event_waiter", waiter):
            result = await harness.execute(
                "telegramReceive",
                {"sender_filter": "all", "content_type_filter": "media"},
            )

        harness.assert_envelope(result, success=True)
        payload = result["result"]
        assert payload["content_type"] == "voice"
        assert payload["media"]["file_id"] == "VOICE-1"
        assert payload["media"]["kind"] == "voice"
        assert payload["has_media"] is True
        # The trigger never carries bytes.
        assert payload["media"]["file_path"] is None
        assert payload["media"]["downloaded"] is False

    async def test_bot_not_connected_returns_error(self, harness):
        svc = _make_telegram_service(connected=False)
        waiter = _make_waiter_stub(canned_event=self.CANNED)

        with _patch_telegram_service(svc), patched_broadcaster(), patch("services.event_waiter", waiter):
            result = await harness.execute(
                "telegramReceive",
                {"sender_filter": "all"},
            )

        harness.assert_envelope(result, success=False)
        assert "not connected" in result["error"].lower()
        # Must NOT have registered a waiter when bot is offline (sync call).
        waiter.register.assert_not_called()

    async def test_cancellation_propagates_as_error(self, harness):
        import asyncio

        svc = _make_telegram_service(connected=True, owner_chat_id=1)
        waiter = _make_waiter_stub(wait_side_effect=asyncio.CancelledError())

        with _patch_telegram_service(svc), patched_broadcaster(), patch("services.event_waiter", waiter):
            result = await harness.execute(
                "telegramReceive",
                {"sender_filter": "all"},
            )

        harness.assert_envelope(result, success=False)
        assert "cancel" in result["error"].lower()


# ============================================================================
# telegramGetAttachment (ActionNode + AI tool — downloads file_id into the
# workspace attachments/ folder; Outlook download_attachments pattern)
# ============================================================================


class TestTelegramGetAttachment:
    PAYLOAD = b"%PDF-1.4 telegram attachment test bytes"

    @staticmethod
    def _connected_bot(payload=b"%PDF-1.4 telegram attachment test bytes"):
        """Stub service whose bot resolves and downloads a real Telegram file."""
        svc = _make_telegram_service(connected=True)
        bot = MagicMock(name="Bot")
        tg_file = MagicMock(name="TelegramFile")
        tg_file.file_path = "documents/invoice_42.pdf"
        bot.get_file = AsyncMock(return_value=tg_file)
        bot.download_file = AsyncMock(return_value=payload)
        svc._require_bot = MagicMock(return_value=bot)
        return svc

    async def test_happy_path_saves_into_workspace_attachments(self, harness, tmp_path):
        svc = self._connected_bot()
        ctx = harness.build_context(workspace_dir=str(tmp_path))

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramGetAttachment",
                {"file_id": "DOC-1", "file_name": "invoice_42.pdf", "kind": "document"},
                context=ctx,
            )

        harness.assert_envelope(result, success=True)
        payload = result["result"]
        assert payload["downloaded"] is True
        assert payload["file_id"] == "DOC-1"
        # Slugified stem keeps the real extension (documentParser globs *.pdf).
        assert payload["filename"].startswith("invoice-42-")
        assert payload["filename"].endswith(".pdf")
        assert payload["rel_path"].startswith("attachments/")
        # file_path is absolute and lives under the workspace attachments/ dir.
        assert payload["file_path"].startswith(str(tmp_path))
        assert "attachments/" in payload["file_path"]
        # The bytes actually landed on disk, atomically, unmodified.
        from pathlib import Path

        target = Path(payload["file_path"])
        assert target.is_file()
        assert target.read_bytes() == self.PAYLOAD
        assert payload["size_bytes"] == len(self.PAYLOAD)
        import hashlib

        assert payload["sha256"] == hashlib.sha256(self.PAYLOAD).hexdigest()

    async def test_synthesises_name_and_extension_when_absent(self, harness, tmp_path):
        svc = self._connected_bot()
        ctx = harness.build_context(workspace_dir=str(tmp_path))

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramGetAttachment",
                {"file_id": "VOICE-9", "file_name": "voice_note.ogg"},
                context=ctx,
            )

        harness.assert_envelope(result, success=True)
        payload = result["result"]
        assert payload["downloaded"] is True
        # Real usage: the receive trigger always delivers media.file_name
        # (synthesised in _service._normalize_media via _SYNTHETIC_EXT), so
        # the Telegram-native extension survives the slugify.
        assert payload["filename"].startswith("voice-note-")
        assert payload["filename"].endswith(".ogg")

    async def test_fully_synthesised_name_falls_back_to_mime_extension(
        self, harness, tmp_path
    ):
        svc = self._connected_bot()
        ctx = harness.build_context(workspace_dir=str(tmp_path))

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramGetAttachment",
                {"file_id": "VOICE-9", "kind": "voice", "mime_type": "audio/ogg"},
                context=ctx,
            )

        harness.assert_envelope(result, success=True)
        payload = result["result"]
        assert payload["downloaded"] is True
        # Both the name and the extension are synthesised here. Python's
        # mime db maps audio/ogg -> .oga (not .ogg) — the shared helper in
        # telegram_receive uses mimetypes.guess_extension, so the OGG family
        # extension is what lands; the receive trigger's media.file_name
        # normally pre-empts this path with the canonical .ogg.
        assert payload["filename"].startswith("telegram-voice-")
        assert payload["filename"].endswith((".ogg", ".oga"))

    async def test_not_connected_short_circuits(self, harness):
        svc = _make_telegram_service(connected=False)

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramGetAttachment",
                {"file_id": "DOC-1"},
            )

        harness.assert_envelope(result, success=False)
        assert "not connected" in result["error"].lower()

    async def test_missing_file_id_gives_user_error(self, harness):
        svc = self._connected_bot()

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramGetAttachment",
                {"file_id": ""},
            )

        harness.assert_envelope(result, success=False)
        assert "file_id is required" in result["error"]

    async def test_bot_download_failure_surfaces_as_user_error(self, harness, tmp_path):
        svc = _make_telegram_service(connected=True)
        bot = MagicMock(name="Bot")
        bot.get_file = AsyncMock(side_effect=Exception("Bad Request: wrong file id specified"))
        svc._require_bot = MagicMock(return_value=bot)
        ctx = harness.build_context(workspace_dir=str(tmp_path))

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramGetAttachment",
                {"file_id": "BROKEN"},
                context=ctx,
            )

        harness.assert_envelope(result, success=False)
        assert "wrong file id" in result["error"].lower()

    async def test_empty_telegram_payload_surfaces_as_user_error(self, harness, tmp_path):
        svc = self._connected_bot(payload=b"")
        ctx = harness.build_context(workspace_dir=str(tmp_path))

        with _patch_telegram_service(svc):
            result = await harness.execute(
                "telegramGetAttachment",
                {"file_id": "EMPTY-1"},
                context=ctx,
            )

        harness.assert_envelope(result, success=False)
        assert "empty file" in result["error"].lower()


# ============================================================================
# telegram namespace isolation (tenant-scoped bot + status + dispatch)
# ============================================================================


class TestTelegramNamespaceIsolation:
    async def test_message_handler_seals_pinned_namespace_and_dispatches_with_it(self):
        """PTB callbacks may run in tasks with NO sealed context — the
        handler must re-seal from the instance's pinned namespace and
        dispatch the event EXPLICITLY to it (never whoever connected
        last). The seal is asserted via a pass-through spy: the ambient
        ContextVar after the call is other tests' business."""
        from core.namespace_context import set_active_namespace as real_seal
        from nodes.telegram._service import TelegramService

        svc = TelegramService.instance(namespace="tenant-a")
        svc._namespace = "tenant-a"
        svc._connected = True

        # The service does `from . import dispatch_telegram_message_received`
        # — that resolves the PACKAGE-level re-export, so patch there.
        with patch(
            "nodes.telegram._service.set_active_namespace", side_effect=real_seal
        ) as seal_spy, patch(
            "nodes.telegram.dispatch_telegram_message_received", new=AsyncMock()
        ) as dispatch:
            await svc._on_message_received(update=MagicMock(), context=MagicMock())

        dispatch.assert_awaited_once()
        assert dispatch.await_args.kwargs.get("namespace") == "tenant-a"
        # The handler re-sealed the ContextVar to the bot's pinned tenant.
        seal_spy.assert_called_once_with("tenant-a")

    async def test_broadcast_telegram_status_is_tenant_scoped(self):
        """The status frame goes ONLY to the bot's namespace and lands in
        the per-namespace cache slot — never in the global slot."""
        from types import SimpleNamespace

        from nodes.telegram._events import broadcast_telegram_status

        fake = SimpleNamespace(_status={}, broadcast=AsyncMock())
        with patch("services.status_broadcaster.get_status_broadcaster", return_value=fake):
            await broadcast_telegram_status(
                connected=True,
                bot_id=1,
                bot_username="test_bot",
                bot_name="Veronica",
                owner_chat_id=42,
                namespace="tenant-a",
            )

        assert fake._status["telegram_by_ns"]["tenant-a"]["bot_username"] == "test_bot"
        assert "telegram" not in fake._status, "global slot must not receive a tenant's bot state"
        assert fake.broadcast.await_args.kwargs.get("tenant_id") == "tenant-a"

    async def test_broadcast_default_namespace_mirrors_legacy_slot(self):
        from types import SimpleNamespace

        from nodes.telegram._events import broadcast_telegram_status

        fake = SimpleNamespace(_status={}, broadcast=AsyncMock())
        with patch("services.status_broadcaster.get_status_broadcaster", return_value=fake):
            await broadcast_telegram_status(connected=True, namespace="default")

        assert fake._status["telegram"]["connected"] is True
        assert fake._status["telegram_by_ns"]["default"]["connected"] is True

    async def test_get_status_swaps_telegram_slot_per_tenant(self):
        """full_status must describe the REQUESTING tenant's bot — the
        pre-fix global slot made every tenant display the last-connected
        bot."""
        from services.status_broadcaster import StatusBroadcaster

        b = StatusBroadcaster()
        b._status["telegram_by_ns"] = {
            "tenant-a": {"connected": True, "bot_username": "test_bot"},
        }
        b._status["telegram"] = {"connected": True, "bot_username": "someone_elses_bot"}

        view = b.get_status(tenant_id="tenant-a")
        assert view["telegram"]["bot_username"] == "test_bot"

        # A tenant with no bot gets a clean disconnected snapshot — not
        # another tenant's bot.
        other = b.get_status(tenant_id="bluedoc")
        assert other["telegram"]["connected"] is False
        assert other["telegram"]["bot_username"] is None

        # Legacy global view unchanged.
        assert b.get_status()["telegram"]["bot_username"] == "someone_elses_bot"


# ============================================================================
# socialSend
# ============================================================================


class TestSocialSend:
    async def test_whatsapp_text_happy_path(self, harness):
        whatsapp_send = AsyncMock(return_value={"success": True, "message_id": "wamid.xyz"})

        # The social node resolves the platform handler via the
        # social_provider_registry (Wave 11.I plugin self-registration).
        # Patching nodes.whatsapp._service.handle_whatsapp_send does NOT
        # affect the registered handler — the registry captured a strong
        # ref to the original function object at import time. Patch the
        # registry lookup instead.
        with patch(
            "services.plugin.social_provider_registry.get_social_send_handler",
            return_value=whatsapp_send,
        ):
            result = await harness.execute(
                "socialSend",
                {
                    "channel": "whatsapp",
                    "recipient_type": "phone",
                    "phone": "+15551234567",
                    "message_type": "text",
                    "message": "hi there",
                },
            )

        harness.assert_envelope(result, success=True)
        payload = result["result"]
        assert payload["channel"] == "whatsapp"
        assert payload["recipient"] == "+15551234567"
        assert payload["recipient_type"] == "phone"
        assert payload["message_type"] == "text"
        assert payload["message_id"] == "wamid.xyz"

        whatsapp_send.assert_awaited_once()
        sent_params = whatsapp_send.await_args.args[0]
        assert sent_params["phone"] == "+15551234567"
        assert sent_params["message"] == "hi there"
        assert sent_params["message_type"] == "text"

    async def test_missing_recipient_short_circuits(self, harness):
        # recipientType=phone but no phone param -> ValueError inside handler
        whatsapp_send = AsyncMock()

        with patch("nodes.whatsapp._service.handle_whatsapp_send", whatsapp_send):
            result = await harness.execute(
                "socialSend",
                {
                    "channel": "whatsapp",
                    "recipient_type": "phone",
                    "message_type": "text",
                    "message": "x",
                },
            )

        harness.assert_envelope(result, success=False)
        assert "recipient" in result["error"].lower()
        whatsapp_send.assert_not_awaited()

    async def test_unsupported_channel_returns_stub_error(self, harness):
        # Any non-whatsapp channel should surface as a failed envelope.
        whatsapp_send = AsyncMock()

        with patch("nodes.whatsapp._service.handle_whatsapp_send", whatsapp_send):
            result = await harness.execute(
                "socialSend",
                {
                    "channel": "discord",
                    "recipient_type": "phone",
                    "phone": "+15551234567",
                    "message_type": "text",
                    "message": "hi",
                },
            )

        harness.assert_envelope(result, success=False)
        assert (
            "discord" in result["error"].lower()
            or "not yet implemented" in result["error"].lower()
            or "not supported" in result["error"].lower()
        )
        whatsapp_send.assert_not_awaited()

    async def test_whatsapp_failure_becomes_error_envelope(self, harness):
        whatsapp_send = AsyncMock(return_value={"success": False, "error": "rpc boom"})

        # See test_whatsapp_text_happy_path: patch the registry lookup,
        # not the module attribute the registry already captured.
        with patch(
            "services.plugin.social_provider_registry.get_social_send_handler",
            return_value=whatsapp_send,
        ):
            result = await harness.execute(
                "socialSend",
                {
                    "channel": "whatsapp",
                    "recipient_type": "phone",
                    "phone": "+15551234567",
                    "message_type": "text",
                    "message": "x",
                },
            )

        harness.assert_envelope(result, success=False)
        assert "rpc boom" in result["error"]


# ============================================================================
# socialReceive
# ============================================================================


class TestSocialReceive:
    async def test_normalizes_whatsapp_upstream(self, harness):
        upstream = {
            "message_id": "wamid.abc",
            "sender": "15551234567@s.whatsapp.net",
            "sender_phone": "15551234567",
            "push_name": "Alice",
            "chat_id": "15551234567@s.whatsapp.net",
            "text": "hi from wa",
            "message_type": "text",
            "is_group": False,
            "is_from_me": False,
            "timestamp": "2026-04-15T00:00:00",
        }

        nodes = [
            {"id": "src_wa", "type": "whatsappReceive"},
            {"id": "tgt_social", "type": "socialReceive"},
        ]
        edges = [
            {
                "source": "src_wa",
                "target": "tgt_social",
                "sourceHandle": "output-main",
                "targetHandle": "input-main",
            }
        ]
        upstream_outputs = {"src_wa::output_main": upstream}

        result = await harness.execute(
            "socialReceive",
            {"channel_filter": "all", "sender_filter": "all"},
            node_id="tgt_social",
            nodes=nodes,
            edges=edges,
            upstream_outputs=upstream_outputs,
        )

        harness.assert_envelope(result, success=True)
        payload = result["result"]
        # Handler-built slices
        assert payload["message"] == "hi from wa"
        assert payload["contact"]["sender_phone"] == "15551234567"
        assert payload["contact"]["channel"] == "whatsapp"
        assert payload["metadata"]["message_id"] == "wamid.abc"
        # Top-level unified fields (from spread)
        assert payload["channel"] == "whatsapp"
        assert payload["chat_type"] == "dm"

    async def test_missing_upstream_returns_error(self, harness):
        nodes = [
            {"id": "src_wa", "type": "whatsappReceive"},
            {"id": "tgt_social", "type": "socialReceive"},
        ]
        # No edges / upstream outputs -> handler gets {} and errors out.
        result = await harness.execute(
            "socialReceive",
            {},
            node_id="tgt_social",
            nodes=nodes,
            edges=[],
            upstream_outputs={},
        )

        harness.assert_envelope(result, success=False)
        assert "no message data" in result["error"].lower()

    async def test_filter_rejects_message(self, harness):
        upstream = {
            "message_id": "m1",
            "sender": "15550000000@s.whatsapp.net",
            "sender_phone": "15550000000",
            "push_name": "Bob",
            "chat_id": "c1",
            "text": "spam spam",
            "message_type": "text",
            "is_group": False,
            "is_from_me": False,
        }
        nodes = [
            {"id": "src_wa", "type": "whatsappReceive"},
            {"id": "tgt_social", "type": "socialReceive"},
        ]
        edges = [
            {
                "source": "src_wa",
                "target": "tgt_social",
                "sourceHandle": "output-main",
                "targetHandle": "input-main",
            }
        ]
        upstream_outputs = {"src_wa::output_main": upstream}

        result = await harness.execute(
            "socialReceive",
            {
                "channel_filter": "all",
                "sender_filter": "keywords",
                "keywords": "hello,hi",
            },
            node_id="tgt_social",
            nodes=nodes,
            edges=edges,
            upstream_outputs=upstream_outputs,
        )

        # Filtered messages return success=true with result=null and filtered=true
        harness.assert_envelope(result, success=True)
        assert result["result"] is None
        assert result.get("filtered") is True

    async def test_ignore_own_messages_default(self, harness):
        upstream = {
            "message_id": "m1",
            "sender": "self@s.whatsapp.net",
            "sender_phone": "self",
            "chat_id": "c1",
            "text": "echo",
            "message_type": "text",
            "is_group": False,
            "is_from_me": True,
        }
        nodes = [
            {"id": "src_wa", "type": "whatsappReceive"},
            {"id": "tgt_social", "type": "socialReceive"},
        ]
        edges = [
            {
                "source": "src_wa",
                "target": "tgt_social",
                "sourceHandle": "output-main",
                "targetHandle": "input-main",
            }
        ]
        upstream_outputs = {"src_wa::output_main": upstream}

        result = await harness.execute(
            "socialReceive",
            {"sender_filter": "all"},  # ignoreOwnMessages default true
            node_id="tgt_social",
            nodes=nodes,
            edges=edges,
            upstream_outputs=upstream_outputs,
        )

        harness.assert_envelope(result, success=True)
        assert result["result"] is None
        assert result.get("filtered") is True
