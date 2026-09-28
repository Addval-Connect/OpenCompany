"""Namespace-routing proxy classes for Database and CredentialsDatabase.

NamespacedDatabase:
  - AUTH_METHODS (users, namespaces, namespace assignments) always route
    to the "owner" namespace DB regardless of the active ContextVar
    namespace.  These tables are global/shared.
  - Everything else routes to the pool entry for the current namespace
    (get_active_namespace()).

NamespacedCredentialsDatabase:
  - All methods route to the pool entry for the current namespace.
    No auth distinction — credentials are 100% per-namespace.

Both classes use __getattr__ delegation so every new method added to
Database / CredentialsDatabase is automatically namespace-aware without
touching this file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.namespace_context import get_active_namespace

if TYPE_CHECKING:
    from core.database import Database
    from core.credentials_database import CredentialsDatabase
    from core.db_pool import DatabasePool, CredentialsPool


# Methods that operate on shared auth tables and must always hit the
# "owner" namespace DB regardless of the active request namespace.
_AUTH_METHODS: frozenset[str] = frozenset(
    {
        # User CRUD
        "get_user_by_id",
        "get_user_by_email",
        "get_users",
        "create_user",
        "update_user",
        "delete_user",
        "authenticate_user",
        "record_user_login",
        "get_user_auth_context",
        "get_all_users_for_admin",
        # User settings (stored per-user globally)
        "get_user_settings",
        "save_user_settings",
        # Namespace management
        "upsert_namespace",
        "get_namespace",
        "list_namespaces",
        "get_active_namespace_for_user",
        "set_active_namespace_for_user",
        "list_user_namespaces",
        "assign_user_namespace",
        "is_user_in_namespace",
        # Tenant namespace (1:1 user→temporal-ns mapping)
        "get_tenant_namespace",
        "list_tenant_namespaces",
        "upsert_tenant_namespace",
        "set_tenant_namespace_status",
        # Invite tokens (global)
        "create_invite_token",
        "use_invite_token",
        # Internal migration helpers (only run against owner DB)
        "_migrate_user_settings",
        "_migrate_tenant_namespaces",
        "_migrate_user_namespaces",
        "_migrate_credentials_to_namespace",
        "_migrate_workflow_namespace",
        "_migrate_workflow_owner",
        "_migrate_agent_teams",
        "_migrate_workflow_controls",
        "_migrate_generation_scoped_runtime_data",
        # Lifecycle
        "startup",
        "shutdown",
        "get_session",
    }
)


class NamespacedDatabase:
    """Database proxy that routes calls per namespace via ContextVar.

    Auth methods always target the "owner" DB.
    All other methods target the namespace-specific DB.
    """

    def __init__(self, pool: "DatabasePool") -> None:
        self._pool = pool

    @property
    def _owner(self) -> "Database":
        return self._pool.get("owner")

    def _active_db(self) -> "Database":
        return self._pool.get(get_active_namespace())

    def __getattr__(self, name: str):
        if name.startswith("_"):
            # Private/dunder attrs not in our set → active namespace DB
            # (handles _pool, _owner etc. set in __init__ via object.__setattr__)
            raise AttributeError(name)
        if name in _AUTH_METHODS:
            return getattr(self._owner, name)
        return getattr(self._active_db(), name)

    # Expose engine/async_session of the owner db for startup bootstrapping
    @property
    def engine(self):
        return self._owner.engine

    @property
    def async_session(self):
        return self._owner.async_session

    @property
    def settings(self):
        return self._owner.settings

    async def startup(self):
        """Initialize the owner DB; other namespace DBs are lazily started."""
        await self._owner.startup()

    async def shutdown(self):
        for db in self._pool._pool.values():
            await db.shutdown()


class NamespacedCredentialsDatabase:
    """CredentialsDatabase proxy — all calls go to namespace-specific DB.

    No auth distinction: credentials are 100% per-namespace.
    """

    def __init__(self, pool: "CredentialsPool") -> None:
        self._pool = pool

    def _active_creds(self) -> "CredentialsDatabase":
        return self._pool.get(get_active_namespace())

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._active_creds(), name)

    @property
    def encryption(self):
        return self._pool.encryption
