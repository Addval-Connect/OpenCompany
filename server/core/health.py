"""Health check utilities for daemon monitoring.

Provides uptime tracking and comprehensive health status for /health endpoint.
"""

import time
from typing import Dict, Any, TYPE_CHECKING

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

if TYPE_CHECKING:
    from core.config import Settings
    from core.database import Database
    from core.cache import CacheService

# Module-level startup time tracking
_startup_time: float = 0.0


def set_startup_time() -> None:
    """Record the application startup time. Call once during lifespan startup."""
    global _startup_time
    _startup_time = time.time()


def get_uptime() -> float:
    """Get uptime in seconds since startup."""
    return time.time() - _startup_time if _startup_time else 0.0


def get_memory_mb() -> float:
    """Get current process memory usage in MB."""
    if not PSUTIL_AVAILABLE:
        return 0.0
    try:
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def get_disk_percent(path: str = ".") -> float:
    """Get disk usage percentage for given path."""
    if not PSUTIL_AVAILABLE:
        return 0.0
    try:
        return psutil.disk_usage(path).percent
    except Exception:
        return 0.0


def get_cpu_percent() -> float:
    """Get current process CPU usage percentage."""
    if not PSUTIL_AVAILABLE:
        return 0.0
    try:
        return psutil.Process().cpu_percent(interval=0.1)
    except Exception:
        return 0.0


async def check_database(database: "Database") -> bool:
    """Check database connectivity."""
    try:
        async with database.get_session() as session:
            from sqlalchemy import text

            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def check_cache(cache: "CacheService") -> bool:
    """Check cache connectivity."""
    try:
        test_key = "_health_check"
        await cache.set(test_key, "ok", ttl=10)
        result = await cache.get(test_key)
        await cache.delete(test_key)
        return result == "ok"
    except Exception:
        return False


def readiness_report(
    *,
    db_ok: bool,
    temporal_enabled: bool,
    phase: str,
    worker_ready: bool,
    pool_ready: bool,
    client_connected: bool,
    version: str,
) -> tuple[int, Dict[str, Any]]:
    """Pure readiness verdict shared by ``/health/ready`` and its tests.

    Ready = database reachable AND (Temporal disabled OR the worker manager
    has started). The worker manager is the LAST thing
    ``services.temporal.lifecycle`` wires, so it is the honest signal that a
    Run can actually execute; a connected client alone is not enough.
    Returns ``(status_code, body)``: 200 when ready, 503 otherwise, with the
    coarse ``phase`` string a splash screen can show.
    """
    ready = bool(db_ok and (not temporal_enabled or worker_ready))
    body: Dict[str, Any] = {
        "ready": ready,
        "phase": "ready" if ready else ("disabled" if not temporal_enabled else phase),
        "database": bool(db_ok),
        "temporal": {
            "enabled": bool(temporal_enabled),
            "phase": phase,
            "client_connected": bool(client_connected),
            "worker_ready": bool(worker_ready),
            "pool_ready": bool(pool_ready),
        },
        "version": version,
    }
    return (200 if ready else 503), body


async def get_health_status(database: "Database", cache: "CacheService", settings: "Settings") -> Dict[str, Any]:
    """Get comprehensive health status for /health endpoint.

    Returns:
        Dict containing status, uptime, resource usage, and feature flags.
    """
    # Run health checks
    db_healthy = await check_database(database)
    cache_healthy = await check_cache(cache)

    # Determine overall status
    overall_status = "healthy" if (db_healthy and cache_healthy) else "degraded"

    return {
        "status": overall_status,
        "uptime_seconds": round(get_uptime(), 1),
        "memory_mb": round(get_memory_mb(), 1),
        "disk_percent": round(get_disk_percent(), 1),
        "cpu_percent": round(get_cpu_percent(), 1),
        "checks": {
            "database": db_healthy,
            "cache": cache_healthy,
        },
        "features": {
            "redis": settings.redis_enabled,
            "temporal": settings.temporal_enabled,
            "cleanup": settings.cleanup_enabled,
            "ws_logging": settings.ws_logging_enabled,
        },
        "psutil_available": PSUTIL_AVAILABLE,
    }
