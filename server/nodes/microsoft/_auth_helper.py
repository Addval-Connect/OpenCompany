"""Shared Microsoft Graph token helper.

Microsoft Graph access tokens expire in ~1 hour, and
``AuthService.get_oauth_tokens()`` returns the STORED (possibly expired)
access token without refreshing — the generic :class:`Connection` facade
only retries once on 401/403 with the *same* token, so a stale token
would fail twice. This helper proactively refreshes and persists the
access token before a node makes Graph calls (mirroring
``nodes.google._auth_helper.get_google_credentials``).

The AuthService storage layer does not plumb ``token_expiry``, so we
track expiry in-process (``_TOKEN_EXPIRY``). On an unknown / expired
entry (e.g. the first call after a server restart) we refresh once —
a cheap, safe over-refresh — then rely on the cached expiry to skip
refresh on subsequent calls within the token lifetime.
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from core.logging import get_logger

logger = get_logger(__name__)

# user_id -> epoch seconds at which the currently-stored access token expires.
_TOKEN_EXPIRY: Dict[str, float] = {}

# Refresh this many seconds before actual expiry to avoid edge-of-expiry races.
_EXPIRY_MARGIN_SECONDS = 120


def _needs_refresh(user_id: str) -> bool:
    expiry = _TOKEN_EXPIRY.get(user_id)
    if expiry is None:
        return True  # unknown (fresh process / never refreshed here)
    return time.time() >= (expiry - _EXPIRY_MARGIN_SECONDS)


# Last refresh failure/skip reason, for the actionable 401 error surface.
# Keyed like _TOKEN_EXPIRY; overwritten by every attempt.
_LAST_REFRESH_BLOCKER: Dict[str, str] = {}


def _note_blocker(user_id: str, reason: str) -> None:
    """Record why a refresh could not run/complete, and log it loudly.

    The refresh path previously logged failures at DEBUG — invisible in
    production — so a dead refresh token surfaced only as a downstream
    Graph 401 with no explanation ("no pudo conectarse con Microsoft").
    WARNING is the level that makes the root cause diagnosable from the
    deploy log alone.
    """
    _LAST_REFRESH_BLOCKER[user_id] = reason
    logger.warning("[microsoft] token refresh unavailable: %s", reason)


def _last_blocker(user_id: str) -> str:
    return _LAST_REFRESH_BLOCKER.get(user_id, "the stored refresh token was rejected")


async def force_refresh_microsoft_token(user_id: str = "owner") -> str:
    """Refresh now, ignoring the in-process expiry cache; return the new token.

    Used as the 401-recovery path: Graph just rejected the stored token, so
    falling back to it is pointless — either the refresh produces a fresh
    token (the caller retries the request) or we raise an actionable error
    that names the reason instead of a bare "no pudo conectarse".
    """
    from services.plugin import NodeUserError

    refreshed = await _refresh_and_persist(user_id, None)
    if refreshed:
        return refreshed
    raise NodeUserError(
        "Microsoft Graph rejected the stored token and it cannot be "
        f"refreshed ({_last_blocker(user_id)}). Reconnect Microsoft in the "
        "Credentials modal (Sign in) and re-run."
    )


async def ensure_fresh_microsoft_token(user_id: str = "owner") -> str:
    """Guarantee the stored Microsoft access token is fresh; return it.

    Raises:
        PermissionError: if Microsoft Graph is not connected (no tokens),
            annotated so ``BaseNode.execute`` surfaces the provider and
            emits a ``credential.oauth.runtime_failed`` event.
    """
    from services.plugin.deps import get_auth_service

    auth_service = get_auth_service()
    tokens = await auth_service.get_oauth_tokens("microsoft", customer_id=user_id)
    if not tokens or not tokens.get("access_token"):
        err = PermissionError("Microsoft Graph not connected. Connect via the Credentials modal.")
        err.provider = "microsoft"
        err.reason = "missing"
        err.auth = "oauth2"
        raise err

    if not _needs_refresh(user_id):
        return tokens["access_token"]

    refreshed = await _refresh_and_persist(user_id, tokens)
    return refreshed or tokens["access_token"]


async def _refresh_and_persist(user_id: str, current_tokens: Optional[Dict]) -> Optional[str]:
    """Attempt a token refresh; persist the new access + rotated refresh.

    Returns the new access token, or ``None`` if refresh was not possible
    (no refresh token / no client credentials / upstream failure) — the
    caller decides whether falling back to the stored token is safe
    (``ensure_fresh``) or must surface the reason (``force_refresh``).
    Every skip/failure is logged at WARNING with its real cause.
    """
    from services.plugin.deps import get_auth_service

    from ._oauth import MicrosoftOAuth

    auth_service = get_auth_service()

    refresh_token = await auth_service.get_oauth_refresh_token("microsoft", customer_id=user_id)
    if not refresh_token:
        _note_blocker(
            user_id,
            "no refresh token stored for the active namespace (the consent "
            "may not have granted offline_access) — sign in again",
        )
        return None

    client_id = await auth_service.get_api_key("microsoft_client_id") or ""
    client_secret = await auth_service.get_api_key("microsoft_client_secret") or ""
    if not client_id:
        _note_blocker(
            user_id,
            "microsoft_client_id is not stored in this namespace's "
            "credentials — save it in the Credentials modal",
        )
        return None

    oauth = MicrosoftOAuth(client_id=client_id, redirect_uri="", client_secret=client_secret or None)
    result = await oauth.refresh_access_token(refresh_token)
    if not result.get("success") or not result.get("access_token"):
        _note_blocker(
            user_id,
            f"Entra ID rejected the refresh ({result.get('error') or 'unknown error'})",
        )
        return None

    new_access = result["access_token"]
    new_refresh = result.get("refresh_token") or refresh_token
    email = (current_tokens or {}).get("email")
    name = (current_tokens or {}).get("name")
    scopes = (current_tokens or {}).get("scopes")
    if current_tokens is None:
        stored = await auth_service.get_oauth_tokens("microsoft", customer_id=user_id) or {}
        email, name, scopes = stored.get("email"), stored.get("name"), stored.get("scopes")
    await auth_service.store_oauth_tokens(
        provider="microsoft",
        access_token=new_access,
        refresh_token=new_refresh,
        email=email,
        name=name,
        scopes=scopes,
        customer_id=user_id,
    )

    expires_in = result.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        _TOKEN_EXPIRY[user_id] = time.time() + float(expires_in)
    else:
        # Microsoft access tokens default to ~3600s; assume that.
        _TOKEN_EXPIRY[user_id] = time.time() + 3600.0
    _LAST_REFRESH_BLOCKER.pop(user_id, None)

    logger.debug("[microsoft] refreshed and persisted access token")
    return new_access
