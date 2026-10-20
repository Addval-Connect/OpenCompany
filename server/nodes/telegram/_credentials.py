"""Telegram bot-token credential (Wave 11.E.1 — per-domain).

Used by the two telegram plugins in this folder (telegram_send, telegram_receive).

Multi-bot support: credentials are stored as named rows — one per bot,
keyed ``telegram_{bot_username}`` (lowercased) — mirroring the
``openai_compatible`` endpoint pattern. The bare ``telegram`` id is
retained as the catalogue provider so the Credentials panel still
displays the Telegram entry; nodes select a specific bot via the
``telegram_bot_ref`` parameter.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from services.plugin.credential import ApiKeyCredential, ProbeResult


# Telegram embeds the bot token in the URL path (``/bot<token>/getMe``)
# rather than in a header / query / Authorization slot, so the
# declarative ``probe_url`` shape doesn't fit. We override ``_probe``
# directly but reuse :meth:`_handle_probe_response` from the base for
# the 200-with-failure-envelope case.
_TELEGRAM_API = "https://api.telegram.org"


def bot_ref(bot_username: str) -> str:
    """Unique storage key for a named bot row: ``telegram_{username}``."""
    return f"telegram_{(bot_username or '').strip().lower()}"


class TelegramCredential(ApiKeyCredential):
    id = "telegram"
    display_name = "Telegram Bot"
    category = "Social"
    key_name = ""  # not used — python-telegram-bot takes the token directly
    key_location = "header"
    extra_fields = ("telegram_owner_chat_id",)
    docs_url = "https://core.telegram.org/bots"

    @classmethod
    def sanitize_secrets(cls, secrets: Dict[str, Any]) -> Dict[str, Any]:
        """Drop empty optional fields so they never reach downstream int-casts."""
        if not secrets.get("telegram_owner_chat_id"):
            secrets.pop("telegram_owner_chat_id", None)
        return secrets

    @classmethod
    async def _probe(cls, api_key: str) -> ProbeResult:
        """Validate via ``GET /bot<token>/getMe``.

        Telegram returns 401 for revoked tokens and 404 for malformed
        tokens; both surface as :class:`httpx.HTTPStatusError` and the
        base :meth:`Credential.validate` translates them via
        :func:`classify_credential_error`. A 200 with ``{ok: false}`` is
        rare but possible (legacy token shapes) and is caught in
        :meth:`_handle_probe_response`.
        """
        url = f"{_TELEGRAM_API}/bot{api_key}/getMe"
        async with httpx.AsyncClient(timeout=cls.probe_timeout_seconds) as client:
            response = await client.get(url)
        response.raise_for_status()
        return cls._handle_probe_response(response)

    @classmethod
    def _handle_probe_response(cls, response: httpx.Response) -> ProbeResult:
        payload = response.json()
        if not payload.get("ok"):
            return ProbeResult(
                valid=False,
                message=payload.get("description", "Telegram rejected the bot token"),
            )
        bot = payload.get("result") or {}
        username = bot.get("username")
        return ProbeResult(
            valid=True,
            message=(f"Telegram bot token is valid (@{username})" if username else "Telegram bot token is valid"),
            extra={
                "bot_id": bot.get("id"),
                "bot_username": username,
                "bot_name": bot.get("first_name"),
            },
        )

    # ---- Multi-bot (named rows) ------------------------------------
    #
    # One bot per named row: ``telegram_{bot_username}`` stores the
    # token; ``{ref}_owner_chat_id`` stores that bot's owner chat.
    # The bare ``telegram`` id is never written — it's the catalogue key.

    @classmethod
    async def resolve(cls, *, user_id: str = "owner", ref: Optional[str] = None) -> Dict[str, Any]:
        """Resolve the named bot's token (+ owner chat if saved).

        Falls back to the legacy bare-``telegram`` row when ``ref`` is
        unset or missing, so pre-multi-bot workflows keep working.
        """
        from core.container import container

        auth_service = container.auth_service()
        token = await auth_service.get_api_key(ref) if ref else None
        if token:
            secrets: Dict[str, Any] = {"api_key": token}
            owner = await auth_service.get_api_key(f"{ref}_owner_chat_id")
            if owner:
                secrets["telegram_owner_chat_id"] = owner
            return secrets
        return await super().resolve(user_id=user_id)

    @classmethod
    async def validate(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Probe the token, then persist it under its named row.

        The username from ``getMe`` is the natural stable name; if the
        token somehow returns no username we refuse to auto-name and
        ask for one, keeping rows addressable.
        """
        from core.container import container
        from services.status_broadcaster import get_status_broadcaster

        result = await cls._probe(data.get("api_key") or "")
        if not result.valid:
            await get_status_broadcaster().update_api_key_status(
                provider=cls.id,
                valid=False,
                message=result.message,
                has_key=False,
                models=result.models,
            )
            return {
                "success": True,
                "provider": cls.id,
                "valid": False,
                "message": result.message,
                "models": result.models,
                "timestamp": 0,
            }

        auth = container.auth_service()
        username = (result.extra.get("bot_username") or "").strip()
        if not username:
            return {
                "success": True,
                "provider": cls.id,
                "valid": False,
                "message": "Telegram did not return a bot username; cannot name this bot row.",
                "models": result.models,
                "timestamp": 0,
            }

        ref = bot_ref(username)
        owner_chat_id = (data.get("telegram_owner_chat_id") or "").strip()
        await auth.store_api_key(provider=ref, api_key=data.get("api_key") or "", models=result.models)
        if owner_chat_id:
            await auth.store_api_key(provider=f"{ref}_owner_chat_id", api_key=owner_chat_id, models=[])
        else:
            await auth.remove_api_key(f"{ref}_owner_chat_id")

        await get_status_broadcaster().update_api_key_status(
            provider=cls.id,
            valid=True,
            message=result.message,
            has_key=True,
            models=result.models,
        )
        return {
            "success": True,
            "provider": cls.id,
            "ref": ref,
            "valid": True,
            "message": result.message,
            "models": result.models,
            "timestamp": 0,
            **result.extra,
        }

    @classmethod
    async def catalogue_extras(cls) -> Dict[str, Any]:
        """List the saved named bots for the Credentials panel."""
        from core.container import container

        auth = container.auth_service()
        prefix = "telegram_"
        bots = [
            {
                "ref": provider,
                "label": provider.removeprefix(prefix),
                "username": provider.removeprefix(prefix),
            }
            for provider in await auth.list_api_key_providers()
            if provider.startswith(prefix) and not provider.endswith("_owner_chat_id")
        ]
        return {"stored": bool(bots), "bots": bots}

    @classmethod
    async def is_configured(cls, auth_service: Any, parameters: Dict[str, Any]) -> bool:
        """The bot the node names is saved; bare ``telegram`` is legacy."""
        ref = str(parameters.get("telegram_bot_ref") or "")
        if not ref:
            return bool(await auth_service.has_valid_key(cls.id))
        return bool(await auth_service.has_valid_key(ref))
