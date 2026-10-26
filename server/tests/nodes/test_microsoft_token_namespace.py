"""Namespace isolation for the Microsoft token refresh caches.

``user_id`` is the same principal ("owner") in every tenant — caches
keyed by user_id alone leaked one tenant's expiry/blocker state into
every other tenant's refresh decisions.
"""

from __future__ import annotations

import time

import pytest

from core.namespace_context import set_active_namespace
from nodes.microsoft import _auth_helper as helper


pytestmark = pytest.mark.node_contract


@pytest.fixture(autouse=True)
def _clean_caches():
    helper._TOKEN_EXPIRY.clear()
    helper._LAST_REFRESH_BLOCKER.clear()
    set_active_namespace("default")
    yield
    helper._TOKEN_EXPIRY.clear()
    helper._LAST_REFRESH_BLOCKER.clear()
    set_active_namespace("default")


class TestNamespaceKeyedTokenCaches:
    def test_fresh_refresh_in_one_namespace_does_not_suppress_another(self):
        set_active_namespace("tenant-a")
        helper._TOKEN_EXPIRY[helper._ns_key("owner")] = time.time() + 1000.0
        assert helper._needs_refresh("owner") is False  # fresh in tenant-a

        set_active_namespace("tenant-b")
        assert helper._needs_refresh("owner") is True  # unknown in tenant-b → must refresh

    def test_blocker_is_namespace_scoped(self):
        set_active_namespace("tenant-a")
        helper._note_blocker("owner", "Entra ID rejected the refresh (invalid_grant)")

        assert helper._last_blocker("owner") == "Entra ID rejected the refresh (invalid_grant)"

        set_active_namespace("tenant-b")
        assert helper._last_blocker("owner") == "the stored refresh token was rejected"

    def test_populated_expiry_survives_context_switch_and_returns(self):
        set_active_namespace("tenant-a")
        helper._TOKEN_EXPIRY[helper._ns_key("owner")] = time.time() + 1000.0
        set_active_namespace("tenant-b")
        helper._TOKEN_EXPIRY[helper._ns_key("owner")] = time.time() + 1000.0

        set_active_namespace("tenant-a")
        assert helper._needs_refresh("owner") is False
        set_active_namespace("tenant-b")
        assert helper._needs_refresh("owner") is False
