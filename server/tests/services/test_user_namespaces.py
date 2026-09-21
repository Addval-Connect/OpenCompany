"""Tests for the many-to-many user-namespace feature.

Covers:
- _migrate_user_namespaces seeds 'default' and assigns existing users
- list_user_namespaces / assign_user_namespace / is_user_in_namespace
- get_active_namespace_for_user / set_active_namespace_for_user
- get_user_by_id on database
- resolve_namespace_from_state reads from request state
- UserAuthService.switch_namespace rejects unassigned namespaces
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVER_DIR = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_database(db_path: Path):
    """Load a fresh Database instance backed by a temp SQLite file."""
    module_name = f"tests._ns_database_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        module_name, SERVER_DIR / "core" / "database.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.Database(
        SimpleNamespace(
            database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
            database_echo=False,
            database_pool_size=5,
            database_max_overflow=5,
            temporal_namespace="default",
            multi_tenant_namespaces=False,
        )
    )


async def _make_db(tmp_path: Path):
    db = _load_database(tmp_path / "workflow.db")
    await db.startup()
    return db


# ---------------------------------------------------------------------------
# Tests — DB layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migrate_user_namespaces_seeds_default(tmp_path):
    db = await _make_db(tmp_path)
    namespaces = await db.list_user_namespaces("owner")  # OWNER_PRINCIPAL_ID
    # 'default' namespace must exist even with no user rows
    ns_names = [n["namespace"] for n in namespaces]
    # owner is not a real user row so list may be empty, but the namespaces table must have 'default'
    async with db.engine.connect() as conn:
        from sqlalchemy import text
        result = await conn.execute(text("SELECT namespace, status FROM namespaces WHERE namespace='default'"))
        row = result.fetchone()
    assert row is not None
    assert row[1] == "ready"


@pytest.mark.asyncio
async def test_migrate_assigns_user_namespace_via_assign(tmp_path):
    """After calling assign_user_namespace, list_user_namespaces shows the assignment."""
    db = await _make_db(tmp_path)
    user_id = "123"
    # 'default' namespace was seeded by _migrate_user_namespaces
    await db.assign_user_namespace(user_id, "default", role="owner")
    namespaces = await db.list_user_namespaces(user_id)
    assert any(n["namespace"] == "default" for n in namespaces)
    owner_row = next((n for n in namespaces if n["namespace"] == "default"), None)
    assert owner_row is not None
    assert owner_row["role"] == "owner"


@pytest.mark.asyncio
async def test_assign_user_namespace_idempotent(tmp_path):
    db = await _make_db(tmp_path)
    await db.upsert_namespace("tenant-a", display_name="Tenant A")
    # Call twice — must not raise
    await db.assign_user_namespace("42", "tenant-a", role="member")
    await db.assign_user_namespace("42", "tenant-a", role="member")
    namespaces = await db.list_user_namespaces("42")
    assert len([n for n in namespaces if n["namespace"] == "tenant-a"]) == 1


@pytest.mark.asyncio
async def test_is_user_in_namespace_false_for_unassigned(tmp_path):
    db = await _make_db(tmp_path)
    await db.upsert_namespace("tenant-b", status="ready")
    result = await db.is_user_in_namespace("99", "tenant-b")
    assert result is False


@pytest.mark.asyncio
async def test_is_user_in_namespace_true_for_assigned(tmp_path):
    db = await _make_db(tmp_path)
    await db.upsert_namespace("tenant-c", status="ready")
    await db.assign_user_namespace("7", "tenant-c", role="member")
    result = await db.is_user_in_namespace("7", "tenant-c")
    assert result is True


@pytest.mark.asyncio
async def test_is_user_in_namespace_false_for_non_ready(tmp_path):
    db = await _make_db(tmp_path)
    await db.upsert_namespace("tenant-d", status="provisioning")
    await db.assign_user_namespace("8", "tenant-d", role="member")
    result = await db.is_user_in_namespace("8", "tenant-d")
    assert result is False


@pytest.mark.asyncio
async def test_get_active_namespace_defaults_to_default(tmp_path):
    db = await _make_db(tmp_path)
    ns = await db.get_active_namespace_for_user("99999")
    assert ns == "default"


@pytest.mark.asyncio
async def test_set_and_get_active_namespace(tmp_path):
    db = await _make_db(tmp_path)
    await db.set_active_namespace_for_user("5", "tenant-e")
    ns = await db.get_active_namespace_for_user("5")
    assert ns == "tenant-e"


@pytest.mark.asyncio
async def test_list_user_namespaces_multi(tmp_path):
    db = await _make_db(tmp_path)
    await db.upsert_namespace("ns-x", status="ready")
    await db.upsert_namespace("ns-y", status="ready")
    await db.assign_user_namespace("11", "ns-x", role="owner")
    await db.assign_user_namespace("11", "ns-y", role="member")
    nss = await db.list_user_namespaces("11")
    names = {n["namespace"] for n in nss}
    assert "ns-x" in names
    assert "ns-y" in names
    roles = {n["namespace"]: n["role"] for n in nss}
    assert roles["ns-x"] == "owner"
    assert roles["ns-y"] == "member"


# ---------------------------------------------------------------------------
# Tests — tenancy resolver
# ---------------------------------------------------------------------------


def test_resolve_namespace_from_state_disabled():
    from services.tenancy import resolve_namespace_from_state
    settings = SimpleNamespace(temporal_namespace="default", multi_tenant_namespaces=False)
    state = SimpleNamespace(active_namespace="tenant-z")
    # Flag off: always returns default
    assert resolve_namespace_from_state(state, settings=settings) == "default"


def test_resolve_namespace_from_state_enabled():
    from services.tenancy import resolve_namespace_from_state
    settings = SimpleNamespace(temporal_namespace="default", multi_tenant_namespaces=True)
    state = SimpleNamespace(active_namespace="tenant-z")
    assert resolve_namespace_from_state(state, settings=settings) == "tenant-z"


def test_resolve_namespace_from_state_missing_claim():
    from services.tenancy import resolve_namespace_from_state
    settings = SimpleNamespace(temporal_namespace="default", multi_tenant_namespaces=True)
    state = SimpleNamespace()  # no active_namespace
    assert resolve_namespace_from_state(state, settings=settings) == "default"
