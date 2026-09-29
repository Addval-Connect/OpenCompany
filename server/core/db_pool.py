"""Per-namespace Database and CredentialsDatabase pools.

Each namespace gets its own SQLite files under:
  {data_dir}/namespaces/{namespace}/workflow.db
  {data_dir}/namespaces/{namespace}/credentials.db

Instances are created lazily on first access and cached for reuse.
The pool is safe for asyncio (single-threaded event loop, plain dict).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from core.config import Settings
    from core.database import Database
    from core.credentials_database import CredentialsDatabase
    from core.encryption import EncryptionService

logger = logging.getLogger(__name__)


class DatabasePool:
    """Lazy per-namespace Database pool."""

    def __init__(self, settings: "Settings") -> None:
        self.settings = settings
        self._pool: Dict[str, "Database"] = {}
        self._initialized: Dict[str, bool] = {}

    def _db_url(self, namespace: str) -> str:
        # Use _resolve_under_data so that a relative DATA_DIR (e.g. the dev
        # mode ".opencompany") is anchored to the repo root via project_root(),
        # not to the CWD of the uvicorn subprocess (server/).  Without this,
        # namespace DBs land in server/.opencompany/ while everything else
        # (credentials, workflow.db) lands in <repo>/.opencompany/.
        data_dir = Path(self.settings._resolve_under_data(""))
        ns_dir = data_dir / "namespaces" / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        db_path = ns_dir / "workflow.db"
        return f"sqlite+aiosqlite:///{db_path}"

    def get(self, namespace: str) -> "Database":
        """Return (creating and lazily starting if needed) the Database for *namespace*."""
        if namespace not in self._pool:
            from core.database import Database

            class _NsSettings:
                """Thin wrapper that overrides database_url for a specific namespace."""

                def __init__(self, real_settings: "Settings", url: str) -> None:
                    self._s = real_settings
                    self._url = url

                @property
                def database_url(self) -> str:
                    return self._url

                def __getattr__(self, name: str):
                    return getattr(self._s, name)

            ns_url = self._db_url(namespace)
            ns_settings = _NsSettings(self.settings, ns_url)
            db = Database(ns_settings)  # type: ignore[arg-type]
            self._pool[namespace] = db
            logger.debug("DatabasePool: created DB for namespace=%s", namespace)
        return self._pool[namespace]

    async def startup_all(self) -> None:
        """Initialize all already-created pool entries (called at app startup)."""
        for ns, db in list(self._pool.items()):
            if db.engine is None:
                await db.startup()
                logger.info("DatabasePool: initialized namespace=%s", ns)

    async def startup_namespace(self, namespace: str) -> "Database":
        """Ensure the namespace DB exists and is initialized, then return it."""
        db = self.get(namespace)
        if not self._initialized.get(namespace):
            await db.startup()
            self._initialized[namespace] = True
            logger.info("DatabasePool: initialized namespace=%s", namespace)
        return db


class CredentialsPool:
    """Lazy per-namespace CredentialsDatabase pool.

    Each namespace gets its own CredentialsDatabase AND its own
    EncryptionService so that per-DB salts derive different Fernet keys.
    All encryption services use the same server-wide passphrase
    (API_KEY_ENCRYPTION_KEY) but different per-DB salts.
    """

    def __init__(self, settings: "Settings", encryption: "EncryptionService") -> None:
        self.settings = settings
        self._master_encryption = encryption  # used as template only
        self._pool: Dict[str, "CredentialsDatabase"] = {}
        self._encryptions: Dict[str, "EncryptionService"] = {}
        self._initialized: Dict[str, bool] = {}

    @property
    def encryption(self) -> "EncryptionService":
        """Return the encryption service for the currently active namespace."""
        from core.namespace_context import get_active_namespace
        ns = get_active_namespace()
        return self._encryptions.get(ns, self._master_encryption)

    def _creds_path(self, namespace: str) -> str:
        data_dir = Path(self.settings.data_dir)
        ns_dir = data_dir / "namespaces" / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        return str(ns_dir / "credentials.db")

    def get(self, namespace: str) -> "CredentialsDatabase":
        """Return (creating and initializing if needed) the CredentialsDatabase for *namespace*."""
        if namespace not in self._pool:
            from core.credentials_database import CredentialsDatabase
            from core.encryption import EncryptionService

            enc = EncryptionService()
            self._encryptions[namespace] = enc
            creds_db = CredentialsDatabase(
                db_path=self._creds_path(namespace),
                encryption=enc,
            )
            self._pool[namespace] = creds_db
            logger.debug("CredentialsPool: created DB for namespace=%s", namespace)
        return self._pool[namespace]

    async def startup_namespace(self, namespace: str) -> "CredentialsDatabase":
        """Ensure the namespace credentials DB is initialized and encrypted."""
        creds_db = self.get(namespace)
        if not self._initialized.get(namespace):
            enc = self._encryptions[namespace]
            salt = await creds_db.initialize()
            enc.initialize(self.settings.api_key_encryption_key, salt)
            self._initialized[namespace] = True
            logger.info("CredentialsPool: initialized namespace=%s", namespace)
        return creds_db
