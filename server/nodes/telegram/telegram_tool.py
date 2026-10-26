"""Telegram Bot Tool — multi-operation AI tool for agents (msCalendar shape).

One node exposing the useful slice of the Telegram Bot API to an AI
Agent: download a file into the workspace ``attachments/`` folder, show
the typing indicator, send a text message, and inspect the bot / a chat.
The agent picks an ``operation``; everything routes through one
``@Operation("dispatch")`` — the same matrix shape as the Microsoft
Graph tool (``msCalendar``).

Operations:
    download     — fetch a file by ``file_id`` and persist it into the
                   workspace ``attachments/`` folder (the Telegram-side
                   sibling of Outlook's ``download_attachments``)
    send_typing  — sendChatAction (the "typing…" indicator)
    send_message — send text (markdown→HTML auto-formatting + 4096
                   chunking + parse-fallback via the shared service path)
    get_me       — the connected bot's identity
    get_chat     — a chat's metadata

Not exposed on purpose: ``get_updates`` (fights the receive trigger's
own polling — Telegram allows one getUpdates consumer per token) and
history reads (the Bot API does not offer them to bots).
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.plugin import ActionNode, NodeContext, NodeUserError, Operation, TaskQueue

from ._credentials import TelegramCredential

_CHAT_ACTIONS = (
    "typing",
    "upload_photo",
    "record_video",
    "upload_video",
    "record_voice",
    "upload_voice",
    "upload_document",
    "choose_sticker",
    "find_location",
    "record_video_note",
    "upload_video_note",
)


class TelegramToolParams(BaseModel):
    """Flat (LLM-schema-safe) parameters — one matrix, one optional field
    per operation. Blank strings are tolerated at the dispatch body."""

    operation: Literal["download", "send_typing", "send_message", "get_me", "get_chat"] = Field(
        default="send_typing",
        description="Bot API operation to run",
    )
    chat_id: str = Field(
        default="",
        description=(
            "Target chat id or @username (send_typing / send_message / "
            "get_chat) — OPTIONAL: defaults to the bot owner's chat"
        ),
    )
    text: str = Field(
        default="",
        description="Message text (send_message)",
        json_schema_extra={"rows": 3},
    )
    chat_action: Literal[
        "typing",
        "upload_photo",
        "record_video",
        "upload_video",
        "record_voice",
        "upload_voice",
        "upload_document",
        "choose_sticker",
        "find_location",
        "record_video_note",
        "upload_video_note",
    ] = Field(
        default="typing",
        description="Chat action to show (send_typing)",
    )
    file_id: str = Field(
        default="",
        description="Telegram file_id to download (download)",
    )
    file_name: str = Field(
        default="",
        description="Original file name (download; synthesised when absent)",
    )
    kind: str = Field(
        default="",
        description="Media kind (download) — photo|video|audio|voice|animation|video_note|sticker|document",
    )
    mime_type: str = Field(
        default="",
        description="MIME type used to synthesise a missing extension (download)",
    )
    parse_mode: Literal["", "Auto", "HTML", "Markdown", "MarkdownV2"] = Field(
        default="Auto",
        description="Text formatting for send_message — Auto converts markdown to Telegram HTML",
    )

    model_config = ConfigDict(extra="ignore")


class TelegramToolOutput(BaseModel):
    """Operation result — one shape, the fields each operation fills.
    ``extra="allow"`` so context keys pass through."""

    operation: Optional[str] = None

    # download
    downloaded: Optional[bool] = None
    filename: Optional[str] = None
    file_path: Optional[str] = None  # absolute — feeds documentParser.file_path
    rel_path: Optional[str] = None  # workspace-relative attachments/<name>
    file_id: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None

    # send_typing / send_message
    chat_id: Optional[Any] = None
    chat_action: Optional[str] = None
    sent: Optional[bool] = None
    message_id: Optional[int] = None
    parts: Optional[int] = None
    message_ids: Optional[list] = None

    # get_me
    bot_id: Optional[int] = None
    bot_username: Optional[str] = None
    bot_name: Optional[str] = None

    # get_chat
    chat_info: Optional[dict] = None

    model_config = ConfigDict(extra="allow")


class TelegramToolNode(ActionNode):
    type = "telegramTool"
    display_name = "Telegram Bot Tool"
    subtitle = "Bot API Actions"
    group = ("social", "tool")
    description = "Telegram Bot API operations for AI agents: download attachment to workspace, send typing, send message, get bot/chat info"
    component_kind = "square"
    tool_name = "telegram_tool"
    tool_description = (
        "Interact with the connected Telegram bot. Operations: "
        "download (fetch a file by file_id into the workspace attachments/ "
        "folder and return its path — file_id comes from the Telegram "
        "Receive trigger's media.file_id), send_typing (show the typing… "
        "or another chat action indicator), send_message (send a text "
        "message), get_me (the bot's identity), get_chat (a chat's "
        "metadata). chat_id is OPTIONAL — when omitted the bot owner's "
        "chat is used."
    )
    handles = (
        {"name": "input-main", "kind": "input", "position": "left", "label": "Input", "role": "main"},
        {"name": "output-main", "kind": "output", "position": "right", "label": "Output", "role": "main"},
    )
    credentials = (TelegramCredential,)
    annotations = {"destructive": False, "readonly": False, "open_world": True}
    task_queue = TaskQueue.MESSAGING
    usable_as_tool = True

    Params = TelegramToolParams
    Output = TelegramToolOutput

    @Operation("dispatch")
    async def dispatch(self, ctx: NodeContext, params: TelegramToolParams) -> TelegramToolOutput:
        from ._service import get_telegram_service

        service = get_telegram_service()
        if not service.connected:
            raise NodeUserError("Telegram bot not connected. Add bot token in Credentials.")

        op = params.operation
        if op == "download":
            return await self._download(ctx, params)
        if op == "send_typing":
            return await self._send_typing(service, params)
        if op == "send_message":
            return await self._send_message(service, params)
        if op == "get_me":
            return await self._get_me(service)
        if op == "get_chat":
            return await self._get_chat(service, params)
        raise NodeUserError(f"Unknown Telegram Tool operation: {op}")

    async def _download(self, ctx: NodeContext, params: TelegramToolParams) -> TelegramToolOutput:
        if not params.file_id.strip():
            raise NodeUserError("file_id is required for the download operation")

        from .telegram_receive import _download_media_to_workspace

        media: Dict[str, Any] = {
            "file_id": params.file_id,
            "file_name": params.file_name or None,
            "kind": params.kind or None,
            "mime_type": params.mime_type or None,
            "downloaded": False,
        }
        try:
            await _download_media_to_workspace(ctx, media)
        except Exception as exc:  # noqa: BLE001 — user-correctable failure path
            raise NodeUserError(f"Telegram attachment download failed: {exc}") from exc

        if not media.get("downloaded"):
            raise NodeUserError(
                str(media.get("download_error") or "Telegram attachment could not be downloaded")
            )

        from pathlib import Path as _Path

        abs_path = str(media.get("file_path") or "")
        name = _Path(abs_path).name if abs_path else None
        return TelegramToolOutput(
            operation="download",
            downloaded=True,
            filename=name,
            file_path=abs_path or None,
            rel_path=f"attachments/{name}" if name else None,
            file_id=params.file_id,
            mime_type=media.get("mime_type") or params.mime_type or None,
            size_bytes=media.get("size_bytes"),
            sha256=media.get("sha256"),
        )

    def _resolve_chat(self, service, params: TelegramToolParams, op: str) -> str:
        """chat_id explícito, o el chat del dueño del bot.

        Los agentes rara vez conocen el chat_id (vive en el output del
        trigger) — y para un bot asistente el destino natural es el chat
        del dueño, que el sistema ya captura y persiste en la primera
        interacción. Sin explícito y sin dueño → error accionable.
        """
        chat = params.chat_id.strip()
        if chat:
            return chat
        owner = getattr(service, "owner_chat_id", None)
        if owner:
            return str(owner)
        raise NodeUserError(
            f"chat_id is required for the {op} operation — the bot has no "
            "detected owner chat yet (send the bot a message first, or "
            "pass chat_id explicitly)"
        )

    async def _send_typing(self, service, params: TelegramToolParams) -> TelegramToolOutput:
        chat = self._resolve_chat(service, params, "send_typing")
        result = await service.send_chat_action(chat, params.chat_action)
        return TelegramToolOutput(
            operation="send_typing",
            chat_id=result.get("chat_id"),
            chat_action=result.get("action"),
            sent=True,
        )

    async def _send_message(self, service, params: TelegramToolParams) -> TelegramToolOutput:
        chat = self._resolve_chat(service, params, "send_message")
        if not params.text.strip():
            raise NodeUserError("text is required for the send_message operation")
        result = await service.send_message(
            chat,
            params.text,
            parse_mode=params.parse_mode or None,
        )
        return TelegramToolOutput(
            operation="send_message",
            chat_id=result.get("chat_id"),
            message_id=result.get("message_id"),
            parts=result.get("parts"),
            message_ids=result.get("message_ids"),
        )

    async def _get_me(self, service) -> TelegramToolOutput:
        me = await service.get_me()
        return TelegramToolOutput(
            operation="get_me",
            bot_id=me.get("id"),
            bot_username=me.get("username"),
            bot_name=me.get("first_name"),
        )

    async def _get_chat(self, service, params: TelegramToolParams) -> TelegramToolOutput:
        chat = self._resolve_chat(service, params, "get_chat")
        info = await service.get_chat(chat)
        return TelegramToolOutput(operation="get_chat", chat_info=info)
