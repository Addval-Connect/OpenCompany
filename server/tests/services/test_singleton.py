"""Tests for the namespace-scoped ServiceSingleton.

Locks the tenant-isolation fix: long-lived plugin services (bot
connections, SDK sessions) must be keyed by (class, namespace) — the
pre-fix process-wide singleton made every tenant share whichever
tenant's service connected last.
"""

from __future__ import annotations

import pytest

from core.namespace_context import set_active_namespace
from services.plugin.singleton import ServiceSingleton


class _ServiceA(ServiceSingleton):
    def __init__(self) -> None:
        self.tag = "A"


class _ServiceB(ServiceSingleton):
    def __init__(self) -> None:
        self.tag = "B"


@pytest.fixture(autouse=True)
def _clean_singletons():
    yield
    _ServiceA.reset_instance()
    _ServiceB.reset_instance()


class TestNamespaceKeyedInstances:
    async def test_different_namespaces_get_different_instances(self):
        set_active_namespace("tenant-a")
        a1 = _ServiceA.instance()
        set_active_namespace("tenant-b")
        a2 = _ServiceA.instance()

        assert a1 is not a2
        set_active_namespace("tenant-a")
        assert _ServiceA.instance() is a1  # same namespace → same instance

    async def test_explicit_namespace_overrides_context(self):
        set_active_namespace("tenant-a")
        explicit = _ServiceA.instance(namespace="tenant-b")
        ambient = _ServiceA.instance()

        assert explicit is not ambient
        assert _ServiceA.instance(namespace="tenant-b") is explicit

    async def test_subclasses_do_not_share_the_instance_store(self):
        set_active_namespace("tenant-a")
        a = _ServiceA.instance()
        b = _ServiceB.instance()

        assert a is not b
        assert a.tag == "A" and b.tag == "B"
        assert _ServiceA.instance() is a
        assert _ServiceB.instance() is b

    async def test_reset_instance_namespace_scoped(self):
        set_active_namespace("tenant-a")
        a = _ServiceA.instance()
        set_active_namespace("tenant-b")
        b = _ServiceA.instance()

        _ServiceA.reset_instance("tenant-a")
        assert _ServiceA.instance(namespace="tenant-a") is not a  # rebuilt
        assert _ServiceA.instance(namespace="tenant-b") is b  # survived

    async def test_reset_instance_full_clear(self):
        a = _ServiceA.instance(namespace="tenant-a")
        b = _ServiceA.instance(namespace="tenant-b")

        _ServiceA.reset_instance()
        assert _ServiceA.instance(namespace="tenant-a") is not a
        assert _ServiceA.instance(namespace="tenant-b") is not b
