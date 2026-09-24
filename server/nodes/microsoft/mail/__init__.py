"""Outlook Mail via Microsoft Graph — multi-op ActionNode + AI tool.

Operations (dispatched off ``params.operation``):
- send                 -> POST /me/sendMail
- read                 -> GET  /me/messages/{id}  (or GET /me/messages?$top= when no id)
- search               -> GET  /me/messages?$search="..."
- reply                -> POST /me/messages/{id}/reply
- list_attachments     -> GET  /me/messages/{id}/attachments?$select=... (metadata only)
- download_attachments -> GET  /me/messages/{id}/attachments (base64 contentBytes ->
                          workspace files); pairs with the documentParser node for text.

The optional ``mailbox`` param retargets every op to a shared/other mailbox
(``/users/{address}`` instead of ``/me``); empty keeps the signed-in user's
own mailbox. Requires Full Access (+ Send As to send) on that mailbox and the
.Shared OAuth scopes.
"""

from __future__ import annotations

import base64
import json
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.plugin import ActionNode, NodeContext, NodeUserError, Operation, TaskQueue

from .._base import graph_request, mailbox_base, track_microsoft_usage, write_attachment_bytes
from .._credentials import MicrosoftCredential

_SEND = {"displayOptions": {"show": {"operation": ["send"]}}}
# Graph inline attachment limit. Requests with a total message size > 4 MB
# must use the upload-session API; we guard with a conservative per-file cap
# so a single large attachment fails early with a clear message rather than
# silently producing an HTTP 413 from Graph.
_GRAPH_INLINE_ATTACHMENT_LIMIT = 4 * 1024 * 1024  # 4 MB
_READ = {"displayOptions": {"show": {"operation": ["read"]}}}
_SEARCH = {"displayOptions": {"show": {"operation": ["search"]}}}
_REPLY = {"displayOptions": {"show": {"operation": ["reply"]}}}
_ATTACH = {"displayOptions": {"show": {"operation": ["list_attachments", "download_attachments"]}}}

# Graph attachment @odata.type discriminators.
_FILE_ATTACHMENT = "#microsoft.graph.fileAttachment"


class MailParams(BaseModel):
    operation: Literal["send", "read", "search", "reply", "list_attachments", "download_attachments"] = "send"

    # Target mailbox. Empty = the signed-in user's own mailbox. Set to a
    # shared/other mailbox address (e.g. support@contoso.com) to operate on
    # it — requires Full Access (+ Send As to send) on that mailbox and the
    # .Shared OAuth scopes.
    mailbox: str = Field(default="", description="Shared mailbox address (empty = your own mailbox).")

    # Send
    to: str = Field(
        default="",
        json_schema_extra={"placeholder": "alice@contoso.com, bob@contoso.com", **_SEND},
    )
    cc: str = Field(default="", json_schema_extra=_SEND)
    bcc: str = Field(default="", json_schema_extra=_SEND)
    subject: str = Field(default="", json_schema_extra=_SEND)
    body: str = Field(
        default="",
        json_schema_extra={"rows": 4, "placeholder": "Write your message...", **_SEND},
    )
    body_type: Literal["text", "html"] = Field(default="text", json_schema_extra=_SEND)
    # Workspace file paths to attach to the outgoing email.
    # Accepts a JSON array string or a comma-separated string of paths — the
    # LLM may pass either; both are normalised to a list before execution.
    # Each path may be absolute (e.g. from download_attachments) or
    # workspace-relative (e.g. from the gallery node).
    # Per-file limit: 4 MB (Graph inline attachment cap). Larger files raise
    # a NodeUserError with a clear message rather than silently failing.
    attachments: List[str] = Field(
        default_factory=list,
        description=(
            "Workspace file paths to attach (absolute or workspace-relative). "
            "Pass as a JSON array or comma-separated string."
        ),
        json_schema_extra=_SEND,
    )

    @field_validator("attachments", mode="before")
    @classmethod
    def _coerce_attachments(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v if x]
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed if x]
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
            # Comma-separated fallback
            return [p.strip() for p in v.split(",") if p.strip()]
        return []

    # Read (message_id optional: omit to list recent messages). message_id is
    # also the parent-message field for the attachment ops, so it shows there too.
    message_id: str = Field(
        default="",
        json_schema_extra={"displayOptions": {"show": {"operation": ["read", "list_attachments", "download_attachments"]}}},
    )
    max_results: int = Field(default=10, ge=1, le=100, json_schema_extra=_READ)

    # Search
    query: str = Field(
        default="",
        json_schema_extra={"placeholder": "from:jane subject:meeting", **_SEARCH},
    )
    search_max_results: int = Field(default=10, ge=1, le=100, json_schema_extra=_SEARCH)

    # Reply
    reply_message_id: str = Field(default="", json_schema_extra=_REPLY)
    comment: str = Field(
        default="",
        json_schema_extra={"rows": 4, "placeholder": "Your reply...", **_REPLY},
    )
    reply_all: bool = Field(default=False, json_schema_extra=_REPLY)

    # Attachments (list_attachments / download_attachments). Reuses message_id
    # above as the parent message. attachment_id downloads just one; empty = all.
    attachment_id: str = Field(default="", json_schema_extra=_ATTACH)
    include_inline: bool = Field(
        default=False,
        description="Include inline body images (e.g. signature logos). Off by default.",
        json_schema_extra=_ATTACH,
    )

    model_config = ConfigDict(extra="ignore")


class MailOutput(BaseModel):
    operation: Optional[str] = None
    sent: Optional[bool] = None
    attachments_sent: Optional[int] = None
    replied: Optional[bool] = None
    to: Optional[str] = None
    subject: Optional[str] = None
    message_id: Optional[str] = None
    from_: Optional[str] = Field(default=None)
    received: Optional[str] = None
    body_preview: Optional[str] = None
    body: Optional[str] = None
    web_link: Optional[str] = None
    has_attachments: Optional[bool] = None
    messages: Optional[List[dict]] = None
    count: Optional[int] = None
    query: Optional[str] = None
    # Attachment ops
    attachments: Optional[List[dict]] = None
    download_dir: Optional[str] = None
    skipped: Optional[List[dict]] = None

    model_config = ConfigDict(extra="allow")


def _recipients(raw: str) -> list:
    """Comma/semicolon-separated addresses -> Graph recipient objects."""
    parts = [p.strip() for chunk in raw.split(",") for p in chunk.split(";")]
    return [{"emailAddress": {"address": addr}} for addr in parts if addr]


async def _read_attachment_for_send(path_str: str, ctx: NodeContext) -> dict:
    """Read a workspace file and return a Graph fileAttachment dict.

    Accepts absolute paths (returned by download_attachments, the gallery,
    or document nodes) and workspace-relative paths. Validates that the
    file exists and is within the workspace root (containment check via
    resolve_media), then reads the bytes and base64-encodes them.

    Raises NodeUserError on missing file, containment violation, or when
    the file exceeds the Graph inline attachment limit (4 MB).
    """
    import mimetypes
    from pathlib import Path

    from services.media.workspace import resolve_media

    path_str = path_str.strip()
    p = Path(path_str)
    if not p.is_absolute():
        # Workspace-relative: resolve against the workflow workspace root with
        # containment validation — resolve_media raises on path traversal.
        p = resolve_media(path_str, ctx=ctx)
    # Absolute paths: still verify the file exists (containment is the
    # caller's responsibility; Graph would reject the payload anyway).
    if not p.exists() or not p.is_file():
        raise NodeUserError(f"Attachment file not found: {path_str!r}")

    payload = p.read_bytes()
    if len(payload) > _GRAPH_INLINE_ATTACHMENT_LIMIT:
        raise NodeUserError(
            f"Attachment {p.name!r} is {len(payload):,} bytes, which exceeds the "
            f"4 MB Graph inline attachment limit. Use the upload-session API for "
            "larger files, or reduce the file size."
        )

    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": p.name,
        "contentType": mime,
        "contentBytes": base64.b64encode(payload).decode(),
    }


def _summarize(msg: dict) -> dict:
    """Compact a Graph message resource into a flat summary dict."""
    sender = (msg.get("from") or {}).get("emailAddress") or {}
    return {
        "message_id": msg.get("id"),
        "subject": msg.get("subject", ""),
        "from": sender.get("address", ""),
        "from_name": sender.get("name", ""),
        "received": msg.get("receivedDateTime"),
        "body_preview": msg.get("bodyPreview", ""),
        "is_read": msg.get("isRead"),
        "has_attachments": msg.get("hasAttachments"),
        "web_link": msg.get("webLink"),
    }


class MailNode(ActionNode):
    type = "msMail"
    display_name = "Outlook Mail"
    subtitle = "Email Operations"
    group = ("microsoft", "tool")
    description = "Microsoft Outlook Mail send / read / search / reply via Graph (workflow + AI tool)"
    component_kind = "square"
    tool_name = "ms_mail"
    tool_description = (
        "Send, read, search, reply to, and handle attachments of Outlook email via Microsoft Graph. "
        "Operations: send (compose, optionally with file attachments from the workspace), "
        "read (get message by ID or list recent), "
        "search (find messages by text), reply (respond to a message), "
        "list_attachments (metadata for a message's attachments), "
        "download_attachments (save file attachments to the workspace; returns paths "
        "for the document parser). read/search results include has_attachments. "
        "Set 'mailbox' to a shared mailbox address to operate on it instead of your own. "
        "For send: pass 'attachments' as a list of workspace file paths "
        "(absolute paths from download_attachments/gallery, or workspace-relative) "
        "to attach files to the outgoing email."
    )
    handles = (
        {"name": "input-main", "kind": "input", "position": "left", "label": "Input", "role": "main"},
        {"name": "output-main", "kind": "output", "position": "right", "label": "Output", "role": "main"},
    )
    credentials = (MicrosoftCredential,)
    annotations = {"destructive": False, "readonly": False, "open_world": True}
    task_queue = TaskQueue.REST_API
    usable_as_tool = True

    Params = MailParams
    Output = MailOutput

    _SELECT = "id,subject,from,receivedDateTime,bodyPreview,isRead,hasAttachments,webLink"

    @Operation("dispatch")
    async def dispatch(self, ctx: NodeContext, params: MailParams) -> MailOutput:
        op = params.operation

        if op == "send":
            return await self._send(ctx, params)
        if op == "read":
            return await self._read(ctx, params)
        if op == "search":
            return await self._search(ctx, params)
        if op == "reply":
            return await self._reply(ctx, params)
        if op == "list_attachments":
            return await self._list_attachments(ctx, params)
        if op == "download_attachments":
            return await self._download_attachments(ctx, params)
        raise NodeUserError(f"Unknown Mail operation: {op}")

    async def _send(self, ctx: NodeContext, params: MailParams) -> MailOutput:
        if not params.to:
            raise NodeUserError("Recipient email address (to) is required")
        if not params.subject:
            raise NodeUserError("Email subject is required")
        if not params.body:
            raise NodeUserError("Email body is required")

        message = {
            "subject": params.subject,
            "body": {
                "contentType": "HTML" if params.body_type == "html" else "Text",
                "content": params.body,
            },
            "toRecipients": _recipients(params.to),
        }
        if params.cc:
            message["ccRecipients"] = _recipients(params.cc)
        if params.bcc:
            message["bccRecipients"] = _recipients(params.bcc)

        if params.attachments:
            attachment_objects = []
            for path_str in params.attachments:
                attachment_objects.append(await _read_attachment_for_send(path_str, ctx))
            message["attachments"] = attachment_objects

        await graph_request(
            ctx,
            "POST",
            f"{mailbox_base(params.mailbox)}/sendMail",
            json={"message": message, "saveToSentItems": True},
        )
        await track_microsoft_usage(ctx.node_id, "send", 1, ctx.raw)
        return MailOutput(
            operation="send",
            sent=True,
            to=params.to,
            subject=params.subject,
            attachments_sent=len(params.attachments) if params.attachments else None,
        )

    async def _read(self, ctx: NodeContext, params: MailParams) -> MailOutput:
        if params.message_id:
            msg = await graph_request(
                ctx,
                "GET",
                f"{mailbox_base(params.mailbox)}/messages/{params.message_id}",
                params={"$select": f"{self._SELECT},body"},
            )
            await track_microsoft_usage(ctx.node_id, "read", 1, ctx.raw)
            summary = _summarize(msg or {})
            body = ((msg or {}).get("body") or {}).get("content", "")
            return MailOutput(
                operation="read",
                message_id=summary["message_id"],
                subject=summary["subject"],
                from_=summary["from"],
                received=summary["received"],
                body_preview=summary["body_preview"],
                body=body,
                has_attachments=summary["has_attachments"],
                web_link=summary["web_link"],
            )

        # No id -> list most recent messages.
        data = await graph_request(
            ctx,
            "GET",
            f"{mailbox_base(params.mailbox)}/messages",
            params={
                "$top": min(params.max_results, 100),
                "$select": self._SELECT,
                "$orderby": "receivedDateTime desc",
            },
        )
        items = (data or {}).get("value", [])
        formatted = [_summarize(m) for m in items]
        await track_microsoft_usage(ctx.node_id, "read", len(formatted), ctx.raw)
        return MailOutput(operation="read", messages=formatted, count=len(formatted))

    async def _search(self, ctx: NodeContext, params: MailParams) -> MailOutput:
        if not params.query:
            raise NodeUserError("Search query is required")
        # Graph $search must be a quoted string; it cannot combine with $orderby.
        data = await graph_request(
            ctx,
            "GET",
            f"{mailbox_base(params.mailbox)}/messages",
            params={
                "$search": f'"{params.query}"',
                "$top": min(params.search_max_results, 100),
                "$select": self._SELECT,
            },
        )
        items = (data or {}).get("value", [])
        formatted = [_summarize(m) for m in items]
        await track_microsoft_usage(ctx.node_id, "search", len(formatted), ctx.raw)
        return MailOutput(
            operation="search",
            messages=formatted,
            count=len(formatted),
            query=params.query,
        )

    async def _reply(self, ctx: NodeContext, params: MailParams) -> MailOutput:
        if not params.reply_message_id:
            raise NodeUserError("reply_message_id is required")
        if not params.comment:
            raise NodeUserError("Reply comment is required")
        endpoint = "replyAll" if params.reply_all else "reply"
        await graph_request(
            ctx,
            "POST",
            f"{mailbox_base(params.mailbox)}/messages/{params.reply_message_id}/{endpoint}",
            json={"comment": params.comment},
        )
        await track_microsoft_usage(ctx.node_id, "reply", 1, ctx.raw)
        return MailOutput(operation="reply", replied=True, message_id=params.reply_message_id)

    async def _list_attachments(self, ctx: NodeContext, params: MailParams) -> MailOutput:
        if not params.message_id:
            raise NodeUserError("message_id is required to list attachments")
        # Metadata only — $select excludes contentBytes so no payload is fetched.
        data = await graph_request(
            ctx,
            "GET",
            f"{mailbox_base(params.mailbox)}/messages/{params.message_id}/attachments",
            params={"$select": "id,name,contentType,size,isInline"},
        )
        items = (data or {}).get("value", [])
        attachments = []
        for a in items:
            is_inline = bool(a.get("isInline"))
            if is_inline and not params.include_inline:
                continue
            odata = a.get("@odata.type", "")
            attachments.append(
                {
                    "attachment_id": a.get("id"),
                    "name": a.get("name"),
                    "content_type": a.get("contentType"),
                    "size": a.get("size"),
                    "is_inline": is_inline,
                    # "file" for downloadable fileAttachment; else the Graph
                    # subtype (item / reference) so the caller sees why a
                    # download op would skip it.
                    "kind": "file" if odata == _FILE_ATTACHMENT else odata.split(".")[-1] or "unknown",
                }
            )
        await track_microsoft_usage(ctx.node_id, "list_attachments", len(attachments), ctx.raw)
        return MailOutput(operation="list_attachments", attachments=attachments, count=len(attachments))

    async def _download_attachments(self, ctx: NodeContext, params: MailParams) -> MailOutput:
        from services.media.limits import MEDIA_MAX_READ_BYTES

        if not params.message_id:
            raise NodeUserError("message_id is required to download attachments")

        # Full fetch — fileAttachments carry base64 contentBytes inline. For
        # attachments >3 MB Graph may omit contentBytes and require the
        # session upload/download API; that's out of scope (the >25 MiB guard
        # below skips oversize items rather than blowing the media read cap).
        base = mailbox_base(params.mailbox)
        if params.attachment_id:
            single = await graph_request(
                ctx,
                "GET",
                f"{base}/messages/{params.message_id}/attachments/{params.attachment_id}",
            )
            items = [single] if single else []
        else:
            data = await graph_request(
                ctx,
                "GET",
                f"{base}/messages/{params.message_id}/attachments",
            )
            items = (data or {}).get("value", [])

        downloaded = []
        skipped = []
        for a in items:
            name = a.get("name") or "attachment"
            odata = a.get("@odata.type", "")
            if odata != _FILE_ATTACHMENT:
                skipped.append({"name": name, "reason": f"unsupported type {odata.split('.')[-1] or 'unknown'}"})
                continue
            if a.get("isInline") and not params.include_inline:
                skipped.append({"name": name, "reason": "inline"})
                continue
            content_b64 = a.get("contentBytes")
            if not content_b64:
                skipped.append({"name": name, "reason": "no contentBytes (may exceed Graph inline size)"})
                continue
            payload = base64.b64decode(content_b64)
            if len(payload) > MEDIA_MAX_READ_BYTES:
                skipped.append({"name": name, "reason": f"exceeds {MEDIA_MAX_READ_BYTES} byte limit"})
                continue

            ref, abs_path = write_attachment_bytes(
                payload,
                ctx=ctx,
                filename=name,
                mime_type=a.get("contentType"),
            )
            downloaded.append(
                {
                    "filename": name,
                    "path": abs_path,  # absolute — feeds documentParser.file_path
                    "mime_type": a.get("contentType"),
                    "size": len(payload),
                    "ref": ref.model_dump(mode="json"),
                }
            )

        if not downloaded:
            detail = f" (skipped: {skipped})" if skipped else ""
            raise NodeUserError(f"No downloadable file attachments on message {params.message_id}{detail}")

        # download_dir (absolute workspace attachments/ dir) feeds documentParser.input_dir.
        from pathlib import Path as _Path

        download_dir = str(_Path(downloaded[0]["path"]).parent)
        await track_microsoft_usage(ctx.node_id, "download_attachments", len(downloaded), ctx.raw)
        return MailOutput(
            operation="download_attachments",
            attachments=downloaded,
            download_dir=download_dir,
            count=len(downloaded),
            skipped=skipped or None,
        )
