"""Namespace routing for direct-session stores (Data mounts / Canvas / Memory).

The ``NamespacedDatabase`` proxy routes ``get_session`` to the owner DB by
design (auth tables are global) while the ``engine`` property resolves the
active namespace. Stores that open sessions DIRECTLY through the proxy
therefore mixed two databases in multi-tenant deployments:
``ensure_schema`` created ``data_mounts`` in the namespace DB while the
session read the owner DB — the "no such table: data_mounts" on the first
Data-panel open after every deploy. The stores now resolve the namespace
Database explicitly via ``proxy.active_db()``; this suite locks that
contract: a mount added through the proxy must land in the ACTIVE
namespace's DB file, never in the owner's.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.namespace_context import set_active_namespace
from services.data.mount_store import DataMountStore

pytestmark = pytest.mark.unit

SERVER_DIR = Path(__file__).resolve().parents[2]


def _load_real_module(relpath: str, name: str):
    """File-load a core module under a private name (conftest stubs `core`)."""
    spec = importlib.util.spec_from_file_location(name, SERVER_DIR / relpath)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_real_database():
    """File-load core.database under a private name (conftest stubs it)."""
    return _load_real_module(
        "core/database.py", f"tests._routing_db_{uuid.uuid4().hex}"
    ).Database


def _load_namespaced_db():
    return _load_real_module(
        "core/namespaced_db.py", f"tests._routing_nsdb_{uuid.uuid4().hex}"
    ).NamespacedDatabase


class _FakePool:
    """Just the surface NamespacedDatabase uses: ``get(namespace)``."""

    def __init__(self, dbs: dict) -> None:
        self._dbs = dbs

    def get(self, namespace: str):
        return self._dbs[namespace]


async def _make_dbs(tmp_path: Path) -> dict:
    Database = _load_real_database()
    dbs = {}
    for ns in ("owner", "acme", "other"):
        db = Database(
            SimpleNamespace(
                database_url=f"sqlite+aiosqlite:///{tmp_path / f'{ns}.db'}",
                database_echo=False,
                database_pool_size=5,
                database_max_overflow=5,
                temporal_namespace="default",
                multi_tenant_namespaces=True,
            )
        )
        await db.startup()
        dbs[ns] = db
    return dbs


def _rows(db_path: Path, table: str = "data_mounts") -> list:
    con = sqlite3.connect(db_path)
    try:
        exists = con.execute(
            "select count(*) from sqlite_master where name=?", (table,)
        ).fetchone()[0]
        if not exists:
            return ["<no table>"]
        return con.execute(f"select user_id, name from {table}").fetchall()
    finally:
        con.close()


def _count(db_path: Path, table: str) -> int:
    con = sqlite3.connect(db_path)
    try:
        exists = con.execute(
            "select count(*) from sqlite_master where name=?", (table,)
        ).fetchone()[0]
        if not exists:
            return -1
        return con.execute(f"select count(*) from {table}").fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def proxy(tmp_path: Path):
    NamespacedDatabase = _load_namespaced_db()
    dbs = asyncio.run(_make_dbs(tmp_path))
    return NamespacedDatabase(_FakePool(dbs)), tmp_path


def test_mount_lands_in_active_namespace_db(proxy, tmp_path):
    """The deploy bug: ensure_schema + session must target the SAME db."""
    proxy_, _ = proxy
    root = tmp_path / "docs"
    root.mkdir()

    set_active_namespace("acme")
    store = DataMountStore(proxy_)
    mount = asyncio.run(store.add_mount("1", name="docs", root_path=str(root)))
    assert mount["name"] == "docs"

    # The row lives in the ACTIVE namespace's file…
    assert _rows(tmp_path / "acme.db") == [("1", "docs")]
    # …and never in the owner DB.
    assert _rows(tmp_path / "owner.db") == []


def test_list_mounts_reads_active_namespace(proxy, tmp_path):
    proxy_, _ = proxy
    root = tmp_path / "shared"
    root.mkdir()
    store = DataMountStore(proxy_)

    set_active_namespace("acme")
    asyncio.run(store.add_mount("1", name="acme_mount", root_path=str(root)))

    # A different namespace sees NO mounts — per-namespace isolation.
    set_active_namespace("other")
    assert asyncio.run(store.list_mounts("1")) == []

    set_active_namespace("acme")
    mounts = asyncio.run(store.list_mounts("1"))
    assert [m["name"] for m in mounts] == ["acme_mount"]


def test_plain_database_still_works(proxy, tmp_path):
    """Single-tenant / tests pass a plain Database (no active_db) — the
    store falls back to it unchanged."""
    proxy_, _ = proxy
    owner_db = proxy_._pool._dbs["owner"]
    root = tmp_path / "plain"
    root.mkdir()

    store = DataMountStore(owner_db)  # not the proxy: no active_db attribute
    mount = asyncio.run(store.add_mount("1", name="plain", root_path=str(root)))
    assert mount["name"] == "plain"
    assert asyncio.run(store.list_mounts("1")) != []


def test_conversations_are_per_namespace(proxy, tmp_path):
    """Agent conversations / terminal transcripts are namespace data — the
    user's directive: nothing global except user authentication."""
    from services.agent_context import list_conversations, save_conversation

    proxy_, _ = proxy
    set_active_namespace("acme")
    asyncio.run(
        save_conversation(
            proxy_,
            workflow_id="wf-1",
            generation=1,
            agent_node_id="agent:1",
            messages=[{"role": "user", "content": "hola"}],
        )
    )

    # The conversation row lives in the ACTIVE namespace's file…
    assert _count(tmp_path / "acme.db", "agent_conversations") == 1
    # …and the owner DB stays clean.
    assert _count(tmp_path / "owner.db", "agent_conversations") in (0, -1)

    # Listing from another namespace sees nothing.
    set_active_namespace("other")
    assert asyncio.run(list_conversations(proxy_, workflow_id="wf-1")) == []

    set_active_namespace("acme")
    rows = asyncio.run(list_conversations(proxy_, workflow_id="wf-1"))
    assert len(rows) == 1
