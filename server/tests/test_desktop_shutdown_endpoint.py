"""``POST /api/desktop/shutdown`` — token-gated, then funnels into
``core.desktop.request_shutdown`` after the 202 is on the wire.

Mounted on a bare FastAPI app (same pattern as ``tests/routers``); the
router is the unit under test, not ``main``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

SERVER_DIR = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.unit


def _file_load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, SERVER_DIR / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def modules(monkeypatch):
    desktop = _file_load("core.desktop", "core/desktop.py")
    router_mod = _file_load("routers.desktop", "routers/desktop.py")
    calls: list[str] = []
    monkeypatch.setattr(router_mod, "request_shutdown", lambda reason: calls.append(reason))
    monkeypatch.delenv(desktop.ENV_TOKEN, raising=False)
    return desktop, router_mod, calls


@pytest.fixture
def client(modules):
    _, router_mod, _ = modules
    app = FastAPI()
    app.include_router(router_mod.router)
    return TestClient(app)


def test_refuses_without_a_configured_token(client, modules):
    _, router_mod, calls = modules
    r = client.post("/api/desktop/shutdown", headers={router_mod.TOKEN_HEADER: "anything"})
    assert r.status_code == 401
    assert calls == []


def test_refuses_a_wrong_token(client, modules, monkeypatch):
    desktop, router_mod, calls = modules
    monkeypatch.setenv(desktop.ENV_TOKEN, "correct-token")
    r = client.post("/api/desktop/shutdown", headers={router_mod.TOKEN_HEADER: "wrong"})
    assert r.status_code == 401
    r = client.post("/api/desktop/shutdown")
    assert r.status_code == 401
    assert calls == []


def test_accepts_the_right_token_and_schedules_shutdown(client, modules, monkeypatch):
    desktop, router_mod, calls = modules
    monkeypatch.setenv(desktop.ENV_TOKEN, "correct-token")
    # Fire the scheduled call immediately instead of after the grace delay.
    monkeypatch.setattr(router_mod, "_SHUTDOWN_DELAY_SECONDS", 0)
    r = client.post("/api/desktop/shutdown", headers={router_mod.TOKEN_HEADER: "correct-token"})
    assert r.status_code == 202
    assert r.json() == {"accepted": True}
    # TestClient runs the app loop per request; the loop.call_later(0, ...)
    # callback fires before the loop is torn down.
    assert calls == ["desktop shell requested shutdown"]


def test_route_is_on_the_public_allowlist():
    """The shell holds no session cookie, so the middleware must let the
    request reach the token check."""
    src = (SERVER_DIR / "middleware" / "auth.py").read_text(encoding="utf-8")
    assert '"/api/desktop/shutdown"' in src
    assert '"/health/ready"' in src


def test_main_mounts_the_router_only_in_desktop_mode():
    src = (SERVER_DIR / "main.py").read_text(encoding="utf-8")
    assert "if _is_desktop_mode():" in src
    assert "from routers import desktop as _desktop_router" in src
