"""``core.env_defaults.apply_file_defaults_to_environ`` — the CLI's env
layering, available to processes the CLI did not spawn.

Precedence (low -> high): ``.env.template`` < ``.env`` < process env, with
``os.environ.setdefault`` so a shell override always wins. Quote handling
must match ``cli.config._load_env_file`` exactly, or the same ``.env`` would
mean two different things depending on who launched the backend.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVER_DIR.parent


@pytest.fixture
def env_files(tmp_path, monkeypatch):
    template = tmp_path / ".env.template"
    user = tmp_path / ".env"
    monkeypatch.setenv("OPENCOMPANY_ENV_TEMPLATE", str(template))
    monkeypatch.setenv("OPENCOMPANY_ENV_FILE", str(user))
    for key in ("OC_T_ONLY", "OC_BOTH", "OC_PROC", "OC_QUOTED", "OC_INNER", "OC_EMPTY"):
        monkeypatch.delenv(key, raising=False)
    import core.env_defaults as mod

    mod = importlib.reload(mod)
    mod.reset_cache()
    return mod, template, user


def test_template_then_user_then_process_env(env_files, monkeypatch):
    mod, template, user = env_files
    template.write_text("OC_T_ONLY=from-template\nOC_BOTH=template\nOC_PROC=template\n", encoding="utf-8")
    user.write_text("OC_BOTH=user\nOC_PROC=user\n", encoding="utf-8")
    monkeypatch.setenv("OC_PROC", "process")

    merged = mod.apply_file_defaults_to_environ()

    assert merged == {"OC_T_ONLY": "from-template", "OC_BOTH": "user", "OC_PROC": "user"}
    import os

    assert os.environ["OC_T_ONLY"] == "from-template"
    assert os.environ["OC_BOTH"] == "user"
    assert os.environ["OC_PROC"] == "process", "process env must win over both files"
    assert mod.env_value("OC_PROC") == "process"


def test_missing_user_file_is_fine(env_files):
    mod, template, user = env_files
    template.write_text("OC_T_ONLY=x\n", encoding="utf-8")
    assert not user.exists()
    assert mod.apply_file_defaults_to_environ() == {"OC_T_ONLY": "x"}


def test_env_value_raises_when_unconfigured(env_files):
    mod, template, _ = env_files
    template.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="OC_T_ONLY is not configured"):
        mod.env_value("OC_T_ONLY")


def _load_cli_env_parser():
    """File-load ``cli/config.py`` for its ``_load_env_file`` without importing
    the CLI package (it pulls ``cli.platform_``)."""
    src = (REPO_ROOT / "cli" / "config.py").read_text(encoding="utf-8")
    ns: dict = {}
    # Extract only the parser function: it depends on Path alone.
    start = src.index("def _load_env_file(")
    end = src.index("\ndef ", start + 1)
    exec("from pathlib import Path\n" + src[start:end], ns)  # noqa: S102 — test-only, repo source
    return ns["_load_env_file"]


@pytest.mark.parametrize(
    "line",
    [
        'OC_QUOTED="double quoted value"',
        "OC_QUOTED='single quoted value'",
        "OC_QUOTED=plain value with spaces",
        'OC_QUOTED="mismatched\'',
        "OC_QUOTED='",
        'OC_QUOTED=""',
        "OC_QUOTED=a=b=c",
        "  OC_QUOTED  =  padded  ",
        'OC_QUOTED=["http://a","http://b"]',
    ],
)
def test_quote_handling_matches_the_cli_parser(env_files, line):
    mod, template, _ = env_files
    template.write_text(line + "\n", encoding="utf-8")
    cli_parse = _load_cli_env_parser()
    assert mod._parse_env_file(template) == cli_parse(template)


def test_comments_and_blank_lines_are_skipped(env_files):
    mod, template, _ = env_files
    template.write_text("# comment\n\nOC_INNER=1\nNOT_A_PAIR\n", encoding="utf-8")
    assert mod._parse_env_file(template) == {"OC_INNER": "1"}
