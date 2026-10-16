"""JEV — TypeSafe System One decision model (Wave: JEV integration).

Dual-purpose node in the ``anthropicChatModel`` ("Claude") mould, adapted
to a System One contract: instead of generating strings, Jev evaluates a
*state* against typed *questions* (the three TypeSafe primitives —
``choice`` / ``score`` / ``noul``) and returns structured, type-safe
answers with calibrated probabilities and confidence. No parsing layer:
the answers slot directly into workflow branching.

- Canvas: a square tool-style node — ``state`` + ``questions`` in params,
  structured answers out ``output-main``.
- Tool: agents call ``jev`` with ``state`` + ``questions`` per decision.
  The bundled ``jev-decisions`` skill teaches the exact questions JSON
  contract (how to compose the structured output Jev expects); the tool
  description carries the short version.

Two providers, same wire contract (``state`` + ``questions`` in, typed
``answers`` out):

- ``openrouter`` (default) — ``POST https://openrouter.ai/api/v1/systemone``,
  the TypeSafe-SDK-compatible System One surface (the official SDKs point at
  it by changing the base URL; bare model ids like ``jev-latest`` map onto
  the ``typesafe/`` namespace), billed to the OpenRouter account
  (``OpenRouterCredential``). ``jev-router`` is OpenRouter's *chat*
  routing model — not answerable through this node.
- ``typesafe`` — ``POST https://api.typesafe.ai/v1/systemone``, key from
  console.typesafe.ai/keys (``TypesafeCredential``).

Docs: https://docs.typesafe.ai/api,
https://openrouter.ai/docs/guides/community/jev.
Deliberately NOT registered as a chat LLM provider (Jev gives up string
generation, so it cannot serve as an agent's chat model); it appears in
the model catalogue (``llm_defaults.json``) and the Credentials modal
only.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

from services.plugin import (
    ActionNode,
    ApiKeyCredential,
    NodeContext,
    NodeUserError,
    Operation,
    ProbeResult,
    TaskQueue,
)

from .._credentials import OpenRouterCredential

API_BASE = "https://api.typesafe.ai/v1"
SYSTEMONE_URL = f"{API_BASE}/systemone"
MODELS_URL = f"{API_BASE}/models"
# OpenRouter's TypeSafe-SDK-compatible System One surface: same request and
# response shape, same bearer auth — different host and key pool
# (openrouter.ai/keys). https://openrouter.ai/docs/guides/community/jev
OPENROUTER_SYSTEMONE_URL = "https://openrouter.ai/api/v1/systemone"

_PROVIDERS = ("typesafe", "openrouter")
_PROVIDER_ENDPOINTS = {
    "typesafe": SYSTEMONE_URL,
    "openrouter": OPENROUTER_SYSTEMONE_URL,
}

_QUESTION_TYPES = ("choice", "score", "noul")
_MAX_CHOICE_OPTIONS = 255
_MIN_SCORE_LEVELS = 2
_MAX_SCORE_LEVELS = 10


class TypesafeCredential(ApiKeyCredential):
    """TypeSafe AI API key (console.typesafe.ai/keys).

    The probe lists models at ``GET /v1/models``; the minimal-evaluation
    fallback covers deployments that only expose the systemone endpoint.
    """

    id = "typesafe"
    display_name = "TypeSafe AI"
    category = "AI"
    key_name = "Authorization"
    key_location = "bearer"
    docs_url = "https://console.typesafe.ai/keys"

    @classmethod
    async def _probe(cls, api_key: str) -> ProbeResult:
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(MODELS_URL, headers=headers)
            except httpx.HTTPError as exc:
                raise NodeUserError(
                    f"TypeSafe AI unreachable: {exc.__class__.__name__}"
                ) from exc
            if resp.status_code == 401:
                return ProbeResult(
                    valid=False,
                    message="TypeSafe rejected the key (401 Unauthorized).",
                )
            if resp.status_code == 200:
                models = [
                    entry.get("id")
                    for entry in (resp.json().get("models") or [])
                    if isinstance(entry, dict) and entry.get("id")
                ]
                return ProbeResult(
                    valid=True,
                    message="API key validated",
                    models=models or None,
                )
            if resp.status_code == 404:
                # No model-list endpoint on this deployment — fall back to a
                # minimal evaluation probe (one noul question; costs a token).
                probe = await client.post(
                    SYSTEMONE_URL,
                    headers=headers,
                    json={
                        "state": "ping",
                        "model": "jev-latest",
                        "questions": {
                            "ok": {"type": "noul", "instructions": "Always true."}
                        },
                    },
                )
                if probe.status_code == 401:
                    return ProbeResult(
                        valid=False,
                        message="TypeSafe rejected the key (401 Unauthorized).",
                    )
                probe.raise_for_status()
                return ProbeResult(valid=True, message="API key validated")
            resp.raise_for_status()
            return ProbeResult(valid=True, message="API key validated")


class JevParams(BaseModel):
    """Flat tool-facing params (contract: no nested models).

    ``questions`` is a JSON *string* — the structured-output contract the
    agent composes per decision. Kept as a string so the tool schema stays
    flat; the operation parses + validates it and fails fast with
    actionable NodeUserError messages (the ``jev-decisions`` skill teaches
    the exact shape).
    """

    state: str = Field(
        ...,
        min_length=1,
        description=(
            "The unstructured state to evaluate: plain text, or a JSON-serialized "
            "object/array for structured program state (chat logs, records, form data)."
        ),
        json_schema_extra={"rows": 5},
    )
    questions: str = Field(
        ...,
        min_length=2,
        description=(
            'JSON object of typed questions, e.g. {"department": {"type": "choice", '
            '"instructions": "Which team handles this", "criteria": {"billing": "...", '
            '"technical": "..."}}, "is_urgent": {"type": "noul", "instructions": "..."}}. '
            'Types: choice (criteria = option map, max 255), score (criteria = ordered '
            "array of 2-10 level descriptions), noul (yes/no probability)."
        ),
        json_schema_extra={"rows": 8},
    )
    # NOT named `model`: with a sibling `provider` field the parameter panel
    # would overwrite it with the chat-model list (reserved-name magic in
    # ParameterRenderer.tsx) — same reason visionAnalyze uses `vision_model`.
    jev_model: str = Field(
        default="jev-latest",
        description=(
            'TypeSafe model id. "jev-latest" tracks the flagship release; '
            '"jev-1.14" / "jev-1.13" pin a release. On the openrouter '
            "provider, bare ids map onto the typesafe/ namespace."
        ),
    )
    provider: Literal["typesafe", "openrouter"] = Field(
        default="openrouter",
        description=(
            "Who answers the call: 'openrouter' (default — the System One "
            "surface routed through OpenRouter, openrouter.ai key, billed "
            "to the OpenRouter account) or 'typesafe' (direct TypeSafe API, "
            "console.typesafe.ai key). Same questions contract either way."
        ),
    )

    model_config = ConfigDict(extra="ignore")


class JevOutput(BaseModel):
    """Structured Jev answers, flattened for direct branching.

    ``answers`` keeps the raw API shape (per-id, typed). ``decisions`` maps
    each id to its bare decision value — ``choice`` label, ``score`` number
    (probability-weighted, can land between levels) or ``noul`` probability
    (0-1). ``confidence``/``probabilities`` carry the calibrated uncertainty
    for choice/score answers (noul IS a probability, so it has none).
    """

    model_config = ConfigDict(extra="allow")

    model: str = ""
    answers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    decisions: Dict[str, Any] = Field(default_factory=dict)
    confidence: Dict[str, float] = Field(default_factory=dict)
    probabilities: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    legends: Dict[str, Dict[str, str]] = Field(default_factory=dict)
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


def _parse_state(raw: str) -> Any:
    """String in, string or structured object out.

    A JSON object/array is sent as structured state; everything else
    (including bare scalars that happen to parse) stays a plain string.
    """
    stripped = (raw or "").strip()
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return raw
        if isinstance(parsed, (dict, list)):
            return parsed
    return raw


def _parse_questions(raw: str) -> Dict[str, Any]:
    """Validate the questions JSON against the TypeSafe question shapes.

    Fail-fast with actionable messages: a malformed question is an operator
    error, not a retryable API failure.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NodeUserError(
            f"'questions' is not valid JSON (at char {exc.pos}): {exc.msg}. "
            "It must be an object mapping question ids to typed questions — "
            "see the jev-decisions skill."
        ) from exc

    if not isinstance(parsed, dict) or not parsed:
        raise NodeUserError(
            "'questions' must be a non-empty JSON object mapping ids to "
            'questions, e.g. {"is_urgent": {"type": "noul", "instructions": "..."}}.'
        )

    validated: Dict[str, Any] = {}
    for qid, question in parsed.items():
        if not isinstance(question, dict):
            raise NodeUserError(
                f"Question '{qid}' must be an object with a 'type' field "
                "(choice | score | noul)."
            )
        qtype = question.get("type")
        if qtype not in _QUESTION_TYPES:
            raise NodeUserError(
                f"Question '{qid}' has type '{qtype}' — expected one of "
                f"{', '.join(_QUESTION_TYPES)}."
            )
        instructions = question.get("instructions")
        if not instructions:
            raise NodeUserError(f"Question '{qid}' is missing 'instructions'.")

        clean: Dict[str, Any] = {"type": qtype, "instructions": instructions}

        criteria = question.get("criteria")
        if qtype == "choice":
            if isinstance(criteria, list):
                # Friendlier labels-without-descriptions form; the API wants a
                # map, so {label: null} is the faithful conversion.
                criteria = {str(label): None for label in criteria}
            if not isinstance(criteria, dict) or not criteria:
                raise NodeUserError(
                    f"Question '{qid}' (choice) needs 'criteria' as a map of "
                    '{{"option": "description"}} — max '
                    f"{_MAX_CHOICE_OPTIONS} options."
                )
            if len(criteria) > _MAX_CHOICE_OPTIONS:
                raise NodeUserError(
                    f"Question '{qid}' (choice) has {len(criteria)} options — "
                    f"TypeSafe allows up to {_MAX_CHOICE_OPTIONS}."
                )
            clean["criteria"] = criteria
        elif qtype == "score":
            if not isinstance(criteria, list) or not (
                _MIN_SCORE_LEVELS <= len(criteria) <= _MAX_SCORE_LEVELS
            ):
                raise NodeUserError(
                    f"Question '{qid}' (score) needs 'criteria' as an ordered "
                    f"array of {_MIN_SCORE_LEVELS}-{_MAX_SCORE_LEVELS} level "
                    "descriptions (e.g. [\"Calm\", \"Frustrated\", \"Angry\"])."
                )
            clean["criteria"] = criteria
        else:  # noul
            if isinstance(criteria, dict):
                clean["criteria"] = {
                    k: criteria[k] for k in ("true", "false") if k in criteria
                } or None

        validated[str(qid)] = clean
    return validated


def _flatten_answers(
    answers: Dict[str, Any],
) -> tuple:
    """Split raw answers into decisions / confidence / probabilities / legends."""
    decisions: Dict[str, Any] = {}
    confidence: Dict[str, float] = {}
    probabilities: Dict[str, Dict[str, float]] = {}
    legends: Dict[str, Dict[str, str]] = {}
    for qid, answer in answers.items():
        if not isinstance(answer, dict):
            continue
        atype = answer.get("type")
        if atype == "choice":
            decisions[qid] = answer.get("choice")
            if isinstance(answer.get("confidence"), (int, float)):
                confidence[qid] = float(answer["confidence"])
            if isinstance(answer.get("probabilities"), dict):
                probabilities[qid] = answer["probabilities"]
        elif atype == "score":
            decisions[qid] = answer.get("score")
            if isinstance(answer.get("confidence"), (int, float)):
                confidence[qid] = float(answer["confidence"])
            if isinstance(answer.get("probabilities"), dict):
                probabilities[qid] = answer["probabilities"]
            if isinstance(answer.get("legend"), dict):
                legends[qid] = answer["legend"]
        elif atype == "noul":
            decisions[qid] = answer.get("noul")
    return decisions, confidence, probabilities, legends


class JevNode(ActionNode):
    """TypeSafe JEV — the System One decision model as a node + agent tool."""

    type = "jev"
    display_name = "JEV"
    subtitle = "Decision Model (System One)"
    group = ("model", "tool")
    description = (
        "TypeSafe JEV: state in, typed structured decisions out. Compose "
        "choice/score/noul questions and branch on calibrated answers — "
        "no hallucinated strings, 70-500ms per call"
    )
    component_kind = "tool"

    usable_as_tool = True
    tool_name = "jev"
    # usable_as_tool auto-hides the canvas handles; this node must stay
    # wirable on the canvas (state/answers flow) as well as callable as a
    # tool — same opt-out as tikhubAction / documentParser.
    hide_input_handle = False
    hide_output_handle = False
    tool_description = (
        "Ask the TypeSafe JEV decision model — a System One model that returns "
        "type-safe structured answers with calibrated probabilities and "
        "confidence, never generated text. Pass `state` (the facts: plain text "
        "or a JSON object/array) and `questions` (a JSON object mapping ids to "
        "typed questions: {\"id\": {\"type\": \"choice\"|\"score\"|\"noul\", "
        "\"instructions\": \"...\", \"criteria\": ...}}). choice = pick one "
        "option from a criteria map (max 255); score = rate on an ordered "
        "2-10 level rubric; noul = yes/no probability 0-1. `provider` picks "
        "who answers: 'openrouter' (default — routed through OpenRouter, "
        "openrouter.ai key) or 'typesafe' (direct API, console.typesafe.ai "
        "key) — the questions contract is identical. Ask ATOMIC questions "
        "(one judgment each) and combine in code. Returns `decisions` "
        "(id -> value), `confidence` and `probabilities` — branch on the "
        "decision, gate the action on confidence. Use the jev-decisions skill "
        "for the full contract and composition patterns."
    )

    handles = (
        {"name": "input-main", "kind": "input", "position": "left", "label": "Input", "role": "main"},
        {"name": "output-main", "kind": "output", "position": "right", "label": "Answers", "role": "main"},
    )
    annotations = {"destructive": False, "readonly": True, "open_world": True}
    task_queue = TaskQueue.REST_API
    credentials = (TypesafeCredential, OpenRouterCredential)

    Params = JevParams
    Output = JevOutput

    @Operation("evaluate", cost={"service": "jev", "action": "system_one", "count": 1})
    async def evaluate(self, ctx: NodeContext, params: JevParams) -> JevOutput:
        questions = _parse_questions(params.questions)
        payload = {
            "state": _parse_state(params.state),
            "model": params.jev_model or "jev-latest",
            "questions": questions,
        }

        data = await self._post_systemone(ctx, payload, params.provider)

        answers = data.get("answers") or {}
        if not isinstance(answers, dict):
            raise NodeUserError("TypeSafe returned a malformed answers payload.")
        decisions, confidence, probabilities, legends = _flatten_answers(answers)
        usage = data.get("usage") or {}

        return JevOutput(
            model=str(data.get("model") or params.model),
            answers=answers,
            decisions=decisions,
            confidence=confidence,
            probabilities=probabilities,
            legends=legends,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

    @staticmethod
    async def _post_systemone(
        ctx: NodeContext, payload: Dict[str, Any], provider: str = "openrouter"
    ) -> Dict[str, Any]:
        """POST the System One surface with one polite retry on 429/529.

        Both providers speak the identical request/response contract — the
        choice only picks the host and the credential pool (see the module
        docstring for the two endpoints).
        """
        provider = provider if provider in _PROVIDERS else "typesafe"
        url = _PROVIDER_ENDPOINTS[provider]
        label = "TypeSafe" if provider == "typesafe" else "OpenRouter"
        async with ctx.connection(provider) as conn:
            try:
                response = await conn.post(
                    url,
                    json=payload,
                    headers={"Accept": "application/json"},
                )
                if response.status_code in (429, 529):
                    await asyncio.sleep(1.0)
                    response = await conn.post(
                        url,
                        json=payload,
                        headers={"Accept": "application/json"},
                    )
            except httpx.TimeoutException as exc:
                raise NodeUserError(
                    f"{label} API timed out after 30s — JEV calls normally "
                    "take under a second; retry the workflow."
                ) from exc
            except httpx.HTTPError as exc:
                raise NodeUserError(
                    f"{label} API unreachable: {exc.__class__.__name__}"
                ) from exc

        if response.status_code == 401:
            raise NodeUserError(
                f"{label} API key invalid or missing (401). Connect the "
                f"'{provider}' credential in the Credentials modal."
            )
        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                detail = body.get("detail") or body.get("error") or body.get("message") or ""
                if isinstance(detail, dict):
                    detail = json.dumps(detail)
            except Exception:  # noqa: BLE001 — detail is best-effort
                detail = ""
            raise NodeUserError(
                f"TypeSafe API error {response.status_code}"
                + (f": {detail}" if detail else "")
            )

        return response.json()


# Re-exported for tests that patch the HTTP boundary without importing
# httpx request plumbing through the Connection facade.
__all__ = [
    "JevNode",
    "JevParams",
    "JevOutput",
    "TypesafeCredential",
    "OPENROUTER_SYSTEMONE_URL",
    "SYSTEMONE_URL",
    "_parse_questions",
    "_parse_state",
    "_flatten_answers",
]
