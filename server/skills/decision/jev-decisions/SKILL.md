---
name: jev-decisions
description: Compose typed questions (choice / score / noul) for the TypeSafe JEV decision model and read its typed answers — state in, calibrated decisions out, no generated strings.
allowed-tools: jev
metadata:
  author: opencompany
  version: "1.1"
  category: decision

---

# JEV Decisions Skill

Compose **questions** for the TypeSafe JEV decision model — a System One model
that evaluates a *state* and returns **structured, type-safe answers** with
calibrated probabilities and confidence. JEV never generates strings and never
hallucinates: every answer is one of the typed values you asked for. Calls
complete in 70–500 ms.

## How It Works

This skill teaches both halves of the contract: how to **compose** the
`questions` JSON (and the `state`), and how to **read** the typed answers
(decisions, confidence, probabilities) so workflow code can branch on them.
To execute decisions, connect the **JEV** node to the agent's `input-tools`
handle and call the `jev` tool with `state` + `questions`.

## The `jev` Tool

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| state | string | Yes | The unstructured state to evaluate: plain text, or a JSON-serialized object/array (chat logs, records, form data). Objects/arrays are sent as structured state. |
| questions | string (JSON) | Yes | Object mapping question ids to typed questions — see the contract below. |
| jev_model | string | No | TypeSafe model id. Default `jev-latest` tracks the flagship release. |
| provider | string | No | `typesafe` (default, direct API with the console.typesafe.ai key) or `openrouter` (System One surface routed through OpenRouter, billed to the OpenRouter account). The questions contract is identical. |

## Choosing a Provider

`provider` selects who answers; the request and response shapes are the same:

- **`typesafe`** — direct TypeSafe API (`api.typesafe.ai`). Needs the
  **TypeSafe AI** credential.
- **`openrouter`** — `openrouter.ai/api/v1/systemone`, the TypeSafe-SDK-
  compatible surface. Needs the **OpenRouter** credential; calls are billed to
  your OpenRouter account (each response reports `usage.cost` in USD). Bare
  model ids (`jev-latest`, `jev-1.13`) are mapped onto the `typesafe/`
  namespace automatically. `jev-router` is OpenRouter's *chat* routing model —
  it cannot answer System One questions, so don't select it as `model` here.

Pick `openrouter` when you already have OpenRouter credit and want one bill;
pick `typesafe` when you have a direct TypeSafe key or need the vendor's
latest release first.

## The Questions JSON Contract

`questions` is a JSON object. Each **key is a question id** (that id comes back
as the answer key). Each **value is a typed question** with a `type` of
`choice`, `score`, or `noul`:

```json
{
  "department": {
    "type": "choice",
    "instructions": "Which team should handle this",
    "criteria": {
      "billing": "Payments, invoices, refunds",
      "technical": "Bugs, API errors, integrations",
      "sales": "Pricing, plans, upgrades"
    }
  },
  "frustration": {
    "type": "score",
    "instructions": "How frustrated is the customer",
    "criteria": ["Calm", "Frustrated", "Angry"]
  },
  "is_urgent": {
    "type": "noul",
    "instructions": "Conveys urgency: blocked work, revenue loss, or a deadline today"
  }
}
```

### Question Types

| Type | Decides | `criteria` | Answer value |
|------|---------|------------|--------------|
| `choice` | Pick ONE option | Map `{"option": "description"}` (max 255 options). A plain array of labels is accepted and normalized to label-only options. | The winning option label |
| `score` | Rate on an ordered rubric | Array of 2–10 level descriptions, ordered low → high | A number, probability-weighted — it can land **between** levels (e.g. 1.05 on a 0/1/2 rubric) |
| `noul` | Yes/no probability | Optional map `{"true": "...", "false": "..."}` clarifying each pole | A probability 0–1 |

Every question **must** include `instructions` — a full sentence saying exactly
what to judge. This is the model's directive, not a label.

## The Response

The tool returns the raw `answers` (per id, typed) plus a flattened surface for
direct branching:

| Key | Contents |
|-----|----------|
| `decisions` | id → bare decision value: choice label, score number, or noul probability |
| `confidence` | id → calibrated confidence 0–1 (choice and score; noul IS a probability, so it carries none) |
| `probabilities` | id → distribution over options/levels (choice and score) |
| `legends` | id → level index → description (score only) |
| `input_tokens` / `output_tokens` | Usage counters |

```json
{
  "decisions": {"department": "technical", "frustration": 1.05, "is_urgent": 0.99},
  "confidence": {"department": 0.81, "frustration": 0.92},
  "probabilities": {"department": {"technical": 0.88, "billing": 0.12, "sales": 0.0}}
}
```

### Reading the Raw Answers

`answers` keeps the API's per-id objects — the `type` inside each one tells you
which fields to read:

```json
{
  "department": {
    "type": "choice",
    "choice": "technical",
    "confidence": 0.81,
    "probabilities": {"technical": 0.88, "billing": 0.12, "sales": 0.0}
  },
  "frustration": {
    "type": "score",
    "score": 1.05,
    "confidence": 0.92,
    "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
    "legend": {"0": "Calm", "1": "Frustrated", "2": "Angry"}
  },
  "is_urgent": {"type": "noul", "noul": 0.99}
}
```

How to read each primitive:

- **`choice`** — `choice` is the winner (the argmax of `probabilities`); the
  probabilities show how close the runner-up was. `0.88` vs `0.12` is a clear
  call; `0.45` vs `0.44` is a coin flip — treat near-ties as "ambiguous" and
  branch for a human, don't act on the label.
- **`score`** — the number is a probability-weighted position on the rubric and
  can land **between** levels: `1.05` on a 0/1/2 rubric reads "solidly
  Frustrated, edging toward Angry". Use `legend` to translate index →
  description, and set your threshold on the number (`score >= 2` = top level
  or beyond), not on the label.
- **`noul`** — the value IS the probability of yes. `> 0.5` means yes, but pick
  your own operating threshold per question (see below).

**`probabilities` vs `confidence`**: `probabilities` is the distribution over
options/levels — the *shape* of the judgment. `confidence` (choice and score
only) is JEV's calibrated assurance in the top pick; `noul` carries no separate
confidence because the value itself is the probability. Gate actions on
`confidence`, inspect `probabilities` to understand *why*.

**Thresholds** (starting points — tune per question, not one global number):

| Confidence | Meaning | Action |
|-----------|---------|--------|
| ≥ 0.8 | Clear call | Act automatically |
| 0.5 – 0.8 | Leaning, not certain | Secondary check, or log and continue |
| < 0.5 | Ambiguous | Escalate to a human |

Questions in one request are answered **independently and in parallel** — no
answer sees another's. Read `decisions` per id and combine the values in your
own code; if one judgment depends on another, make it a second call with the
first answer folded into the `state`.

On the `openrouter` provider, `usage.cost` (USD) reports the exact cost of the
call; output tokens are always free.

## Composition Patterns

1. **Ask ATOMIC questions** — one judgment per question id. Don't ask
   "is this urgent AND technical"; ask `is_urgent` and `department`
   separately and combine the answers in code.
2. **Branch on `decisions`, gate on `confidence`.** Route the workflow on the
   decision value; only act automatically when confidence clears a threshold
   (e.g. ≥ 0.7), otherwise escalate to a human.
3. **Use `score` for intensity, `noul` for gatekeeping.** `frustration` on a
   3-level rubric tells you how heated a ticket is; `is_urgent` (a probability)
   tells you whether to page someone.
4. **Use `choice` for closed routing.** Team assignment, language detection
   from a supported list, ticket category — anything with a fixed option set.
   Give every option a one-line description so the criteria are self-contained.
5. **Pass structured state when you have it.** JSON objects/arrays (transcript,
   record) are evaluated as-is; keep the state factual and let the questions
   carry the judgment.
6. **Validate before spending tokens.** Malformed questions fail fast with an
   actionable error — `questions` must be a non-empty JSON object, every entry
   needs a known `type` and `instructions`, `choice` needs a criteria map
   (≤ 255 options), `score` needs 2–10 ordered levels.

## Anti-Patterns

- **Free-form answers from an LLM.** If you need generated text, use a chat
  model node — JEV is for typed decisions only.
- **Compound questions.** "Is this angry AND about billing?" — split it.
- **Vague instructions.** "Classify the message" is not a directive; say what
  evidence decides each option or level.
- **Overlapping choice options.** If two criteria could both win, split them
  into separate questions or make the descriptions mutually exclusive.
- **Reading `confidence` as a probability of being right.** It is a calibrated
  uncertainty signal — use it to gate, not as a guarantee.