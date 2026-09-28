"""Microsoft Graph service-status refresh callback.

Registered via ``status_broadcaster.register_service_refresh``. Reads
OAuth tokens via ``auth_service.get_oauth_tokens("microsoft")`` and
mirrors the connected/disconnected state into the broadcaster cache so
a freshly-connected client reflects status on the next refresh cycle.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from opentelemetry import trace

if TYPE_CHECKING:
    from services.status_broadcaster import StatusBroadcaster

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


async def refresh_microsoft_status(broadcaster: "StatusBroadcaster") -> None:
    """No-op: Microsoft OAuth status is namespace-scoped.

    The background refresh has no namespace context and cannot determine
    which namespace's token to check. Status is reported correctly by the
    on-demand ``status()`` handler in ``oauth_lifecycle.py``, which reads
    the active namespace from the WebSocket connection.
    """
