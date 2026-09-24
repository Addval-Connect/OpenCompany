"""``edgymeow`` (WhatsApp Go bridge) local install — landed in the
shared OpenCompany packages tree at :func:`core.paths.packages_dir`
(``<DATA_DIR>/packages/``).

All OpenCompany-managed npm packages (``edgymeow``,
``@anthropic-ai/claude-code``, ``agent-browser``, ``cf``, ``vercel``)
share a single ``<packages_dir>/node_modules/`` managed by bun through
one ``package.json`` + ``bun.lock``. :func:`core.js_runtime.add_package`
(``bun add --cwd <packages_dir> <spec>``) extends the shared tree
idempotently; no Node or npm is involved.

edgymeow is the one package whose postinstall matters: it downloads the
platform's Go binary into ``node_modules/edgymeow/bin/``. bun blocks
dependency lifecycle scripts by default, so this install passes
``trust=True`` (bun's ``--trust``), which also records the package in
the tree's ``trustedDependencies``.

Pre-fix this lived as a top-level ``edgymeow`` dep in the root
``package.json`` and landed at ``<repo>/node_modules/edgymeow/`` via
``pnpm install``. Operators had to re-run ``pnpm install`` after
``company clean`` to recover. After this move, the WhatsApp binary
follows the same on-demand install pattern as every other
OpenCompany-managed CLI.
"""

from __future__ import annotations

import sys
from typing import Optional

from core.js_runtime import add_package, bun_binary
from core.logging import get_logger
from core.paths import packages_dir

logger = get_logger(__name__)

# Pinned for reproducible WhatsApp Go-bridge ABI. Bump when the
# bridge's WebSocket / event schema changes.
_NPM_SPEC = "edgymeow@0.0.20"


def edgymeow_binary_path() -> Optional[str]:
    """Return path to the edgymeow Go binary, installing on miss.

    Returns ``None`` if bun is not available or the install failed —
    callers should surface this as a user-visible error (the runtime
    can't spawn without it). Idempotent: subsequent calls hit the
    existing binary on disk.
    """
    root = packages_dir()
    bin_name = "edgymeow-server.exe" if sys.platform == "win32" else "edgymeow-server"
    bin_path = root / "node_modules" / "edgymeow" / "bin" / bin_name

    if bin_path.exists():
        return str(bin_path)

    if bun_binary() is None:
        logger.warning("[whatsapp] bun not available; cannot install %s", _NPM_SPEC)
        return None

    logger.info("[whatsapp] installing %s into the shared packages tree %s", _NPM_SPEC, root)
    result = add_package(_NPM_SPEC, trust=True)
    if result.returncode != 0 or not bin_path.exists():
        logger.error("[whatsapp] bun add %s failed: %s", _NPM_SPEC, result.stderr.strip())
        return None

    logger.info("[whatsapp] edgymeow installed at %s", bin_path)
    return str(bin_path)


__all__ = ["edgymeow_binary_path"]
