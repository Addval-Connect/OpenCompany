"""``agent-browser`` local install — landed in the shared OpenCompany
packages tree at :func:`core.paths.packages_dir` (``<DATA_DIR>/packages/``).

All OpenCompany-managed npm packages (``agent-browser``,
``@anthropic-ai/claude-code``, ``edgymeow``, ``cf``, ``vercel``) live
under a single ``<packages_dir>/node_modules/`` managed by bun through
one ``package.json`` + ``bun.lock`` rather than us carving out
per-service install trees. :func:`core.js_runtime.add_package`
(``bun add --cwd <packages_dir> <spec>``) extends the shared tree
idempotently and the bin shim runs on the bun runtime; no Node or npm
is involved. agent-browser's postinstall is trusted so its platform
binary lands the way the package expects.
"""

from __future__ import annotations

import subprocess
from typing import Optional

from core.js_runtime import add_package, bun_binary, shared_tree_bin
from core.logging import get_logger

logger = get_logger(__name__)

_NPM_SPEC = "agent-browser@latest"


def agent_browser_binary_path() -> Optional[str]:
    """Return path to the agent-browser CLI, installing on miss."""
    bin_path = shared_tree_bin("agent-browser")

    if bin_path.exists():
        return str(bin_path)

    if bun_binary() is None:
        logger.warning("[browser] bun not available; cannot install %s", _NPM_SPEC)
        return None

    logger.info("[browser] installing %s into the shared packages tree", _NPM_SPEC)
    result = add_package(_NPM_SPEC, trust=True)
    if result.returncode != 0 or not bin_path.exists():
        logger.error("[browser] bun add %s failed: %s", _NPM_SPEC, result.stderr.strip())
        return None

    # Fetch the Chrome-for-Testing runtime (agent-browser's documented
    # post-install step — downloads ~150MB chromium on first use).
    runtime = subprocess.run(
        [str(bin_path), "install"],
        capture_output=True,
        text=True,
    )
    if runtime.returncode != 0:
        logger.warning("[browser] chromium runtime install failed: %s", runtime.stderr.strip())

    logger.info("[browser] agent-browser installed at %s", bin_path)
    return str(bin_path)


__all__ = ["agent_browser_binary_path"]
