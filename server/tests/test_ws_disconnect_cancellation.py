"""A WebSocket disconnect must not interrupt database teardown.

Cancelling a handler task while a session is open used to deliver the
``CancelledError`` inside SQLAlchemy's reset-on-return rollback, which the
pool reports as "Exception during reset or similar" with a traceback.
Three guards fix it: session teardown is shielded, the endpoint drains
handlers briefly before cancelling them, and broadcasts skip sockets
that already saw a close frame.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketState

pytestmark = pytest.mark.unit

_SERVER = Path(__file__).resolve().parents[1]
_LOADED: dict = {}


def _load(rel: str):
    """Load a real ``core`` module privately; the root conftest stubs ``core.database``.

    Memoised per path: executing ``credentials_database.py`` twice would
    redefine its SQLModel tables on the shared metadata.
    """
    if rel in _LOADED:
        return _LOADED[rel]
    target = (_SERVER / rel).resolve()
    # tests/credentials/conftest.py replaces the stubbed ``core`` package with
    # the real modules at collection time; reuse that module rather than
    # executing the file a second time against the same SQLModel metadata.
    existing = sys.modules.get(f"core.{Path(rel).stem}")
    existing_file = getattr(existing, "__file__", None)
    if existing_file and Path(existing_file).resolve() == target:
        _LOADED[rel] = existing
        return existing
    name = f"tests._ws_cancel_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, target)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _LOADED[rel] = module
    return module


class _FakeSession:
    def __init__(self, *, close_gate: Optional[asyncio.Event] = None):
        self.calls: List[str] = []
        self.close_gate = close_gate
        self.closed = False

    async def rollback(self) -> None:
        self.calls.append("rollback")

    async def close(self) -> None:
        self.calls.append("close")
        if self.close_gate is not None:
            await self.close_gate.wait()
        self.closed = True


def _database(session: _FakeSession):
    module = _load("core/database.py")
    database = module.Database(
        SimpleNamespace(
            database_url="sqlite+aiosqlite:///:memory:",
            database_echo=False,
            database_pool_size=1,
            database_max_overflow=0,
        )
    )
    database.async_session = lambda: session
    return database


def _credentials_database(session: _FakeSession):
    module = _load("core/credentials_database.py")
    database = object.__new__(module.CredentialsDatabase)
    database._session_factory = lambda: session
    return database


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


class TestSessionTeardownIsShielded:
    @pytest.mark.parametrize("factory", [_database, _credentials_database], ids=["workflow-db", "credentials-db"])
    async def test_cancel_inside_the_body_still_rolls_back_and_closes(self, factory):
        session = _FakeSession()
        database = factory(session)
        entered = asyncio.Event()

        async def work():
            async with database.get_session():
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(work())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert session.calls == ["rollback", "close"]
        assert session.closed is True

    @pytest.mark.parametrize("factory", [_database, _credentials_database], ids=["workflow-db", "credentials-db"])
    async def test_cancel_during_close_lets_the_close_finish(self, factory):
        """The cancellation arrives while the pool reset is in progress; the
        reset must complete instead of being torn out from under SQLAlchemy."""
        gate = asyncio.Event()
        session = _FakeSession(close_gate=gate)
        database = factory(session)

        async def work():
            async with database.get_session():
                pass

        task = asyncio.create_task(work())
        while "close" not in session.calls:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert session.closed is False, "close is still running, shielded from the cancel"
        gate.set()
        await _settle()
        assert session.closed is True

    async def test_exception_in_body_rolls_back_and_closes(self):
        session = _FakeSession()
        database = _database(session)

        with pytest.raises(RuntimeError):
            async with database.get_session():
                raise RuntimeError("boom")

        assert session.calls == ["rollback", "close"]

    async def test_clean_exit_closes_without_rollback(self):
        session = _FakeSession()
        database = _database(session)

        async with database.get_session():
            pass

        assert session.calls == ["close"]


class TestHandlerDrain:
    async def test_short_handlers_finish_and_long_ones_are_cancelled(self):
        from routers.websocket import _drain_handler_tasks

        fast = asyncio.create_task(asyncio.sleep(0.01))
        slow = asyncio.create_task(asyncio.Event().wait())

        await _drain_handler_tasks({fast, slow}, grace=0.3)

        assert fast.done() and not fast.cancelled(), "a handler that finishes inside the grace is never cancelled"
        assert slow.cancelled()

    async def test_no_tasks_is_a_no_op(self):
        from routers.websocket import _drain_handler_tasks

        await _drain_handler_tasks(set(), grace=0.01)

    def test_endpoints_use_the_drain(self):
        import inspect

        import routers.websocket as ws

        source = inspect.getsource(ws)
        assert source.count("await _drain_handler_tasks(handler_tasks)") == 2, (
            "both /ws/status and /ws/internal must drain instead of cancelling immediately"
        )


class _Socket:
    """Hashable stand-in for a Starlette WebSocket (SimpleNamespace is not hashable)."""

    def __init__(self, *, client=WebSocketState.CONNECTED, application=WebSocketState.CONNECTED, send=None):
        self.client_state = client
        self.application_state = application
        self.send_text = send or AsyncMock()


def _socket(**kwargs) -> _Socket:
    return _Socket(**kwargs)


class TestBroadcastSkipsClosedSockets:
    async def test_closed_socket_is_pruned_without_a_send(self):
        from services.status_broadcaster import StatusBroadcaster

        broadcaster = StatusBroadcaster()
        closing = _socket(client=WebSocketState.DISCONNECTED)
        closed_by_server = _socket(application=WebSocketState.DISCONNECTED)
        live = _socket()
        broadcaster._connections = {closing, closed_by_server, live}

        await broadcaster.broadcast({"type": "node_status"})

        closing.send_text.assert_not_awaited()
        closed_by_server.send_text.assert_not_awaited()
        live.send_text.assert_awaited_once()
        assert broadcaster._connections == {live}

    async def test_send_failure_prunes_the_socket(self):
        from services.status_broadcaster import StatusBroadcaster

        broadcaster = StatusBroadcaster()
        failing = _socket(send=AsyncMock(side_effect=RuntimeError('Cannot call "send" once a close message has been sent.')))
        broadcaster._connections = {failing}

        await broadcaster.broadcast({"type": "node_status"})

        assert broadcaster._connections == set()
