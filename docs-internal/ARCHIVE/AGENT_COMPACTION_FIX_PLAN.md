# Fix: agent transcripts outgrow compaction and brick the next firing

> **ARCHIVED 2026-09-24 — Shipped** (branch `fix/agent-compaction-pressure`, merged to main). The approved plan plus an as-built record, including where the implementation departed from the plan. Not maintained.
>
> For current state see:
>
> - [agent_context_flow.md → Transcript size](../agent_context_flow.md): the rules and the replay contract.
> - [errors.md entry 28](../errors.md): the incident, the fix, and the one-time recovery for rows saved before it.

## Context

`errors.log` (2026-09-05) records one deployed chat workflow, `AI_Assistant_1`: an `aiAgent` on gemini-3.8-flash with writeTodos, simpleMemory and tikhubAction. Each tikhubAction call appended its whole upstream response (roughly 400,000 characters) to the transcript. The `agent.execute_llm_step` input reached 528 KB at iteration 5 and 1.4 MB from iteration 6 on, with a Temporal `PayloadSizeWarning` every turn. Compaction never fired, because its only trigger is 80% of a 1,048,576-token window, compared with a running sum. The 1.4 MB transcript was saved to `agent_conversations`, and the next chat message failed in `agent.prepare_payload` with non-retryable `ConversationTooLarge` (1,429,978 bytes against a 1,000,000 cap). Every later firing failed the same way until the user cleared the Context panel.

## Decisions

Confirmed by the user 2026-09-09:
1. `ConversationTooLarge` stays a hard, non-retryable failure; the fix prevents new transcripts from reaching it.
2. The tool-result cap is per-user through a Settings slider, with an env fallback.
3. The wire dedupe (every tool message stores its text twice) is deferred to its own change.
4. Compaction's token gate measures the live context, not a cumulative sum.

Approved with the plan on 2026-09-24:
5. **Byte pressure clears the oldest tool results rather than summarizing the turn the model has not read.** Clearing is free, cannot fail, and is the pattern of Anthropic's context editing (`clear_tool_uses`) and Claude Code's micro-compaction. The summarizer keeps the latest turn verbatim.
6. **New behavior is gated on values recorded in the `agent.prepare_payload` result, not on a `workflow.patched` marker.** Histories recorded before the change carry none of the new keys and replay through the original code (the technique `capture_temporal_routing_input` uses to freeze routing flags).
7. **Default cap 100,000 characters, external tools only**, matching the shell and browser output caps. Exempt: delegated agents (`AI_AGENT_TYPES`), `_builtin_skill`, `taskManager`, `_builtin_check_delegated_tasks`.

## Root causes

1. Nothing bounded a tool result before it entered the transcript: the workflow appended `_serialise_tool_result(tool_result)` whole, the in-process loop `json.dumps(result)` whole.
2. Every tool message is stored twice (`content` plus a default `tool_result` block). Deferred (decision 3).
3. The token gate compared a running sum of every step's usage (`context_usage_total`) with the threshold, and never looked at bytes.
4. The seed guard's comment said the run degrades with a warning; the code raises. `save_conversation` had no size check.
5. `_serialise_tool_result` is shared with the delegation brief and the child's answer text, so the cap could not live inside it.

## As built

**Phase 1, cap external tool results (both paths).**
- `server/services/tool_output.py`: `bound_tool_output(text, limit)` keeps the first `limit` characters and appends `[Tool result truncated: showing the first N of M characters. Call the tool again with narrower parameters to see the rest.]`. Re-bounding keeps the original M. `tool_output_is_capped(node_type)` exempts decision 7's list. `resolve_tool_output_limit(user_settings, settings)` applies per-user `tool_result_max_chars` > `Settings.tool_result_max_chars`, with the `agent_recursion_limit` guard (a positive int).
- Settings: `Settings.tool_result_max_chars` (env `TOOL_RESULT_MAX_CHARS`, default 100,000, `0` disables), `.env.template`, `UserSettings.tool_result_max_chars`, a migration whose column default is read from the model field, and the hand-written `Database.get_user_settings` dict.
- Temporal: `prepare_agent_payload` records `tool_result_max_chars`; `AgentWorkflow.run` bounds `tool_content` right after `_serialise_tool_result` for capped, non-delegation calls.
- In-process: `run_native_agent_loop(..., tool_output_limit=None)` bounds the serialized result; image blocks are read from the untouched result, so `llm_media` refs survive. `AIService.execute_agent` and `execute_chat_agent` resolve and pass the limit.
- Client: `toolResultMaxChars` in `client/src/components/ui/settingsPanel/schema.ts` (range in the shared `TOOL_RESULT_MAX_CHARS_RANGE`), and a "Tool Result Limit" slider (10K to 200K, step 10K) in the Memory & Compaction section of `SettingsPanel.tsx`.

**Phase 2, transcript pressure in `AgentWorkflow` (runs recorded with `context_pressure_version` 1).**
- `prepare_agent_payload` also records `transcript_budget_bytes` (three quarters of `TEMPORAL_PAYLOAD_WARN_BYTES`, derived in `transcript_budget_bytes()`) and `context_pressure_version`.
- `server/services/temporal/agent_context_pressure.py` (pure, workflow-safe). After each tool turn:
  1. `clear_old_tool_results`: over the budget, results from earlier turns become a placeholder, oldest first, external before agent-internal, down to half the budget. `tool_call_id` and `name` survive; the wire is rebuilt so the duplicated block goes too.
  2. Summarize when `projected_request_tokens` (the step's `total_tokens`, plus the turn's added characters net of what was cleared, at four per token) reaches the threshold, or when `earlier_turns_over_budget` (still over budget with the earlier turns holding more than half of it). Only the turns before the latest are summarized (`summarizer_view`), and the swap is `[system, user(summary + current request), latest turn verbatim]`. With nothing older than the latest turn (`has_summarizable_history`), it skips.
  3. `clip_latest_turn`: if the latest turn alone still overflows, its external results are cut to one shared length found by bisection on the exact serialized size, never below 2,000 characters.
- Without the key, the original cumulative gate and whole-transcript swap run unchanged.

**Phase 3, seed guard.** Comment rewritten to describe the raise. The message now reads "Clear the conversation from the Context panel, then run again. Settings > Tool Result Limit caps how much one tool call can add to it." `_save_conversation` logs a WARNING over half of `_SEED_TRANSCRIPT_MAX_BYTES`. `prepare_agent_payload` logs a WARNING instead of silently dropping the threshold when it cannot be computed.

**Phase 4, docs.** `errors.md` entry 28; `agent_context_flow.md` (new "Transcript size" section, compaction rewrite, invariant 10); `memory_compaction.md`; `TEMPORAL_ARCHITECTURE.md` (the loop pseudo-code, the `agent.prepare_payload` and `agent.compact_context` rows: compaction failure is terminal, not best-effort); `data_node.md`; `CLAUDE.md`; `.env.template`.

## Differences from the approved plan, and why

- **Module location.** `server/services/tool_output.py`, not under `services/llm/` as planned: importing anything there runs that package's `__init__`, which reads `llm_defaults.json` from disk. The new module needs only `constants` and the standard library, so workflow code imports it at module level like `get_node_class`.
- **Truncation note.** The approved text said "The full result is in this tool's node output panel". That is false for tools that hide their Output section (`simpleMemory`, `dataSource`, `visionAnalyze`, `processManager`) and only true for a tool's latest call, so the note only tells the model how to get the rest.
- **Order: clear, then summarize, then clip.** The plan clipped the latest turn inside the clearing step, before any summary; that could cut unread results to fit a history the summary was about to replace. Clipping now runs last, against the room that remains.
- **Byte-forced summary.** The plan summarized for token pressure only. A transcript whose bulk is text (long user or assistant messages) cannot be brought under budget by clearing tool results, so it also summarizes when the earlier turns alone keep it over budget, but not when the latest turn is the excess (clipping handles that without a paid call).
- **Token arithmetic.** Checked per provider: every provider's `total_tokens` is the whole prompt, cache reads and writes included, plus output (Anthropic adds the cache counters itself; OpenAI and Gemini already count them in input). The gate uses the step's `total_tokens`; no provider change was needed.
- **Settings getter.** `Database.get_user_settings` builds its dict by hand, so it needed the new key (the plan said no edit); `server/tests/test_user_settings_contract.py` enforces it.

## Tests

- `server/tests/services/test_tool_output.py`: bounding and re-bounding, the note, exemptions, limit precedence, and one test that keeps the four copies of the default (`.env.template`, `Settings`, `UserSettings`, client schema) equal.
- `server/tests/temporal/test_agent_context_pressure.py`: clearing order and target, pairing, clipping to one length, the minimum length, token arithmetic, summarizer view.
- `server/tests/temporal/test_agent_workflow_pressure.py`: `AgentWorkflow.run` end to end with scripted activities: cap and exemptions, legacy histories untouched, clearing across turns, clipping a single overflowing turn, the next-request gate against the legacy running sum, the kept latest turn, byte-forced summary, compaction off.
- `server/tests/temporal/test_prepare_payload_pressure.py`: the recorded keys and precedence, the seed guard at and over the cap, the threshold warning, the save warning.
- `server/tests/temporal/test_agent_workflow.py`: `TestTranscriptPressureReplaySafety` source guards.
- `server/tests/services/test_native_agent_runtime.py`: in-process cap, `llm_media` survival, skill exemption, no limit.
- `client/src/components/ui/settingsPanel/schema.test.ts`: round trip, mapping, default for old rows, range.

## Verification

```
cd server && uv run pytest tests/ -q
bun run typecheck
bun --cwd=client run test
```

End to end, for the user to run (it needs the real app and data directory): clear the oversized conversation once from the Context panel, run the tikhub prompt that caused the incident, and expect no `PayloadSizeWarning`, tool messages ending with the truncation note, an INFO line when old results are cleared, and a second chat message that runs.

## Deferred and found along the way

- Wire dedupe (decision 3).
- Pressure relief on the in-process path, which gets only the cap. `CompactionService.track()` also sums every request's `total_tokens` across a session, the same running-sum problem the workflow had.
- Chunked summarization for models whose window is smaller than the budget.
- From reading `services/pricing.py` and `config/pricing.json` (not exercised by a test): pricing assumes Anthropic's usage semantics for every provider: OpenAI and OpenAI-compatible cached tokens are charged at the input rate and again at the cache rate, o4-mini reasoning tokens are charged twice, and Gemini thinking tokens are never charged. Separate billing change.
- Not verified: `BaseNode.execute_as_tool` may hand the model `{"result": None}` for Task Manager calls whose payload has `success` but no `result` key.
