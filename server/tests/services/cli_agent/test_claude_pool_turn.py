"""``ClaudeSessionPool`` turn contracts against a fake subprocess.

Covers the stream-json runtime contract without spawning claude:
  - a cold spawn mints ``--session-id`` and knows the UUID before any
    event arrives;
  - a turn completes on the ``result`` stdout event;
  - stdout EOF (the child died) wakes ``send_turn`` immediately with the
    exit code instead of burning the full turn timeout (GitHub #133).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nodes.agent.claude_code_agent import _pool as pool_mod
from nodes.agent.claude_code_agent import _provider as provider_mod
from nodes.agent.claude_code_agent._pool import ClaudeSessionPool
from services.cli_agent.types import ClaudeTaskSpec


class _FakeStdin:
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self) -> None:
        self.pid = 4242
        self.returncode: int | None = None
        self.stdin = _FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self._exited = asyncio.Event()

    def exit(self, code: int) -> None:
        self.returncode = code
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self._exited.set()

    async def wait(self) -> int:
        await self._exited.wait()
        return self.returncode or 0

    def kill(self) -> None:
        if self.returncode is None:
            self.exit(-9)


def _feed(proc: _FakeProcess, event: dict) -> None:
    proc.stdout.feed_data((json.dumps(event) + "\n").encode("utf-8"))


@pytest.fixture
def spawned(monkeypatch):
    """A pool whose ``_spawn`` lands on a fake process; yields
    ``(pool, session, proc, argv)``."""
    captured: dict = {}

    async def fake_exec(*argv, **kwargs):
        captured["argv"] = list(argv)
        return captured["proc"]

    monkeypatch.setattr(pool_mod.asyncio, "create_subprocess_exec", fake_exec)
    # Never touch the shared npm tree from a unit test.
    monkeypatch.setattr(provider_mod, "claude_binary_path", lambda: "claude")
    monkeypatch.setattr(pool_mod.ClaudeSessionPool, "_emit_event", AsyncMock())

    pool = ClaudeSessionPool()

    async def _make():
        # StreamReader / Event need a running loop, so build inside the test.
        proc = captured["proc"] = _FakeProcess()
        session = await pool._spawn(
            memory_node_id="node:turn:0",
            spec=ClaudeTaskSpec(prompt="hi"),
            cwd=Path.cwd(),
            env={},
            defaults={},
            mcp_endpoint_url=None,
            mcp_bearer_token=None,
            connected_tool_names=None,
        )
        return pool, session, proc, captured["argv"]

    return _make


async def test_cold_spawn_mints_session_id(spawned):
    _pool, session, proc, argv = await spawned()
    idx = argv.index("--session-id")
    assert argv[idx + 1] == session.current_session_uuid
    assert session.current_session_uuid  # known before any event
    proc.exit(0)


async def test_turn_completes_on_result_event(spawned):
    pool, session, proc, _argv = await spawned()
    sid = session.current_session_uuid

    async def drive():
        await asyncio.sleep(0)
        _feed(proc, {"type": "system", "subtype": "init", "session_id": sid})
        _feed(proc, {"type": "assistant", "message": {"content": [{"type": "text", "text": "OK"}]}, "session_id": sid})
        _feed(
            proc,
            {"type": "result", "subtype": "success", "result": "OK", "session_id": sid, "num_turns": 1, "usage": {}},
        )

    asyncio.create_task(drive())
    result = await asyncio.wait_for(pool.send_turn(session, "hi", timeout_seconds=10), timeout=5)

    assert result.success is True
    assert result.response == "OK"
    assert result.session_id == sid
    sent = json.loads(proc.stdin.written[0].decode("utf-8"))
    assert sent == {"type": "user", "message": {"role": "user", "content": "hi"}}
    proc.exit(0)


async def test_child_exit_without_result_fails_fast(spawned):
    pool, session, proc, _argv = await spawned()

    async def die():
        await asyncio.sleep(0)
        _feed(proc, {"type": "assistant", "message": {"content": [{"type": "text", "text": "partial"}]}})
        proc.exit(1)

    asyncio.create_task(die())
    # The turn timeout is far longer than the test budget: a hang here
    # means EOF no longer wakes ``send_turn``.
    result = await asyncio.wait_for(pool.send_turn(session, "hi", timeout_seconds=600), timeout=5)

    assert result.success is False
    assert "code 1" in (result.error or "")
    assert "result" in (result.error or "")


async def test_exit_before_turn_reports_exit_code(spawned):
    pool, session, proc, _argv = await spawned()
    proc.exit(3)
    await asyncio.sleep(0)
    result = await pool.send_turn(session, "hi", timeout_seconds=1)
    assert result.success is False
    assert "code 3" in (result.error or "")


def test_project_key_matches_claude_encoding():
    """Claude replaces every char outside ``[a-zA-Z0-9-]`` with ``-``,
    dots included (GitHub #132). Runs are not collapsed."""
    from services.cli_agent.session import _PROJECT_KEY_RE

    assert _PROJECT_KEY_RE.sub("-", r"E:\Kae\.opencompany\workspaces\x") == "E--Kae--opencompany-workspaces-x"
    assert _PROJECT_KEY_RE.sub("-", "/home/u/.opencompany/ws") == "-home-u--opencompany-ws"
    assert _PROJECT_KEY_RE.sub("-", "D:\\startup\\projects\\opencompany") == "D--startup-projects-opencompany"
