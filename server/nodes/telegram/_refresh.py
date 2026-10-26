"""Telegram service-status refresh callback.

Moved from ``services/status_broadcaster._refresh_telegram_status``.
The broadcaster no longer hardcodes a per-service refresh — instead
plugin packages register their own callback via
``status_broadcaster.register_service_refresh``.

The callback runs once per WebSocket client connect (inside the
``_refresh_all_services`` TaskGroup).  Auth reads + owner restore
happen inside :class:`TelegramService`; this function just decides
whether to attempt an auto-reconnect and mirrors the resulting status
into the broadcaster cache.
"""

from __future__ import annotations

import logging
from typing import Dict, TYPE_CHECKING

from opentelemetry import trace

if TYPE_CHECKING:
    from services.status_broadcaster import StatusBroadcaster

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


async def refresh_telegram_status(broadcaster: "StatusBroadcaster") -> None:
    """Startup refresh — PER-NAMESPACE since the tenant-isolation fix.

    Enumerates every registered namespace and connects (or reports) each
    tenant's OWN bot instance, sealing the namespace ContextVar around
    each so credential resolution hits that tenant's DB. The pre-fix
    shape connected ONE process-global bot from whatever namespace was
    active at startup — every tenant then shared and displayed that bot,
    and after a restart only the default tenant's bot ever came back.

    A namespace whose DB has no telegram row simply reports
    ``connected=False`` into its own per-namespace status slot.

    Wave 12 B3: routes through the plugin _events.py wrapper. Cache write
    + tenant-scoped WS broadcast in one call.
    """
    with tracer.start_as_current_span("broadcaster.refresh_telegram") as span:
        try:
            from core.container import container
            from core.namespace_context import get_active_namespace, set_active_namespace

            namespaces = {"default"}
            try:
                for row in await container.database().list_namespaces(ready_only=True):
                    name = row.get("name") if isinstance(row, dict) else getattr(row, "name", None)
                    if name:
                        namespaces.add(str(name))
            except Exception as exc:  # noqa: BLE001 — registry hiccup must not kill the refresh
                logger.warning(f"[Telegram] namespace registry unavailable ({exc}); refreshing default only")

            previous = get_active_namespace()
            for ns in sorted(namespaces):
                set_active_namespace(ns)
                try:
                    await _refresh_namespace(broadcaster, ns, span)
                except Exception as exc:  # noqa: BLE001 — one tenant's failure never blocks the others
                    logger.warning(f"[Telegram] status refresh failed for namespace={ns}: {exc}")
                finally:
                    set_active_namespace(previous)
        except Exception as e:
            span.record_exception(e)
            logger.debug(f"[StatusBroadcaster] Could not refresh Telegram status: {e}")


async def _refresh_namespace(broadcaster: "StatusBroadcaster", ns: str, span) -> None:
    """Connect (or report) ONE namespace's bot into ITS status slot."""
    from ._events import broadcast_telegram_status
    from ._service import get_telegram_service

    service = get_telegram_service()  # namespace-scoped via the sealed ContextVar

    async def _emit(connected: bool, has_token: bool) -> None:
        """Snapshot service state and broadcast (per-ns cache write + WS)."""
        s = service.get_status() if connected else {}
        await broadcast_telegram_status(
            connected=connected,
            bot_id=s.get("bot_id") if connected else None,
            bot_username=s.get("bot_username") if connected else None,
            bot_name=s.get("bot_name") if connected else None,
            owner_chat_id=s.get("owner_chat_id") if connected else None,
            has_stored_token=has_token,
            namespace=ns,
        )

    if service.connected:
        await _emit(True, True)
        span.set_attribute(f"ns.{ns}.path", "already_connected")
    elif not await service.has_stored_token():
        await _emit(False, False)
        span.set_attribute(f"ns.{ns}.path", "no_token")
    else:
        span.set_attribute(f"ns.{ns}.path", "auto_reconnect")
        logger.info(f"[StatusBroadcaster] Auto-reconnecting Telegram bot (namespace={ns})...")
        result = await service.connect()
        ok = bool(result.get("success"))
        await _emit(ok, True)
        span.set_attribute(f"ns.{ns}.reconnect_ok", ok)
        if ok:
            bot_username = (broadcaster._status.get("telegram_by_ns") or {}).get(ns, {}).get("bot_username")
            logger.info(f"[StatusBroadcaster] Telegram auto-reconnected (namespace={ns}): @{bot_username}")
        else:
            logger.warning(
                f"[StatusBroadcaster] Telegram auto-reconnect failed (namespace={ns}): {result.get('error')}"
            )


async def precheck_telegram_trigger(parameters: Dict) -> str | None:
    """Trigger-precheck: ensure the Telegram bot is connected before
    entering the event-wait loop.

    Returns an error string to short-circuit, or None to proceed.
    """
    from ._service import get_telegram_service

    service = get_telegram_service()
    if not service.connected:
        return "Telegram bot not connected. Add bot token in Credentials."
    sender_filter = parameters.get("sender_filter", "all")
    logger.info("[TelegramTrigger] starting " f"sender_filter={sender_filter} " f"owner_detected={service.owner_chat_id is not None}")
    return None
