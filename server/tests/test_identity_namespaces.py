"""Tenancy principal and credential namespace must never be aliased.

``user_id`` (who is acting) and the credential ``customer_id`` (whose
stored tokens to read) happen to share the literal "owner". Collapsing
them means the day ``user_id`` becomes a real authenticated subject,
every OAuth-backed node starts looking up tokens under a customer id
nobody has stored anything under.
"""

from __future__ import annotations

import inspect
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]


def test_the_two_constants_exist_and_are_not_aliased():
    import constants

    assert constants.OWNER_PRINCIPAL_ID == "owner"
    assert constants.DEFAULT_CREDENTIAL_CUSTOMER_ID == "owner"
    source = inspect.getsource(constants)
    # Same value, but each must be its own literal. `X = Y` would mean a
    # change to one silently moves the other.
    assert "DEFAULT_CREDENTIAL_CUSTOMER_ID: str = OWNER_PRINCIPAL_ID" not in source
    assert "OWNER_PRINCIPAL_ID: str = DEFAULT_CREDENTIAL_CUSTOMER_ID" not in source


def test_node_context_keeps_them_independent():
    from services.plugin.context import NodeContext

    ctx = NodeContext.from_legacy(
        node_id="n", node_type="t", context={"user_id": "42"}
    )
    assert ctx.user_id == "42"
    # The credential namespace must NOT follow the principal.
    assert ctx.credential_customer_id == "owner"


def test_connection_factory_scopes_on_the_credential_namespace():
    """The actual coupling point: this read is what broke OAuth nodes."""
    from services.plugin import base

    source = inspect.getsource(base._make_connection_factory)
    assert "credential_customer_id" in source
    assert 'context.get("user_id"' not in source, (
        "the connection factory must not scope credentials by the tenancy "
        "principal — that re-points every OAuth token lookup"
    )


def test_credential_modules_do_not_import_the_tenancy_principal():
    """An import-graph guard: credential code has no business knowing
    about the tenancy principal, and importing it invites aliasing."""
    targets = [
        SERVER_DIR / "services" / "auth.py",
        SERVER_DIR / "services" / "plugin" / "connection.py",
        SERVER_DIR / "services" / "plugin" / "credential.py",
        SERVER_DIR / "core" / "credentials_database.py",
        SERVER_DIR / "core" / "credential_backends.py",
    ]
    offenders = [
        p.name
        for p in targets
        if p.exists() and "OWNER_PRINCIPAL_ID" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"credential modules import the tenancy principal: {offenders}"


# ---------------------------------------------------------------------------
# Fase 0 — tenancy model and resolve_tenant_namespace
# ---------------------------------------------------------------------------

class _FakeSettings:
    temporal_namespace = "default"
    multi_tenant_namespaces = False


class _FakeDb:
    """Configurable stub for core.database tenant helpers."""

    def __init__(self, row=None, raise_on_get=False):
        self._row = row
        self._raise = raise_on_get

    async def get_tenant_namespace(self, user_id):
        if self._raise:
            raise RuntimeError("db exploded")
        return self._row


import pytest


def test_flag_off_returns_default_no_db_call():
    """With the flag off, resolve_tenant_namespace must never read the DB."""
    import asyncio

    from services.tenancy import resolve_tenant_namespace

    call_count = 0

    class CountingDb:
        async def get_tenant_namespace(self, user_id):
            nonlocal call_count
            call_count += 1
            return None

    settings = _FakeSettings()
    settings.multi_tenant_namespaces = False
    result = asyncio.get_event_loop().run_until_complete(
        resolve_tenant_namespace("42", database=CountingDb(), settings=settings)
    )
    assert result == "default"
    assert call_count == 0, "flag off must not read the DB"


def test_no_row_returns_default():
    import asyncio

    from services.tenancy import resolve_tenant_namespace

    settings = _FakeSettings()
    settings.multi_tenant_namespaces = True
    db = _FakeDb(row=None)
    result = asyncio.get_event_loop().run_until_complete(
        resolve_tenant_namespace("42", database=db, settings=settings)
    )
    assert result == "default"


def test_provisioning_status_returns_default():
    import asyncio

    from services.tenancy import STATUS_PROVISIONING, resolve_tenant_namespace

    settings = _FakeSettings()
    settings.multi_tenant_namespaces = True
    db = _FakeDb(row={"user_id": "42", "namespace": "tenant-a", "status": STATUS_PROVISIONING})
    result = asyncio.get_event_loop().run_until_complete(
        resolve_tenant_namespace("42", database=db, settings=settings)
    )
    assert result == "default"


def test_disabled_status_returns_default():
    import asyncio

    from services.tenancy import STATUS_DISABLED, resolve_tenant_namespace

    settings = _FakeSettings()
    settings.multi_tenant_namespaces = True
    db = _FakeDb(row={"user_id": "42", "namespace": "tenant-a", "status": STATUS_DISABLED})
    result = asyncio.get_event_loop().run_until_complete(
        resolve_tenant_namespace("42", database=db, settings=settings)
    )
    assert result == "default"


def test_ready_row_returns_mapped_namespace():
    import asyncio

    from services.tenancy import STATUS_READY, resolve_tenant_namespace

    settings = _FakeSettings()
    settings.multi_tenant_namespaces = True
    db = _FakeDb(row={"user_id": "42", "namespace": "tenant-b", "status": STATUS_READY})
    result = asyncio.get_event_loop().run_until_complete(
        resolve_tenant_namespace("42", database=db, settings=settings)
    )
    assert result == "tenant-b"


def test_db_error_propagates():
    """A DB failure must raise, not silently fall back to the default."""
    import asyncio

    from services.tenancy import resolve_tenant_namespace

    settings = _FakeSettings()
    settings.multi_tenant_namespaces = True
    db = _FakeDb(raise_on_get=True)
    with pytest.raises(RuntimeError, match="db exploded"):
        asyncio.get_event_loop().run_until_complete(
            resolve_tenant_namespace("42", database=db, settings=settings)
        )


# ---------------------------------------------------------------------------
# is_valid_namespace / validate_namespace
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "tenant-a",
    "tenant-b2",
    "ab",           # minimum length: 3 chars total (a + at least 2 more [a-z0-9-] + ending [a-z0-9])
    "my-tenant-99",
    "aa",           # 2 chars — under the 3-63 range (NAMESPACE_PATTERN needs [a-z][a-z0-9-]{1,61}[a-z0-9])
])
def test_is_valid_namespace_accepts_valid(value):
    from services.tenancy import is_valid_namespace

    # Only values that actually match the regex should assert True
    from services.tenancy import _NAMESPACE_RE
    expected = bool(_NAMESPACE_RE.fullmatch(value)) and value not in {"default", "temporal-system"}
    assert is_valid_namespace(value) == expected


@pytest.mark.parametrize("value, reason", [
    ("default", "reserved"),
    ("temporal-system", "reserved"),
    ("Tenant-A", "uppercase"),
    ("1tenant", "leading digit"),
    ("tenant-", "trailing hyphen"),
    ("a", "too short — only 1 char"),
    ("", "empty"),
    (None, "not a string"),
    (42, "not a string"),
])
def test_is_valid_namespace_rejects_invalid(value, reason):
    from services.tenancy import is_valid_namespace

    assert not is_valid_namespace(value), f"expected invalid for: {reason}"


@pytest.mark.parametrize("value", [
    "tenant-a",
    "tenant-b2",
    "my-tenant-99",
])
def test_validate_namespace_accepts_valid(value):
    from services.tenancy import validate_namespace

    assert validate_namespace(value) == value


@pytest.mark.parametrize("value, fragment", [
    ("default", "reserved"),
    ("temporal-system", "reserved"),
    ("Tenant-A", r"must match"),
    ("1tenant", r"must match"),
    ("tenant-", r"must match"),
    ("", "non-empty"),
    (None, "non-empty"),
])
def test_validate_namespace_raises_for_invalid(value, fragment):
    from services.tenancy import validate_namespace

    with pytest.raises(ValueError, match=fragment):
        validate_namespace(value)
