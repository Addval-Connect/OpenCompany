---
name: telegram-get-attachment-skill
description: Download a Telegram file (document, photo, video, audio or voice) by file_id into the workflow workspace attachments/ folder and return its path for downstream nodes.
allowed-tools: telegram_get_attachment
metadata:
  author: opencompany
  version: "1.0"
  category: social

---

# Telegram Get Attachment Tool

Download a file sent to the Telegram bot and persist it into the workflow workspace.

## How It Works

This skill provides instructions for the **Telegram Get Attachment** tool node. Connect it to an AI Agent's `input-tools` handle, or wire it directly after a **Telegram Receive** trigger.

## telegram_get_attachment Tool

### Schema Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| file_id | string | Yes | Telegram `file_id` — template it from the Telegram Receive trigger's `media.file_id` |
| file_name | string | No | Original file name; synthesised from kind + extension when absent |
| kind | string | No | `photo`, `video`, `audio`, `voice`, `animation`, `video_note`, `sticker` or `document` |
| mime_type | string | No | Used to synthesise a missing extension |

### Output

| Field | Description |
|-------|-------------|
| downloaded | `true` when the file landed in the workspace |
| file_path | Absolute path — feed it to `documentParser.file_path` / `input_dir` directly |
| rel_path | Workspace-relative `attachments/<name>` reference |
| size_bytes / sha256 | Integrity metadata |

### Notes

- The file never travels as bytes/base64 — it is written atomically to `<workspace>/attachments/` with a collision-safe name.
- If the download fails the error names the reason (wrong file_id, empty file, bot not connected).

### Examples

**Download the document from the incoming message** (agent has the trigger context):
```json
{
  "file_id": "BQACAgIAAx0CAPIKAAH",
  "file_name": "invoice_42.pdf",
  "kind": "document"
}
```
