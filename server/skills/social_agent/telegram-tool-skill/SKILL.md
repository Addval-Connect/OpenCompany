---
name: telegram-tool-skill
description: Multi-operation Telegram bot toolkit for agents - download files to the workspace, show the typing indicator, send text messages, and inspect the bot or a chat.
allowed-tools: telegram_tool
metadata:
  author: opencompany
  version: "1.0"
  category: social

---

# Telegram Bot Tool

One tool exposing the useful slice of the Telegram Bot API to an agent.

## How It Works

This skill provides instructions for the **Telegram Bot Tool** node. Connect it to an AI Agent's `input-tools` handle — the agent picks an `operation` and fills the fields it needs.

## telegram_tool Tool

### Schema Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| operation | string | Yes | `download`, `send_typing`, `send_message`, `get_me` or `get_chat` |
| chat_id | string | No | Target chat id or @username — **optional: defaults to the bot owner's chat** |
| chat_action | string | No | `typing` (default), `upload_photo`, `record_video`, `upload_video`, `record_voice`, `upload_voice`, `upload_document`, `choose_sticker`, `find_location`, `record_video_note`, `upload_video_note` |
| text | string | If send_message | Message text (markdown is converted to Telegram HTML) |
| parse_mode | string | No | `Auto` (default), `HTML`, `Markdown`, `MarkdownV2` or empty (plain) |
| file_id | string | If download | Telegram `file_id` (from the Telegram Receive trigger's `media.file_id`) |
| file_name | string | If download | Original file name (synthesised when absent) |
| kind / mime_type | string | No | Used for fallback naming when the file has no name |

### Operations

| Operation | Required Fields | Description |
|-----------|-----------------|-------------|
| `download` | file_id | Persist the file into the workspace `attachments/` folder; returns `file_path` (absolute, feeds documentParser), `rel_path`, `size_bytes`, `sha256` |
| `send_typing` | — (chat_id optional) | Show the typing/indicator for ~5s in the target chat |
| `send_message` | text | Send text (auto-chunked at 4096 chars, chained replies) |
| `get_me` | — | The bot's id, username and display name |
| `get_chat` | — (chat_id optional) | A chat's type, title/username, name |

### Notes

- `chat_id` omitted → the bot owner's chat (the first person who messaged the bot).
- `get_updates` and message history are NOT available: the Bot API allows one getUpdates consumer per bot token (the receive trigger owns it) and bots cannot read history.

### Examples

**Show the typing indicator, then answer:**
```json
{"operation": "send_typing"}
```
followed by
```json
{"operation": "send_message", "text": "Ready — the report is in attachments/."}
```

**Download a document the user sent:**
```json
{"operation": "download", "file_id": "BQACAgIAAx0CAPIKAAH", "file_name": "invoice.pdf", "kind": "document"}
```
