"""Cancellation-safe teardown for async SQLAlchemy sessions.

Shared by ``core.database`` and ``core.credentials_database``. Both wrap
the call in ``asyncio.shield`` so a task cancelled while a session is
open (a WebSocket client disconnecting mid-request) cannot interrupt
the pool's reset-on-return rollback. Without the shield SQLAlchemy's
``_finalize_fairy`` logs "Exception during reset or similar" with a
traceback, invalidates the connection, and re-raises the
CancelledError; the connection is then rebuilt on the next checkout.
"""

from __future__ import annotations

from typing import Any


async def teardown_session(session: Any, *, rollback: bool) -> None:
    """Roll back (optionally) and close ``session``, always closing."""
    try:
        if rollback:
            await session.rollback()
    finally:
        await session.close()


__all__ = ["teardown_session"]
