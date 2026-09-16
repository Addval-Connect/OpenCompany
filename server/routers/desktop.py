"""Desktop-host control surface (mounted only when ``OPENCOMPANY_DESKTOP=1``).

One route: ``POST /api/desktop/shutdown``. The desktop shell calls it on
quit because a Node host cannot deliver ``CTRL_BREAK_EVENT`` on Windows and
``TerminateProcess`` would skip the FastAPI lifespan that reaps Temporal,
the Node sidecar and the WhatsApp bridge. The handler schedules
:func:`core.desktop.request_shutdown` on the loop after the 202 has been
sent, so the shell gets an acknowledgement before the socket goes away.

Auth: the route is on the middleware's public list because the shell holds
no session cookie; instead it must present the per-launch
``OPENCOMPANY_DESKTOP_TOKEN`` in ``X-Desktop-Token`` (constant-time
compared). With the token unset every request is refused.
"""

from __future__ import annotations

import asyncio
import hmac

from fastapi import APIRouter, HTTPException, Request

from core.desktop import desktop_token, request_shutdown
from core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/desktop", tags=["desktop"])

TOKEN_HEADER = "X-Desktop-Token"

# Small delay so the 202 reaches the shell before uvicorn starts closing
# listeners.
_SHUTDOWN_DELAY_SECONDS = 0.2


def _authorize(request: Request) -> None:
    expected = desktop_token()
    presented = request.headers.get(TOKEN_HEADER, "")
    if not expected or not hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid desktop token")


@router.post("/shutdown", status_code=202)
async def shutdown(request: Request) -> dict[str, bool]:
    _authorize(request)
    loop = asyncio.get_running_loop()
    loop.call_later(_SHUTDOWN_DELAY_SECONDS, request_shutdown, "desktop shell requested shutdown")
    return {"accepted": True}


__all__ = ["router", "TOKEN_HEADER"]
