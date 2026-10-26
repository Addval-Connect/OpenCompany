"""Tests for the OAuth lifecycle namespace routing.

Locks the fix for the "credentials expired" incident (2026-10): the WS
login handler must stamp the namespace it was initiated from into the
OAuth state, and the HTTP callback must honor it — falling back to the
middleware-resolved namespace (session cookie) when the state carries
none, NEVER forcing "default". The pre-fix behaviour overwrote the
correct tenant with the "default" fallback, so every Microsoft/Google/
Twitter sign-in landed in ``namespaces/default/credentials.db`` while
the workflows ran in their own tenant namespaces — the per-tenant
refresh then found no row and the provider looked expired.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import fastapi
import httpx
import pytest

from services.events.oauth_lifecycle import (
    make_oauth_callback_router,
    make_oauth_lifecycle_handlers,
)

pytestmark = pytest.mark.credentials


class _FakeStateStore:
    """In-memory stand-in for OAuth2PKCEClient.state_store."""

    def __init__(self) -> None:
        self._records: Dict[str, Dict[str, Any]] = {}

    def put(self, state: str, record: Dict[str, Any]) -> None:
        self._records[state] = record

    def peek(self, state: str) -> Optional[Dict[str, Any]]:
        return self._records.get(state)

    def pop(self, state: str) -> Optional[Dict[str, Any]]:
        return self._records.pop(state, None)


class _FakeOAuth:
    """OAuthLike stub whose state_store is observable from tests."""

    def __init__(self, state_store: _FakeStateStore) -> None:
        self.state_store = state_store
        self.last_state_data: Optional[Dict[str, Any]] = None

    def generate_authorization_url(self, *, state_data: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        self.last_state_data = state_data
        state = "state-123"
        self.state_store.put(state, {"redirect_uri": "http://testserver/api/testprov/callback", "data": state_data or {}})
        return {"url": "https://provider.example/authorize", "state": state}

    async def exchange_code(self, code: str, state: str) -> Dict[str, Any]:
        # Stop the callback right after the namespace routing — the
        # assertions read the ContextVar, not the token store.
        return {"success": False, "error": "test-stop"}

    async def fetch_user_info(self, access_token: str) -> Dict[str, Any]:
        return {"success": False}

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        return {"success": False}

    async def revoke_token(self, token: str, token_type: str = "access_token") -> Dict[str, Any]:
        return {"success": True}


def _make_app(state_store: _FakeStateStore):
    """FastAPI app carrying only the callback router; returns (app, None).

    The WS lifecycle handlers are exercised directly (they take
    ``(data, websocket)`` and don't need ASGI); only the HTTP callback
    runs through the transport.
    """
    app = fastapi.FastAPI()

    async def fake_factory(**kwargs):
        return _FakeOAuth(state_store)

    router = make_oauth_callback_router(
        provider="testprov",
        oauth_factory=fake_factory,
        user_info_to_email=lambda info: "u@x.com",
    )
    app.include_router(router)
    return app, None


@pytest.mark.asyncio
async def test_login_stamps_active_namespace_into_state(monkeypatch):
    """The WS login handler must carry the initiating namespace in the
    OAuth state — the callback is a separate HTTP request and cannot
    otherwise know which tenant's credentials DB to store into."""
    from core.namespace_context import set_active_namespace

    set_active_namespace("addval-connect")
    try:
        state_store = _FakeStateStore()
        oauth_holder: list[_FakeOAuth] = []

        async def fake_oauth_factory(redirect_uri: str = "", **kwargs):
            o = _FakeOAuth(state_store)
            oauth_holder.append(o)
            return o

        class _FakeAuth:
            async def get_api_key(self, provider: str, session_id: str = "default"):
                return "client-id-123"

        from core.container import container

        monkeypatch.setattr(container, "auth_service", lambda: _FakeAuth())

        import services.oauth_utils as oauth_utils

        monkeypatch.setattr(
            oauth_utils, "get_redirect_uri", lambda ws, provider: "http://testserver/api/testprov/callback"
        )

        handlers = make_oauth_lifecycle_handlers(
            provider="testprov",
            oauth_factory=fake_oauth_factory,
            user_info_to_subject=lambda info: "x",
        )
        result = await handlers["testprov_oauth_login"]({}, websocket=None)  # type: ignore[arg-type]

        assert result["success"] is True
        assert oauth_holder, "oauth factory must have been called"
        assert oauth_holder[0].last_state_data == {"namespace": "addval-connect"}
    finally:
        set_active_namespace("default")


@pytest.mark.asyncio
async def test_callback_honors_state_namespace():
    """state_data["namespace"] must win — the store lands in the namespace
    the sign-in was initiated from."""
    from core.namespace_context import get_active_namespace, set_active_namespace

    state_store = _FakeStateStore()
    state_store.put("state-123", {"redirect_uri": "http://x/cb", "data": {"namespace": "addval-connect"}})

    app, _ = _make_app(state_store)
    set_active_namespace("middleware-tenant")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/testprov/callback", params={"code": "c", "state": "state-123"})

    assert resp.status_code == 400  # exchange_code returns failure — stopped after routing
    assert get_active_namespace() == "addval-connect"
    set_active_namespace("default")


@pytest.mark.asyncio
async def test_callback_without_state_namespace_keeps_middleware_namespace():
    """No namespace in the state (pre-fix popup) → the middleware-resolved
    namespace must SURVIVE. The pre-fix behaviour forced "default" here,
    which is what routed every sign-in into the default namespace's DB."""
    from core.namespace_context import get_active_namespace, set_active_namespace

    state_store = _FakeStateStore()
    state_store.put("state-123", {"redirect_uri": "http://x/cb", "data": {}})

    app, _ = _make_app(state_store)
    set_active_namespace("middleware-tenant")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/testprov/callback", params={"code": "c", "state": "state-123"})

    assert resp.status_code == 400
    assert get_active_namespace() == "middleware-tenant"
    set_active_namespace("default")
