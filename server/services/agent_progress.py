"""Shared no-progress guard for agent tool loops.

Both agent loops (the in-process ``run_native_agent_loop`` and the Temporal
``AgentWorkflow``) feed malformed tool calls back to the model so it can repair
them.  That is the right behaviour for an occasional mistake, but it becomes a
deterministic loop when the provider keeps truncating the same long generation:
the model sees "invalid JSON", retries the identical call, and the provider
cuts it at the same deadline again.

This guard is model- and provider-agnostic.  It observes each tool turn and
reports when the loop is no longer making progress:

* ``identical_tool_call`` — the same unusable ``(tool, raw_arguments)`` was
  emitted N times.  This is the signature of a deterministic truncation.
* ``consecutive_unusable_steps`` — N turns in a row produced no executable
  tool call (only malformed/unknown calls).

A turn with at least one executable call resets both counters: a model that
recovers must not be punished for earlier bad turns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Tuple

DEFAULT_MAX_CONSECUTIVE_UNUSABLE_STEPS = 3
DEFAULT_MAX_IDENTICAL_UNUSABLE_STEPS = 2

REASON_IDENTICAL = "identical_tool_call"
REASON_CONSECUTIVE = "consecutive_unusable_steps"


@dataclass
class NoProgressGuard:
    """Track unusable tool turns and decide when to stop the loop."""

    max_consecutive: int = DEFAULT_MAX_CONSECUTIVE_UNUSABLE_STEPS
    max_identical: int = DEFAULT_MAX_IDENTICAL_UNUSABLE_STEPS
    consecutive: int = 0
    identical: Dict[Tuple[str, str], int] = field(default_factory=dict)

    def observe(
        self,
        *,
        failures: Sequence[Tuple[str, str]],
        executable: bool,
    ) -> Optional[str]:
        """Record one tool turn and return a stop reason when it is hostile.

        ``failures`` carries ``(tool_name, raw_arguments)`` for every call the
        loop could not hand to a tool.  ``executable`` is true when at least
        one call in the same turn reached a tool (even if that tool then
        returned a domain error).
        """

        if executable:
            self.consecutive = 0
            self.identical.clear()
            return None

        self.consecutive += 1
        for name, raw in failures:
            raw = str(raw or "")
            if not raw:
                # Unknown tool names have no argument signature to match;
                # they still count toward the consecutive guard.
                continue
            key = (str(name or ""), raw)
            self.identical[key] = self.identical.get(key, 0) + 1
            if self.identical[key] >= self.max_identical:
                return REASON_IDENTICAL

        if self.consecutive >= self.max_consecutive:
            return REASON_CONSECUTIVE
        return None

    def message(self, reason: str) -> str:
        """Return the terminal assistant message for a stop reason."""

        if reason == REASON_IDENTICAL:
            detail = (
                "the model repeated the same unusable tool call "
                f"{self.max_identical} times"
            )
        else:
            detail = (
                "the model returned unusable tool calls for "
                f"{self.consecutive} consecutive steps"
            )
        return (
            f"[Agent stopped: {detail}; nothing from those calls was "
            "executed. The provider may be truncating long responses. "
            "Retry the turn, or use a model that can complete the request "
            "within the provider's limit.]"
        )


__all__ = [
    "DEFAULT_MAX_CONSECUTIVE_UNUSABLE_STEPS",
    "DEFAULT_MAX_IDENTICAL_UNUSABLE_STEPS",
    "NoProgressGuard",
    "REASON_CONSECUTIVE",
    "REASON_IDENTICAL",
]
