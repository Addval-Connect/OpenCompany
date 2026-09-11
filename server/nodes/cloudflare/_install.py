"""Cloudflare CLI (`cf`) auto-installer — bun, pinned, project-local.

The official Cloudflare CLI ships as the npm package ``cf`` (a
technical preview, "the next version of Wrangler"). It lands in the
shared OpenCompany packages tree at :func:`core.paths.packages_dir`
(``<DATA_DIR>/packages/``), the same single ``package.json`` +
``node_modules/`` that holds ``@anthropic-ai/claude-code`` / ``edgymeow``
/ ``agent-browser`` / ``vercel``. :func:`core.js_runtime.add_package`
(``bun add --cwd <packages_dir> <spec>``) extends the shared tree
idempotently and the bin shim executes on the bun runtime; no Node or
npm is involved.

Unlike the vercel installer, the system-global ``cf`` is deliberately
NEVER consulted (the gh philosophy): the preview CLI's command surface
is schema-generated and shifts between versions (0.0.5's ``--ndjson``
is gone in 0.2.0; write ops changed shape), and this plugin's argv
builders are verified against the pinned version only. Auth state is
unaffected by which binary runs — cf's config paths are user-level and
shared, so a session created by the user's own ``cf auth login`` in a
terminal is visible to this pinned binary too.

Pin ``_NPM_SPEC`` when bumping and re-verify every wrapped command via
``cf <cmd> --help-full`` (whatsapp precedent — ``@latest`` makes cold
installs non-reproducible). cf declares ``engines.node >= 22``; bun
ignores ``engines`` and runs the CLI on its own runtime (verified on
bun 1.4 with no Node on PATH, including ``cf auth whoami``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from core.js_runtime import add_package, shared_tree_bin
from core.logging import get_logger

logger = get_logger(__name__)

_NPM_SPEC = "cf@0.2.0"

_cached_path: Optional[Path] = None
_install_lock = asyncio.Lock()


def cf_cli_path() -> Optional[Path]:
    """Sync getter for the project-local binary — the already-installed
    shim, without installing. ``None`` when never installed."""
    global _cached_path
    if _cached_path and _cached_path.exists():
        return _cached_path
    target = _shared_tree_bin()
    if target.exists():
        _cached_path = target
        return target
    return None


def _shared_tree_bin() -> Path:
    return shared_tree_bin("cf")


def _install() -> Path:
    """Blocking ``bun add`` into the shared tree. Raises on failure."""
    bin_path = _shared_tree_bin()
    logger.info("[Cloudflare] installing %s into the shared packages tree", _NPM_SPEC)
    result = add_package(_NPM_SPEC)
    if result.returncode != 0 or not bin_path.exists():
        raise RuntimeError(f"bun add {_NPM_SPEC} failed: {result.stderr.strip()[:500]}")
    logger.info("[Cloudflare] cf CLI installed at %s", bin_path)
    return bin_path


async def ensure_cf_cli() -> Path:
    """Return absolute path to the project-local cf binary, installing
    the pinned release on miss. Idempotent + concurrent-safe."""
    global _cached_path
    if _cached_path and _cached_path.exists():
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
        return installed


__all__ = ["cf_cli_path", "ensure_cf_cli"]
