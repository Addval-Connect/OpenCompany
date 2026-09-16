"""Env accessor backed by the app tree's canonical env files.

The default value for every OpenCompany env var lives in ONE place:
``<app root>/.env.template`` (overridden by ``<app root>/.env``, overridden
by the process environment — the same precedence ``cli.config.load_config``
uses). The CLI pushes that merged view into ``os.environ`` for every
process it spawns; entry points that bypass the CLI (direct ``uvicorn``
runs, the desktop shell, ``python -m services.temporal.worker``, gunicorn,
pytest when a code path is actually exercised) resolve through this helper
instead of carrying fallback literals in code.

:func:`apply_file_defaults_to_environ` is the process-wide form of the same
layering: ``main.py`` calls it before ``Settings()`` so every
``os.environ.get(...)`` in a plugin sees the template defaults, exactly as
it would under the CLI. That is what lets the desktop shell spawn
``python -m uvicorn`` directly without the CLI package.

File locations come from :mod:`core.approot` (``OPENCOMPANY_APP_ROOT`` /
``OPENCOMPANY_ENV_FILE`` / ``OPENCOMPANY_ENV_TEMPLATE`` overrides).

Stdlib-only and dependency-free so it is importable from anywhere
(gunicorn config, plugin folders, the stubbed-core test environment).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from core.approot import env_file_path, env_template_path


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser — mirrors ``cli.config._load_env_file``
    semantics (skip blanks/comments, first ``=`` splits, strip one pair of
    matching surrounding quotes)."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


@lru_cache(maxsize=1)
def _file_defaults() -> dict[str, str]:
    merged = _parse_env_file(env_template_path())
    merged.update(_parse_env_file(env_file_path()))
    return merged


def reset_cache() -> None:
    """Forget the parsed env files (tests that swap ``OPENCOMPANY_*`` paths)."""
    _file_defaults.cache_clear()


def apply_file_defaults_to_environ() -> dict[str, str]:
    """Push ``.env.template`` < ``.env`` into ``os.environ`` without
    overwriting anything already set (python-dotenv ``override=False``
    semantics, identical to ``cli.config.load_config``).

    Returns the merged file view for callers that want to log it.
    """
    merged = _file_defaults()
    for key, value in merged.items():
        os.environ.setdefault(key, value)
    return dict(merged)


def env_value(key: str) -> str:
    """Resolve ``key`` from the process env, then ``.env`` / ``.env.template``.

    Raises ``RuntimeError`` with a pointer to the canonical file when the
    key is configured nowhere — a loud failure instead of a silent
    hardcoded fallback.
    """
    value = os.environ.get(key) or _file_defaults().get(key)
    if not value:
        raise RuntimeError(
            f"{key} is not configured. Set it in the environment or .env; "
            "canonical defaults live in .env.template."
        )
    return value


def env_int(key: str) -> int:
    return int(env_value(key))
