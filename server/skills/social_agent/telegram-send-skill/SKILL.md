---
name: telegram-send-skill
description: Send messages via a Telegram bot - text (markdown to HTML), photos, documents, location and contacts. Supports replying, silent sends and message chunking.
allowed-tools: telegram_send
metadata:
  author: opencompany
  version: "1.0"
  category: social

---

# Telegram Send Tool

Send messages through the connected Telegram bot.

## How It Works

This skill provides instructions for the **Telegram Send** tool node. Connect the **Telegram Send** node to an AI Agent's `input-tools` handle to enable sending.

## telegram_send Tool

### Schema Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| recipient_type | string | Yes | `self` (bot owner), `user` (specific user) or `group` |
| chat_id | string | If user/group | Telegram chat ID (numeric) or @username |
| message_type | string | Yes | `text`, `photo`, `document`, `location` or `contact` |
| text | string | If text | Message content. Markdown is converted to Telegram HTML |
| media_url | string | If photo/document | URL of the media, or a `file_id` from a previous message |
| caption | string | No | Caption for photo/document (max 1024 chars; remainder is threaded as a follow-up) |
| parse_mode | string | No | `Auto` (default, markdown→HTML), `HTML`, `Markdown`, `MarkdownV2` or empty (plain) |
| silent | boolean | No | Send without notification sound |
| reply_to_message_id | integer | No | If > 0, sends as a reply to that message |

### Notes

- Text messages longer than 4096 chars are split into a chained thread automatically.
- Over-long captions are truncated at 1024 and the remainder is threaded underneath.
- `recipient_type: self` needs no chat_id — it targets the bot owner.

### Examples

**Send text to the bot owner:**
```json
{
  "recipient_type": "self",
  "message_type": "text",
  "text": "**Report ready** — see the attached summary."
}
```

**Send a document to a group:**
```json
{
  "recipient_type": "group",
  "chat_id": "-1001234567890",
  "message_type": "document",
  "media_url": "https://example.com/report.pdf",
  "caption": "Monthly report"
}
```
