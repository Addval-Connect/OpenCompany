"""Transcript-pressure rules for ``AgentWorkflow`` (pure functions).

These rules are recorded behavior: ``context_pressure_version`` in a run's
prepare-payload result selects them on replay, so a change here needs a new
version (see the module docstring).

Sizes below are chosen against the wire format: a tool message stores its
text twice (``content`` and the ``tool_result`` block), so a result of N
characters costs about 2N bytes.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from services.llm.protocol import (
    Message,
    ToolCall,
    message_from_wire,
    message_to_wire,
)
from services.temporal.agent_context_pressure import (
    CHARS_PER_TOKEN,
    CLEARED_TOOL_RESULT,
    MIN_CLIPPED_RESULT_CHARS,
    clear_old_tool_results,
    clip_latest_turn,
    earlier_turns_over_budget,
    has_summarizable_history,
    projected_request_tokens,
    request_tokens,
    summarizer_view,
    transcript_budget_bytes,
    transcript_bytes,
    turn_tool_chars,
)

pytestmark = pytest.mark.unit

EXTERNAL = {"scrape", "search"}


def _is_capped(name):
    return name in EXTERNAL


def _wire(**kwargs) -> Dict[str, Any]:
    return dict(message_to_wire(Message(**kwargs)))


def _assistant(*call_ids: str, tool: str = "scrape") -> Dict[str, Any]:
    return _wire(
        role="assistant",
        tool_calls=[
            ToolCall(id=call_id, name=tool, args={"q": call_id})
            for call_id in call_ids
        ],
    )


def _result(call_id: str, tool: str, size: int) -> Dict[str, Any]:
    return _wire(
        role="tool",
        content="r" * size,
        tool_call_id=call_id,
        name=tool,
    )


def _opening(user_chars: int = 0) -> List[Dict[str, Any]]:
    return [
        _wire(role="system", content="You are useful."),
        _wire(role="user", content="h" * user_chars or "Research this."),
    ]


def _turns(*turns) -> List[Dict[str, Any]]:
    """The opening plus one (assistant, result) pair per ``(tool, size)``."""
    messages = _opening()
    for index, (tool, size) in enumerate(turns, start=1):
        messages.append(_assistant(f"call-{index}", tool=tool))
        messages.append(_result(f"call-{index}", tool, size))
    return messages


def _one_turn(*sizes, tool: str = "scrape", user_chars: int = 0):
    """The opening plus ONE turn that called ``tool`` once per size."""
    call_ids = [f"call-{index}" for index, _ in enumerate(sizes, start=1)]
    messages = _opening(user_chars)
    messages.append(_assistant(*call_ids, tool=tool))
    for call_id, size in zip(call_ids, sizes):
        messages.append(_result(call_id, tool, size))
    return messages


def _kept(message: Dict[str, Any]) -> str:
    return message["content"].split("\n\n[Tool result truncated")[0]


class TestBudget:
    def test_budget_is_three_quarters_of_temporal_payload_warning(self):
        from services.media.limits import TEMPORAL_PAYLOAD_WARN_BYTES

        assert transcript_budget_bytes() == TEMPORAL_PAYLOAD_WARN_BYTES * 3 // 4

    def test_transcript_bytes_matches_the_rollover_guard(self):
        messages = _turns(("scrape", 100))

        assert transcript_bytes(messages) == len(
            json.dumps(messages, default=str).encode("utf-8")
        )


class TestClearOldToolResults:
    def test_under_budget_nothing_changes(self):
        messages = _turns(("scrape", 1_000))
        before = [dict(message) for message in messages]

        relief = clear_old_tool_results(
            messages,
            turn_start=len(messages) - 2,
            budget_bytes=1_000_000,
            is_capped=_is_capped,
        )

        assert messages == before
        assert relief.changed == 0
        assert relief.bytes_before == relief.bytes_after

    def test_oldest_results_go_first_and_the_latest_turn_is_kept(self):
        messages = _turns(("scrape", 20_000), ("scrape", 20_000), ("scrape", 20_000))

        relief = clear_old_tool_results(
            messages,
            turn_start=len(messages) - 2,
            budget_bytes=100_000,
            is_capped=_is_capped,
        )

        # Half the budget takes both earlier results; the latest turn stays.
        assert relief.changed == 2
        assert messages[3]["content"] == CLEARED_TOOL_RESULT
        assert messages[5]["content"] == CLEARED_TOOL_RESULT
        assert messages[7]["content"] == "r" * 20_000
        assert relief.bytes_after <= 50_000
        assert relief.bytes_after == transcript_bytes(messages)

    def test_clearing_stops_at_half_the_budget(self):
        messages = _turns(("scrape", 60_000), ("scrape", 10_000), ("scrape", 1_000))

        relief = clear_old_tool_results(
            messages,
            turn_start=len(messages) - 2,
            budget_bytes=100_000,
            is_capped=_is_capped,
        )

        assert relief.changed == 1
        assert messages[3]["content"] == CLEARED_TOOL_RESULT
        assert messages[5]["content"] == "r" * 10_000

    def test_external_results_are_cleared_before_internal_ones(self):
        messages = _turns(("load_skill", 10_000), ("scrape", 60_000), ("scrape", 100))

        clear_old_tool_results(
            messages,
            turn_start=len(messages) - 2,
            budget_bytes=100_000,
            is_capped=_is_capped,
        )

        assert messages[3]["content"] == "r" * 10_000  # internal, and older
        assert messages[5]["content"] == CLEARED_TOOL_RESULT  # external

    def test_internal_results_go_when_external_ones_are_not_enough(self):
        messages = _turns(("load_skill", 60_000), ("scrape", 1_000), ("scrape", 100))

        relief = clear_old_tool_results(
            messages,
            turn_start=len(messages) - 2,
            budget_bytes=100_000,
            is_capped=_is_capped,
        )

        assert relief.changed == 2
        assert messages[3]["content"] == CLEARED_TOOL_RESULT

    def test_a_cleared_result_still_answers_its_call(self):
        messages = _turns(("scrape", 60_000), ("scrape", 100))

        clear_old_tool_results(
            messages,
            turn_start=len(messages) - 2,
            budget_bytes=100_000,
            is_capped=_is_capped,
        )

        cleared = messages[3]
        assert cleared["role"] == "tool"
        assert cleared["tool_call_id"] == "call-1"
        assert cleared["name"] == "scrape"
        # The duplicated tool_result block is rebuilt too, so the old text
        # is really gone from the wire.
        assert [block["text"] for block in cleared["blocks"]] == [
            CLEARED_TOOL_RESULT
        ]
        assert message_from_wire(cleared).content == CLEARED_TOOL_RESULT

    def test_counts_the_characters_it_removed(self):
        messages = _turns(("scrape", 60_000), ("scrape", 100))

        relief = clear_old_tool_results(
            messages,
            turn_start=len(messages) - 2,
            budget_bytes=100_000,
            is_capped=_is_capped,
        )

        assert relief.chars_removed == 60_000 - len(CLEARED_TOOL_RESULT)

    def test_already_cleared_results_are_left_alone(self):
        messages = _turns(("scrape", 60_000), ("scrape", 100))
        clear_old_tool_results(
            messages,
            turn_start=len(messages) - 2,
            budget_bytes=100_000,
            is_capped=_is_capped,
        )
        after_first = [dict(message) for message in messages]

        relief = clear_old_tool_results(
            messages,
            turn_start=len(messages) - 2,
            budget_bytes=1_000,
            is_capped=_is_capped,
        )

        assert relief.changed == 0
        assert messages == after_first

    def test_a_zero_budget_disables_clearing(self):
        messages = _turns(("scrape", 60_000), ("scrape", 100))

        relief = clear_old_tool_results(
            messages,
            turn_start=len(messages) - 2,
            budget_bytes=0,
            is_capped=_is_capped,
        )

        assert relief.changed == 0


class TestEarlierTurnsOverBudget:
    def test_false_within_budget(self):
        messages = _one_turn(1_000, user_chars=80_000)

        assert (
            earlier_turns_over_budget(
                messages,
                turn_start=2,
                budget_bytes=1_000_000,
                size=transcript_bytes(messages),
            )
            is False
        )

    def test_true_when_earlier_turns_hold_more_than_half(self):
        messages = _one_turn(1_000, user_chars=80_000)

        assert (
            earlier_turns_over_budget(
                messages,
                turn_start=2,
                budget_bytes=70_000,
                size=transcript_bytes(messages),
            )
            is True
        )

    def test_false_when_the_latest_turn_is_the_excess(self):
        messages = _one_turn(80_000)

        assert (
            earlier_turns_over_budget(
                messages,
                turn_start=2,
                budget_bytes=70_000,
                size=transcript_bytes(messages),
            )
            is False
        )


class TestClipLatestTurn:
    def test_under_budget_nothing_changes(self):
        messages = _one_turn(1_000, 1_000)
        before = [dict(message) for message in messages]

        relief = clip_latest_turn(
            messages,
            turn_start=2,
            budget_bytes=1_000_000,
            is_capped=_is_capped,
        )

        assert relief.changed == 0
        assert messages == before

    def test_several_large_results_are_cut_to_one_length_that_fits(self):
        messages = _one_turn(100_000, 100_000, 100_000, 100_000)

        relief = clip_latest_turn(
            messages,
            turn_start=2,
            budget_bytes=393_216,
            is_capped=_is_capped,
        )

        assert relief.changed == 4
        assert relief.bytes_after <= 393_216
        assert relief.bytes_after == transcript_bytes(messages)
        assert len({len(_kept(message)) for message in messages[3:]}) == 1
        assert all(
            "of 100,000 characters" in message["content"]
            for message in messages[3:]
        )

    def test_short_results_stay_whole_and_free_their_share(self):
        messages = _one_turn(1_000, 200_000, 200_000)

        clip_latest_turn(
            messages,
            turn_start=2,
            budget_bytes=393_216,
            is_capped=_is_capped,
        )

        assert messages[3]["content"] == "r" * 1_000
        assert "Tool result truncated" in messages[4]["content"]
        assert len(_kept(messages[4])) > 90_000

    def test_internal_results_are_never_cut(self):
        messages = _one_turn(300_000, 300_000, tool="load_skill")

        relief = clip_latest_turn(
            messages,
            turn_start=2,
            budget_bytes=393_216,
            is_capped=_is_capped,
        )

        assert relief.changed == 0
        assert all(
            message["content"] == "r" * 300_000 for message in messages[3:]
        )

    def test_earlier_turns_are_left_to_clearing(self):
        messages = _turns(("scrape", 100_000), ("scrape", 100_000))

        clip_latest_turn(
            messages,
            turn_start=4,
            budget_bytes=250_000,
            is_capped=_is_capped,
        )

        assert messages[3]["content"] == "r" * 100_000
        assert "Tool result truncated" in messages[5]["content"]

    def test_never_cut_below_the_minimum_length(self):
        # The earlier turns alone overflow the budget, so nothing this turn
        # does can fit; each result still keeps the minimum.
        messages = _one_turn(50_000, 50_000, user_chars=400_000)

        relief = clip_latest_turn(
            messages,
            turn_start=2,
            budget_bytes=310_000,
            is_capped=_is_capped,
        )

        assert relief.bytes_after > 310_000
        assert all(
            len(_kept(message)) == MIN_CLIPPED_RESULT_CHARS
            for message in messages[3:]
        )


class TestTokenArithmetic:
    def test_request_tokens_is_the_step_total(self):
        usage = {
            "input_tokens": 1_000,
            "output_tokens": 200,
            "cache_read_tokens": 50_000,
            "total_tokens": 51_200,
        }

        assert request_tokens(usage) == 51_200

    def test_cache_counters_are_never_added_on_top_of_input(self):
        """OpenAI and Gemini already count cached tokens inside input."""
        usage = {
            "input_tokens": 60_000,
            "output_tokens": 500,
            "cache_read_tokens": 50_000,
            "total_tokens": 60_500,
        }

        assert request_tokens(usage) == 60_500

    def test_request_tokens_falls_back_to_input_plus_output(self):
        assert request_tokens({"input_tokens": 7, "output_tokens": 3}) == 10
        assert request_tokens(None) == 0
        assert request_tokens({"total_tokens": True}) == 0

    def test_projection_adds_the_turn_and_subtracts_what_was_cleared(self):
        usage = {"total_tokens": 1_000}

        assert projected_request_tokens(usage, 4_000) == 1_000 + 4_000 // CHARS_PER_TOKEN
        assert projected_request_tokens(usage, -2_000) == 1_000 - 2_000 // CHARS_PER_TOKEN
        assert projected_request_tokens({}, -10_000) == 0

    def test_turn_tool_chars_counts_only_the_latest_turn(self):
        messages = _turns(("scrape", 5_000), ("scrape", 700))

        assert turn_tool_chars(messages, len(messages) - 2) == 700


class TestSummarization:
    def test_a_run_before_its_first_turn_has_nothing_to_summarize(self):
        messages = _turns(("scrape", 100))

        assert has_summarizable_history(messages, 2) is False

    def test_an_earlier_turn_can_be_summarized(self):
        messages = _turns(("scrape", 100), ("scrape", 100))

        assert has_summarizable_history(messages, 4) is True

    def test_a_previous_summary_alone_is_not_summarized_again(self):
        messages = [
            _wire(role="system", content="You are useful."),
            _wire(role="user", content="## Compacted conversation summary\n..."),
            _assistant("call-9"),
            _result("call-9", "scrape", 100),
        ]

        assert has_summarizable_history(messages, 2) is False

    def test_summarizer_view_keeps_only_what_the_activity_renders(self):
        messages = _turns(("scrape", 100))
        messages[2]["provider_state"] = {"provider": "gemini", "payload": {}}

        view = summarizer_view(messages)

        for original, trimmed in zip(messages, view):
            assert "blocks" not in trimmed
            assert "provider_state" not in trimmed
            decoded = message_from_wire(trimmed)
            assert decoded.role == original["role"]
            assert decoded.content == original["content"]
        assert message_from_wire(view[2]).tool_calls[0].name == "scrape"
        assert message_from_wire(view[3]).tool_call_id == "call-1"
