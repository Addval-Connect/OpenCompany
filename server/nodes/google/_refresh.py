"""Google Workspace service-status refresh callback (Wave 11.I, milestone J).

Moved from ``services/status_broadcaster._refresh_google_status``.
Plugin packages register their own callback via
``status_broadcaster.register_service_refresh``; the broadcaster no
longer hardcodes a per-service refresh.

Reads OAuth tokens via ``auth_service.get_oauth_tokens("google")`` and
mirrors the result into the broadcaster cache.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from opentelemetry import trace

if TYPE_CHECKING:
    from services.status_broadcaster import StatusBroadcaster

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


async def refresh_google_status(broadcaster: "StatusBroadcaster") -> None:
    """No-op: Google OAuth status is namespace-scoped.

    The background refresh has no namespace context and cannot determine
    which namespace's token to check. Status is reported correctly by the
    on-demand ``status()`` handler in ``oauth_lifecycle.py``, which reads
    the active namespace from the WebSocket connection.
    """
