"""Per-request namespace context via ContextVar.

Set once at request/WS entry (middleware or WS connect handler); read
by DatabasePool and CredentialsPool to route to the correct per-namespace
SQLite file.  Defaults to "owner" so pre-existing code that never sets
the context still works correctly.
"""

from contextvars import ContextVar

_active_ns: ContextVar[str] = ContextVar("active_ns", default="owner")


def set_active_namespace(ns: str) -> None:
    """Set the active namespace for the current async task."""
    _active_ns.set(ns or "owner")


def get_active_namespace() -> str:
    """Return the active namespace for the current async task."""
    return _active_ns.get()
