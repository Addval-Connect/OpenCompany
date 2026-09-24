"""What one tool result may add to an agent's conversation.

``services.tool_output`` is shared by the in-process loop and the Temporal
``AgentWorkflow``. The incident behind it (docs-internal/errors.md, entry 28):
single TikHub results of about 400,000 characters grew a saved conversation
past the 1 MB seed cap, and every later firing failed to load it.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.tool_output import (
    bound_tool_output,
    resolve_tool_output_limit,
    tool_output_is_capped,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestBoundToolOutput:
    def test_short_result_is_unchanged(self):
        assert bound_tool_output("abc", 10) == "abc"

    @pytest.mark.parametrize("limit", [0, None, -1])
    def test_no_limit_keeps_the_whole_result(self, limit):
        text = "x" * 500
        assert bound_tool_output(text, limit) == text

    def test_long_result_keeps_the_head_and_says_what_was_cut(self):
        text = "a" * 150_000 + "TAIL"

        bounded = bound_tool_output(text, 100_000)

        assert bounded.startswith("a" * 100_000)
        assert "TAIL" not in bounded
        assert "showing the first 100,000 of 150,004 characters" in bounded
        assert "Call the tool again with narrower parameters" in bounded

    def test_the_note_makes_no_promise_about_an_output_panel(self):
        """Several capped tools hide their Output section, and the panel
        only ever shows a tool's latest call."""
        bounded = bound_tool_output("z" * 50, 10)

        assert "panel" not in bounded

    def test_a_tighter_second_cut_keeps_the_original_total(self):
        once = bound_tool_output("b" * 400_000, 100_000)

        twice = bound_tool_output(once, 20_000)

        assert twice.startswith("b" * 20_000)
        assert "showing the first 20,000 of 400,000 characters" in twice
        assert twice.count("[Tool result truncated") == 1

    def test_a_looser_second_cut_is_a_no_op(self):
        once = bound_tool_output("c" * 50_000, 10_000)

        assert bound_tool_output(once, 10_000) == once
        assert bound_tool_output(once, 20_000) == once


class TestExemptions:
    @pytest.mark.parametrize(
        "node_type",
        ["tikhubAction", "httpRequest", "simpleMemory", "dataSource", "", None],
    )
    def test_external_and_unknown_tools_are_capped(self, node_type):
        assert tool_output_is_capped(node_type) is True

    @pytest.mark.parametrize(
        "node_type",
        [
            "_builtin_skill",
            "_builtin_check_delegated_tasks",
            "taskManager",
            "aiAgent",
            "orchestrator_agent",
            "claude_code_agent",
            "rlm_agent",
        ],
    )
    def test_agent_internal_channels_are_never_cut(self, node_type):
        assert tool_output_is_capped(node_type) is False

    def test_every_agent_type_is_exempt(self):
        from constants import AI_AGENT_TYPES

        assert not any(tool_output_is_capped(kind) for kind in AI_AGENT_TYPES)


class TestResolveLimit:
    def test_the_user_setting_wins(self):
        settings = SimpleNamespace(tool_result_max_chars=100_000)

        limit = resolve_tool_output_limit(
            {"tool_result_max_chars": 30_000}, settings
        )

        assert limit == 30_000

    def test_the_env_setting_applies_without_a_user_row(self):
        settings = SimpleNamespace(tool_result_max_chars=100_000)

        assert resolve_tool_output_limit(None, settings) == 100_000

    @pytest.mark.parametrize("raw", [0, -5, True, "50000", None, 2.5])
    def test_only_a_positive_integer_overrides_the_env_value(self, raw):
        settings = SimpleNamespace(tool_result_max_chars=100_000)

        limit = resolve_tool_output_limit(
            {"tool_result_max_chars": raw}, settings
        )

        assert limit == 100_000

    def test_a_zero_env_value_disables_the_cap(self):
        settings = SimpleNamespace(tool_result_max_chars=0)

        assert resolve_tool_output_limit({}, settings) == 0

    def test_settings_without_the_field_disable_the_cap(self):
        """The AIService tests construct it with ``settings=object()``."""
        assert resolve_tool_output_limit(None, object()) == 0


class TestDefaultParity:
    """The default is written in four places and two languages.

    ``.env.template`` is canonical; ``Settings`` mirrors it for bare
    construction, ``UserSettings`` for new rows (and the migration derives
    the column default from it), and the client schema for the Settings
    slider. They cannot share a constant, so this test keeps them equal.
    """

    def test_every_copy_of_the_default_agrees(self):
        from models.database import UserSettings

        template = (REPO_ROOT / ".env.template").read_text(encoding="utf-8")
        config = (REPO_ROOT / "server" / "core" / "config.py").read_text(
            encoding="utf-8"
        )
        schema = (
            REPO_ROOT
            / "client"
            / "src"
            / "components"
            / "ui"
            / "settingsPanel"
            / "schema.ts"
        ).read_text(encoding="utf-8")

        env_match = re.search(r"^TOOL_RESULT_MAX_CHARS=(\d+)\s*$", template, re.M)
        config_match = re.search(
            r"tool_result_max_chars: int = Field\(default=([\d_]+), "
            r'env="TOOL_RESULT_MAX_CHARS"',
            config,
        )
        schema_match = re.search(
            r"toolResultMaxChars: z[^,]*?\.default\(([\d_]+)\)", schema, re.S
        )
        assert env_match and config_match and schema_match, (
            "Could not find a copy of the TOOL_RESULT_MAX_CHARS default. If "
            "one moved, update this extraction; the invariant still holds."
        )

        copies = {
            ".env.template": int(env_match.group(1)),
            "Settings": int(config_match.group(1).replace("_", "")),
            "UserSettings": int(
                UserSettings.model_fields["tool_result_max_chars"].default
            ),
            "client schema": int(schema_match.group(1).replace("_", "")),
        }
        assert len(set(copies.values())) == 1, copies
