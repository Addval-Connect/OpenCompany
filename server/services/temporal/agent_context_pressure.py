"""Transcript-pressure relief for ``AgentWorkflow`` (pure, workflow-safe).

Every function here is a pure computation over MessageWire dicts: no I/O, no
clock, no randomness. ``AgentWorkflow`` calls them from workflow code, and a
replay gets the same answer.

Why this exists (docs-internal/errors.md, entry 28): each tool result is
appended to the agent's transcript and re-sent on every later turn. The
transcript is the ``agent.execute_llm_step`` input and, after each turn, the
saved conversation, so an unbounded one first draws Temporal payload
warnings, then payload errors, and finally fails the next firing at the 1 MB
seed cap. After each tool turn the workflow applies, in order:

1. :func:`clear_old_tool_results`: past the byte budget, results from earlier
   turns are replaced by a short placeholder, oldest first and external tools
   before agent-internal ones, until the transcript is at half the budget.
   Each keeps its ``tool_call_id`` and ``name``, so every tool call still has
   its answer. The latest turn is never cleared: the model has not read it.
2. Summarization, when the next request (:func:`projected_request_tokens`)
   reaches the compaction threshold, or when the transcript is still over
   budget because of what the earlier turns hold. Only the turns before the
   latest one are summarized.
3. :func:`clip_latest_turn`: if the latest turn alone still does not fit, its
   external results are cut to one shared length.

Replay contract: ``agent.prepare_payload`` records ``context_pressure_version``
in the run's history, and the recorded value selects this code path. These
rules decide whether ``agent.compact_context`` is scheduled, so any change to
the clearing order, the placeholder, the targets or the token arithmetic must
ship under a new version number, with the previous rules kept for runs that
recorded the old one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from services.tool_output import bound_tool_output

CONTEXT_PRESSURE_VERSION = 1

# Rough characters per token for text that has not been through a tokenizer
# yet (the same estimate ``skill_runtime`` reports for skill loads).
CHARS_PER_TOKEN = 4

CLEARED_TOOL_RESULT = (
    "[Earlier tool result cleared to keep this conversation within its size "
    "budget. Call the tool again if you still need it.]"
)

# Shortest length a latest-turn result is cut to. Below it the model gets too
# little to act on; the result is kept at this length even if the transcript
# then stays over budget.
MIN_CLIPPED_RESULT_CHARS = 2_000


def transcript_budget_bytes() -> int:
    """Byte budget for a transcript, recorded by ``agent.prepare_payload``.

    The transcript rides every ``agent.execute_llm_step`` input next to the
    tool definitions and a second copy of the system prompt, so it gets three
    quarters of the size at which Temporal starts warning about a payload.
    Imported lazily: ``services.media`` loads its whole package on import,
    which workflow code does not need.
    """
    from services.media.limits import TEMPORAL_PAYLOAD_WARN_BYTES

    return TEMPORAL_PAYLOAD_WARN_BYTES * 3 // 4


def transcript_bytes(messages: Sequence[Any]) -> int:
    """Serialized size, measured the way the rollover guard measures it."""
    return len(json.dumps(list(messages), default=str).encode("utf-8"))


@dataclass(frozen=True)
class Relief:
    """What one relief step changed."""

    bytes_before: int
    bytes_after: int
    # Tool results cleared or cut.
    changed: int = 0
    # Content characters removed, net of placeholders and notes.
    chars_removed: int = 0


def clear_old_tool_results(
    messages: List[Dict[str, Any]],
    *,
    turn_start: int,
    budget_bytes: int,
    is_capped: Callable[[Optional[str]], bool],
) -> Relief:
    """Clear results from turns before ``turn_start`` once over the budget.

    Replaces entries of ``messages`` in place. ``turn_start`` is the index of
    the latest turn's assistant message; that message and the results after
    it are left alone. ``is_capped`` maps a tool message's ``name`` to
    whether the tool is external. Clears down to half the budget, because
    every clear changes the prompt the provider has cached, so one larger
    clear beats a small one every turn.
    """
    size = transcript_bytes(messages)
    before = size
    if not budget_bytes or size <= budget_bytes:
        return Relief(bytes_before=before, bytes_after=size)

    target = budget_bytes // 2
    boundary = max(0, min(turn_start, len(messages)))
    changed = 0
    removed = 0
    for external in (True, False):
        for index in range(boundary):
            if size <= target:
                break
            message = messages[index]
            if not _is_tool_result(message):
                continue
            if bool(is_capped(message.get("name"))) is not external:
                continue
            content = _content(message)
            if content == CLEARED_TOOL_RESULT:
                continue
            replacement = _with_content(message, CLEARED_TOOL_RESULT)
            saved = _item_bytes(message) - _item_bytes(replacement)
            if saved <= 0:
                continue
            messages[index] = replacement
            size -= saved
            changed += 1
            removed += len(content) - len(CLEARED_TOOL_RESULT)
    return Relief(
        bytes_before=before,
        bytes_after=size,
        changed=changed,
        chars_removed=removed,
    )


def earlier_turns_over_budget(
    messages: Sequence[Any],
    *,
    turn_start: int,
    budget_bytes: int,
    size: int,
) -> bool:
    """Whether the earlier turns, not the latest one, keep ``messages`` over budget.

    ``size`` is the transcript's size after :func:`clear_old_tool_results`.
    Still over the budget with the turns before ``turn_start`` holding more
    than half of it, the transcript carries text that only a summary can
    shrink. Otherwise the latest turn is the excess, and
    :func:`clip_latest_turn` handles it without a summarizer call.
    """
    if not budget_bytes or size <= budget_bytes:
        return False
    return transcript_bytes(messages[: max(0, turn_start)]) > budget_bytes // 2


def clip_latest_turn(
    messages: List[Dict[str, Any]],
    *,
    turn_start: int,
    budget_bytes: int,
    is_capped: Callable[[Optional[str]], bool],
) -> Relief:
    """Cut the latest turn's external results to one shared length that fits.

    For when earlier turns are already as small as clearing and summarizing
    can make them. Results shorter than the shared length stay whole, and
    none is cut below ``MIN_CLIPPED_RESULT_CHARS``. The length is found by
    bisection on the exact serialized size, so the note each cut appends and
    the repeated ``tool_result`` block are accounted for.
    """
    size = transcript_bytes(messages)
    before = size
    if not budget_bytes or size <= budget_bytes:
        return Relief(bytes_before=before, bytes_after=size)
    turn = {
        index: messages[index]
        for index in range(max(0, turn_start), len(messages))
        if _is_tool_result(messages[index])
        and is_capped(messages[index].get("name"))
    }
    if not turn:
        return Relief(bytes_before=before, bytes_after=size)
    others = size - sum(_item_bytes(message) for message in turn.values())

    def cut(share: int) -> Dict[int, Dict[str, Any]]:
        return {index: _bounded(message, share) for index, message in turn.items()}

    def size_at(share: int) -> int:
        return others + sum(_item_bytes(message) for message in cut(share).values())

    low = MIN_CLIPPED_RESULT_CHARS
    high = max(len(_content(message)) for message in turn.values())
    if high <= low:
        return Relief(bytes_before=before, bytes_after=size)
    if size_at(low) <= budget_bytes:
        while low < high:
            middle = (low + high + 1) // 2
            if size_at(middle) <= budget_bytes:
                low = middle
            else:
                high = middle - 1

    changed = 0
    removed = 0
    for index, replacement in cut(low).items():
        original = turn[index]
        if replacement is original:
            continue
        messages[index] = replacement
        changed += 1
        removed += len(_content(original)) - len(_content(replacement))
    return Relief(
        bytes_before=before,
        bytes_after=transcript_bytes(messages),
        changed=changed,
        chars_removed=removed,
    )


def request_tokens(usage: Optional[Mapping[str, Any]]) -> int:
    """Tokens in the request that produced ``usage``, plus its reply.

    Every provider fills ``total_tokens`` with the whole prompt, prompt-cache
    reads and writes included, plus the output. Never add the cache counters
    to ``input_tokens``: OpenAI and Gemini already count cached tokens inside
    it, while Anthropic does not.
    """
    usage = usage or {}
    return max(
        _int(usage.get("total_tokens")),
        _int(usage.get("input_tokens")) + _int(usage.get("output_tokens")),
    )


def projected_request_tokens(
    usage: Optional[Mapping[str, Any]],
    added_chars: int,
) -> int:
    """Estimated size of the next request.

    The last request and its reply, plus the characters this turn added to
    the transcript, net of what relief removed, at ``CHARS_PER_TOKEN``.
    """
    return max(0, request_tokens(usage) + added_chars // CHARS_PER_TOKEN)


def turn_tool_chars(messages: Sequence[Any], turn_start: int) -> int:
    """Characters of tool-result content in the latest turn."""
    return sum(
        len(_content(message))
        for message in messages[max(0, turn_start):]
        if _is_tool_result(message)
    )


def has_summarizable_history(messages: Sequence[Any], turn_start: int) -> bool:
    """Whether turns older than the latest one exist to fold into a summary.

    Before its first turn a run holds the system prompt and one user message
    (the request, or an earlier summary carrying it). Summarizing only that
    gains nothing, and a short one is rejected by the summarizer, which fails
    the run.
    """
    return (
        sum(
            1
            for message in messages[: max(0, turn_start)]
            if isinstance(message, Mapping) and message.get("role") != "system"
        )
        > 1
    )


_SUMMARIZER_FIELDS = ("role", "content", "tool_calls", "tool_call_id", "name")


def summarizer_view(messages: Sequence[Any]) -> List[Dict[str, Any]]:
    """The fields ``agent.compact_context`` renders, and nothing more.

    Drops the duplicated content blocks and the provider continuation state,
    which the summarizer never reads but which would double its input.
    """
    return [
        {key: message[key] for key in _SUMMARIZER_FIELDS if key in message}
        for message in messages
        if isinstance(message, Mapping)
    ]


def _is_tool_result(message: Any) -> bool:
    return isinstance(message, Mapping) and message.get("role") == "tool"


def _content(message: Mapping[str, Any]) -> str:
    return str(message.get("content") or "")


def _item_bytes(message: Any) -> int:
    return len(json.dumps(message, default=str).encode("utf-8"))


def _bounded(message: Dict[str, Any], share: int) -> Dict[str, Any]:
    """``message`` itself when it fits ``share``, else a cut copy."""
    content = _content(message)
    bounded = bound_tool_output(content, share)
    return message if bounded == content else _with_content(message, bounded)


def _with_content(message: Mapping[str, Any], content: str) -> Dict[str, Any]:
    """Rebuild a tool result around ``content`` through the wire codec.

    Rebuilding, rather than editing ``content`` alone, regenerates the
    ``tool_result`` block that repeats the text and drops any image blocks,
    so the old payload is really gone.
    """
    from services.llm.protocol import Message, message_to_wire

    return dict(
        message_to_wire(
            Message(
                role="tool",
                content=content,
                tool_call_id=_optional_str(message.get("tool_call_id")),
                name=_optional_str(message.get("name")),
            )
        )
    )


def _optional_str(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
