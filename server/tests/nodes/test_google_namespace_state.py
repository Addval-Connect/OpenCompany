"""The Google customer-auth-url route must stamp the namespace into the
OAuth state — the callback is a separate HTTP request, and without the
stamp its fallback routed the token store to "default" (the same defect
the Microsoft sign-in had; see services/events/oauth_lifecycle.py).
"""

from __future__ import annotations

from typing import Any, Dict

import fastapi
import httpx
import pytest

from core.namespace_context import get_active_namespace, set_active_namespace
from nodes.google import _router as google_router


pytestmark = pytest.mark.node_contract


class _FakeGoogleOAuth:
    client_id = "cid"
    client_secret = "sec"
    last_state_data: Dict[str, Any] = {}

    def generate_authorization_url(self, *, state_data: Dict[str, Any] | None = None) -> Dict[str, str]:
        _FakeGoogleOAuth.last_state_data = state_data or {}
        return {"url": "https://accounts.google.com/o/oauth2/auth", "state": "st-1"}


@pytest.mark.asyncio
async def test_customer_auth_url_carries_namespace(monkeypatch):
    set_active_namespace("tenant-a")
    try:
        async def fake_factory(redirect_uri: str = "", **kwargs):
            return _FakeGoogleOAuth()

        monkeypatch.setattr(google_router, "_google_oauth_factory", fake_factory)
        import services.oauth_utils as oauth_utils

        monkeypatch.setattr(oauth_utils, "get_redirect_uri", lambda req, provider: "http://x/cb")

        app = fastapi.FastAPI()
        app.include_router(google_router.router)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post("/api/google/customer-auth-url", params={"customer_id": "cust-1"})

        assert resp.status_code == 200
        assert _FakeGoogleOAuth.last_state_data.get("namespace") == "tenant-a"
        assert get_active_namespace() == "tenant-a"
    finally:
        set_active_namespace("default")
