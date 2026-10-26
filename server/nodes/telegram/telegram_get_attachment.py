"""Telegram Get Attachment — ActionNode + AI tool.

Downloads one Telegram file (by ``file_id``) into the workflow's
workspace ``attachments/`` folder.

Why an explicit node: the receive trigger only carries the file's
metadata (``media.file_id``) — the bytes must be fetched from the Bot
API — and the deployed path (TriggerListenerWorkflow) pre-executes the
trigger with the raw event payload and never calls
``NodeExecutor.execute``, so any auto-download living inside the trigger
node is dead code there. A plain downstream node always runs with a full
``NodeContext`` (workspace resolved), which is exactly the Outlook
pattern: ``msMailReceive`` delivers message metadata and
``msMail.download_attachments`` fetches the bytes via
``write_attachment_bytes``.

Wiring: connect ``telegramReceive`` output-main into this node (or let
an AI Agent invoke it as a tool) and template ``file_id`` from
``{{Telegram Receive.media.file_id}}``.

Downstream: ``file_path`` (absolute) feeds ``documentParser.file_path`` /
``input_dir`` directly; ``rel_path`` is the workspace-relative
``attachments/<name>`` reference. The file never travels as bytes or
base64 — node outputs are persisted, broadcast, and serialized into LLM
conversations.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.plugin import (
    ActionNode,
    NodeContext,
    NodeUserError,
    Operation,
    TaskQueue,
)

from ._credentials import TelegramCredential


class TelegramGetAttachmentParams(BaseModel):
    """4-field schema. Flat (no nested models) so the LLM tool schema
    stays JSON-Schema-flat; blank strings are tolerated at the operation
    body (the parameter panel stores "" for cleared fields)."""

    file_id: str = Field(
        default="",
        description=(
            "Telegram file_id to download — template it from the receive "
            "trigger's media.file_id"
        ),
    )
    file_name: str = Field(
        default="",
        description="Original file name; synthesised from kind + extension when absent",
    )
    kind: str = Field(
        default="",
        description=(
            "Media kind (photo|video|audio|voice|animation|video_note|"
            "sticker|document) used for fallback naming"
        ),
    )
    mime_type: str = Field(
        default="",
        description="MIME type used to synthesise a missing extension",
    )

    model_config = ConfigDict(extra="ignore")


class TelegramGetAttachmentOutput(BaseModel):
    """Result of one attachment download. ``file_path`` (absolute) is the
    field downstream nodes consume (documentParser takes a plain path);
    ``rel_path`` is the workspace-relative reference."""

    downloaded: bool = False
    filename: Optional[str] = None
    file_path: Optional[str] = None  # absolute — feeds documentParser.file_path
    rel_path: Optional[str] = None  # workspace-relative attachments/<name>
    file_id: Optional[str] = None
    kind: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    download_error: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class TelegramGetAttachmentNode(ActionNode):
    type = "telegramGetAttachment"
    display_name = "Telegram Get Attachment"
    subtitle = "Download Bot File"
    group = ("social",)
    description = "Download a Telegram file (by file_id) into the workspace attachments/ folder"
    component_kind = "square"
    handles = (
        {"name": "input-main", "kind": "input", "position": "left", "label": "Input", "role": "main"},
        {"name": "output-main", "kind": "output", "position": "right", "label": "Output", "role": "main"},
    )
    annotations = {"destructive": False, "readonly": False, "open_world": True}
    credentials = (TelegramCredential,)
    task_queue = TaskQueue.MESSAGING
    usable_as_tool = True
    # Dual-purpose: keep both canvas handles visible — usable_as_tool
    # auto-hides them unless declared (see nodes/README.md pitfalls).
    hide_input_handle = False
    hide_output_handle = False

    Params = TelegramGetAttachmentParams
    Output = TelegramGetAttachmentOutput

    @Operation("get_attachment")
    async def get_attachment(self, ctx: NodeContext, params: TelegramGetAttachmentParams) -> Any:
        """Fetch the file via the connected bot and persist it into the
        workspace ``attachments/`` folder (shared helper with the receive
        trigger, so naming/atomicity stay byte-identical)."""
        if not params.file_id.strip():
            raise NodeUserError(
                "file_id is required — template it from the Telegram Receive "
                "trigger's media.file_id"
            )

        from ._service import get_telegram_service
        from .telegram_receive import _download_media_to_workspace

        service = get_telegram_service()
        if not service.connected:
            raise NodeUserError("Telegram bot not connected. Add bot token in Credentials.")

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
        return TelegramGetAttachmentOutput(
            downloaded=True,
            filename=name,
            file_path=abs_path or None,
            rel_path=f"attachments/{name}" if name else None,
            file_id=params.file_id,
            kind=params.kind or None,
            mime_type=media.get("mime_type") or params.mime_type or None,
            size_bytes=media.get("size_bytes"),
            sha256=media.get("sha256"),
            download_error=None,
        )