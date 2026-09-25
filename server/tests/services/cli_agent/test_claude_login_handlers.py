"""``claude_code_login`` is single-flight: one ``claude auth login`` at a
time, and the in-flight task is held by a strong reference (GitHub #129)."""

from __future__ import annotations

import asyncio

from unittest.mock import AsyncMock

import pytest

from nodes.agent.claude_code_agent import _handlers as handlers


@pytest.fixture(autouse=True)
def _logged_out(monkeypatch):
    monkeypatch.setattr(handlers, "claude_auth_status_info", AsyncMock(return_value={"loggedIn": False}))
    monkeypatch.setattr(handlers, "_login_task", None)


async def test_second_click_does_not_spawn_second_login(monkeypatch):
    started = 0
    release = asyncio.Event()

    async def fake_finalize():
        nonlocal started
        started += 1
        await release.wait()

    monkeypatch.setattr(handlers, "_finalize_claude_login", fake_finalize)

    first = await handlers.handle_claude_code_login({}, None)
    await asyncio.sleep(0)
    second = await handlers.handle_claude_code_login({}, None)

    assert first["success"] is True and first["pending"] is True
    assert second["pending"] is True
    assert started == 1
    assert handlers._login_in_progress() is True

    release.set()
    await handlers._login_task
    assert handlers._login_in_progress() is False


async def test_new_login_allowed_after_previous_finishes(monkeypatch):
    calls = 0

    async def fake_finalize():
        nonlocal calls
        calls += 1

    monkeypatch.setattr(handlers, "_finalize_claude_login", fake_finalize)

    await handlers.handle_claude_code_login({}, None)
    await handlers._login_task
    await handlers.handle_claude_code_login({}, None)
    await handlers._login_task
    assert calls == 2
