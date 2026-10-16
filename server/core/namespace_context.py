"""Per-request namespace context via ContextVar.

Set once at request/WS entry (middleware or WS connect handler); read
by DatabasePool and CredentialsPool to route to the correct per-namespace
SQLite file.  Defaults to "default" — the canonical namespace name shared
by the JWT claim, the UI, Temporal and the on-disk layout. "owner" is a
PRINCIPAL (auth only), never a namespace: see
docs-internal/multitenant_routing_audit.md.
"""

from contextvars import ContextVar

_active_ns: ContextVar[str] = ContextVar("active_ns", default="default")


def set_active_namespace(ns: str) -> None:
    """Set the active namespace for the current async task."""
    _active_ns.set(ns or "default")


def get_active_namespace() -> str:
    """Return the active namespace for the current async task."""
    return _active_ns.get()
