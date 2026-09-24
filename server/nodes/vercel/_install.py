"""Vercel CLI auto-installer.

The Vercel CLI ships as the npm package ``vercel`` — it lands in the
shared OpenCompany packages tree at :func:`core.paths.packages_dir`
(``<DATA_DIR>/packages/``), the same single ``package.json`` +
``node_modules/`` that holds ``@anthropic-ai/claude-code`` /
``edgymeow`` / ``agent-browser`` / ``cf``.
:func:`core.js_runtime.add_package` (``bun add --cwd <packages_dir>
<spec>``) extends the shared tree idempotently and the bin shim runs on
the bun runtime; no Node or npm is involved.

A system install on PATH is preferred; the install only fires when no
system binary is found. Pin ``_NPM_SPEC`` when bumping (whatsapp
precedent — ``@latest`` makes cold installs non-reproducible).
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Optional

from core.js_runtime import add_package, shared_tree_bin
from core.logging import get_logger

logger = get_logger(__name__)

_NPM_SPEC = "vercel@54.21.1"

_cached_path: Optional[Path] = None
_install_lock = asyncio.Lock()


def vercel_cli_path() -> Optional[Path]:
    """Sync getter for the resolved binary path. Returns ``None`` if
    :func:`ensure_vercel_cli` hasn't run yet (or never resolved)."""
    return _cached_path


def _shared_tree_bin() -> Path:
    return shared_tree_bin("vercel")


def _install() -> Path:
    """Blocking ``bun add`` into the shared tree. Raises on failure."""
    bin_path = _shared_tree_bin()
    logger.info("[Vercel] installing %s into the shared packages tree", _NPM_SPEC)
    result = add_package(_NPM_SPEC)
    if result.returncode != 0 or not bin_path.exists():
        raise RuntimeError(f"bun add {_NPM_SPEC} failed: {result.stderr.strip()[:500]}")
    logger.info("[Vercel] CLI installed at %s", bin_path)
    return bin_path


async def ensure_vercel_cli() -> Path:
    """Return absolute path to the vercel binary, installing on miss.
    Idempotent + concurrent-safe.

    Resolution order (stripe idiom):
      1. Cached path from a prior call (in-process).
      2. ``shutil.which("vercel")`` — system install on PATH.
      3. Previously-installed shim in the shared packages tree.
      4. Fresh ``bun add`` into the shared tree.
    """
    global _cached_path
    if _cached_path and _cached_path.exists():
        return _cached_path

    sys_path = shutil.which("vercel")
    if sys_path:
        _cached_path = Path(sys_path)
        logger.info("[Vercel] using system CLI at %s", _cached_path)
        return _cached_path

    async with _install_lock:
        if _cached_path and _cached_path.exists():
            return _cached_path
        target = _shared_tree_bin()
        if target.exists():
            _cached_path = target
            return target
        # The install blocks for tens of seconds — keep the event loop free.
        installed = await asyncio.to_thread(_install)
        _cached_path = installed
        await _disable_telemetry(installed)
        return installed


async def _disable_telemetry(binary: Path) -> None:
    """Best-effort one-shot ``vercel telemetry disable`` right after a
    fresh install (ephemeral-runner hygiene). Non-fatal on any failure."""
    try:
        from ._service import global_argv, vercel_env

        proc = await asyncio.create_subprocess_exec(
            str(binary),
            *global_argv(["telemetry", "disable"]),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=vercel_env(),
        )
        await asyncio.wait_for(proc.wait(), timeout=30)
    except Exception as e:  # noqa: BLE001 — hygiene step, never blocks install
        logger.debug("[Vercel] telemetry disable skipped: %s", e)


__all__ = ["ensure_vercel_cli", "vercel_cli_path"]
