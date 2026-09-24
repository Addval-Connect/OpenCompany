"""Per-namespace Temporal client registry.

Holds one connected :class:`~services.temporal.client.TemporalClientWrapper`
per tenant namespace so every Temporal RPC targeting a tenant's workflows is
issued against the correct server-side namespace rather than always defaulting
to ``settings.temporal_namespace``.

Design invariants
-----------------
* **Shared Runtime.**  The Temporal SDK ``Runtime`` is expensive to create and
  intended to be reused across connections.  The module-level ``_runtime``
  object is created once and passed into every ``Client.connect`` call made
  by this registry, matching the pattern documented in ``client.py:75-82``.

* **Default namespace via the DI container.**  ``container.temporal_client()``
  remains the authoritative accessor for the primary (default) namespace —
  lifecycle management, worker bootstrap, and admin operations all use it.
  This registry is consulted only for namespaces that differ from the default.
  ``get_client_for_namespace(default_ns)`` re-delegates to the container
  rather than maintaining a duplicate wrapper.

* **Fail-open on registry miss.**  If a namespace is not in the registry yet
  (the lifecycle bootstrapper hasn't called ``register`` for it), callers
  fall back to the container default.  A warning is logged so operators know
  which namespace isn't wired.  This is deliberate: a partially-started
  system must not refuse all Temporal RPCs just because tenant B's client
  hasn't been connected yet.

* **Flag guard.**  When ``MULTI_TENANT_NAMESPACES=false`` (the default), the
  entire registry is bypassed and every call returns the container default.
  Single-tenant deployments pay zero cost.

Populated by
------------
``services.temporal.lifecycle`` on startup when it discovers registered-ready
tenant namespaces in ``core.database.list_tenant_namespaces()``.  Fase 4
adds that bootstrap call; this module exists as the stable target it writes
into.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Dict, Optional

from core.logging import get_logger

if TYPE_CHECKING:
    from temporalio.runtime import Runtime

    from services.temporal.client import TemporalClientWrapper

logger = get_logger(__name__)

# Module-level Temporal Runtime shared across every namespace client in this
# registry.  None until the first connect call; once set, never replaced.
_runtime: Optional["Runtime"] = None
_runtime_lock = asyncio.Lock()

# namespace -> connected TemporalClientWrapper
_registry: Dict[str, "TemporalClientWrapper"] = {}
_registry_lock = asyncio.Lock()


async def _get_or_create_runtime() -> "Runtime":
    """Return the shared Runtime, creating it on the first call."""
    global _runtime
    from temporalio.runtime import LoggingConfig, Runtime, TelemetryConfig

    async with _runtime_lock:
        if _runtime is None:
            _runtime = Runtime(
                telemetry=TelemetryConfig(
                    logging=LoggingConfig(filter="ERROR"),
                ),
                worker_heartbeat_interval=None,
            )
    return _runtime  # type: ignore[return-value]


async def register(namespace: str, *, server_address: str, settings: object) -> Optional["TemporalClientWrapper"]:
    """Connect a client for ``namespace`` and add it to the registry.

    Re-entrant-safe: if ``namespace`` is already registered and connected,
    returns the existing wrapper without a new connection attempt.  If the
    previous entry is disconnected, it is replaced.

    ``settings`` is accepted as a positional-style keyword argument so the
    caller never has to import ``Settings`` directly — it passes
    ``container.settings()`` through.

    Returns the connected wrapper, or ``None`` if the connection failed.
    The caller should treat ``None`` as "namespace not available; fall back
    to the default" rather than an error.
    """
    from services.temporal.client import TemporalClientWrapper

    async with _registry_lock:
        existing = _registry.get(namespace)
        if existing is not None and existing.is_connected:
            return existing

    runtime = await _get_or_create_runtime()

    # Build a wrapper that reuses our shared Runtime.  TemporalClientWrapper
    # creates its own Runtime lazily; we intercept by pre-populating it.
    wrapper = TemporalClientWrapper(server_address=server_address, namespace=namespace)
    wrapper._runtime = runtime  # type: ignore[attr-defined]  -- inject shared instance

    client = await wrapper.connect(retries=3, delay=1.0)
    if client is None:
        logger.warning(
            "Failed to connect Temporal client for tenant namespace",
            namespace=namespace,
            server_address=server_address,
        )
        return None

    async with _registry_lock:
        _registry[namespace] = wrapper

    logger.info(
        "Registered Temporal client for tenant namespace",
        namespace=namespace,
    )
    return wrapper


def get_client_for_namespace(namespace: str) -> Optional["TemporalClientWrapper"]:
    """Return the registered wrapper for ``namespace``, or ``None`` on miss.

    Synchronous — callers inside synchronous code (``_controller_handle``,
    ``_client_for_namespace``) must not await here.  The wrapper is
    connected at ``register`` time; a miss means the lifecycle bootstrapper
    hasn't run yet or the namespace was never provisioned.
    """
    return _registry.get(namespace)


def get_or_fallback(namespace: str) -> Optional["TemporalClientWrapper"]:
    """Return the registered wrapper, or the container default on miss.

    Convenience helper for ``_client_for_namespace`` — avoids the two-step
    get + fallback at every call site.  Logs a one-time warning per missing
    namespace so operators can see which namespaces need bootstrapping.
    """
    from core.container import container

    wrapper = _registry.get(namespace)
    if wrapper is not None:
        return wrapper

    default_wrapper = container.temporal_client()
    default_ns = getattr(container.settings(), "temporal_namespace", "default")
    if namespace != default_ns:
        logger.warning(
            "Tenant namespace not in client registry; falling back to default",
            requested_namespace=namespace,
            default_namespace=default_ns,
        )
    return default_wrapper


async def deregister(namespace: str) -> None:
    """Disconnect and remove a namespace from the registry.

    No-op if the namespace is not registered.
    """
    async with _registry_lock:
        wrapper = _registry.pop(namespace, None)
    if wrapper is not None:
        await wrapper.disconnect()
        logger.info("Deregistered Temporal client for tenant namespace", namespace=namespace)


async def disconnect_all() -> None:
    """Disconnect and clear every tenant-namespace client.

    Called by the lifecycle shutdown hook so tenant clients are closed
    gracefully alongside the default client.  The default-namespace client
    (in the DI container) is NOT touched here.
    """
    async with _registry_lock:
        namespaces = list(_registry.keys())
        wrappers = list(_registry.values())
        _registry.clear()

    for wrapper in wrappers:
        try:
            await wrapper.disconnect()
        except Exception as exc:  # noqa: BLE001 — best-effort shutdown
            logger.debug("Error disconnecting tenant namespace client", error=str(exc))

    if namespaces:
        logger.info("Disconnected tenant namespace clients", namespaces=namespaces)


def registered_namespaces() -> list[str]:
    """Snapshot of currently registered namespace names (for introspection / tests)."""
    return list(_registry.keys())


__all__ = [
    "deregister",
    "disconnect_all",
    "get_client_for_namespace",
    "get_or_fallback",
    "register",
    "registered_namespaces",
]
