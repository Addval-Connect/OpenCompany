"""Contract tests for the JEV node (TypeSafe System One decision model).

Freezes the input -> output behaviour: questions-JSON validation, the
request shape sent to ``POST /v1/systemone``, and the flattened answer
surface (decisions / confidence / probabilities / legends). httpx is
mocked with respx so no network is touched.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from tests.nodes._mocks import patched_container, patched_pricing


pytestmark = pytest.mark.node_contract

URL = "https://api.typesafe.ai/v1/systemone"


def _mixed_answers():
    return {
        "model": "jev-1.13.0",
        "answers": {
            "department": {
                "type": "choice",
                "choice": "technical",
                "confidence": 0.81,
                "probabilities": {"technical": 0.88, "billing": 0.12, "sales": 0.0},
            },
            "frustration": {
                "type": "score",
                "score": 1.05,
                "confidence": 0.92,
                "legend": {"0": "Calm", "1": "Frustrated", "2": "Angry"},
                "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
            },
            "is_urgent": {"type": "noul", "noul": 0.99},
        },
        "usage": {"input_tokens": 318, "output_tokens": 34},
    }


QUESTIONS = {
    "department": {
        "type": "choice",
        "instructions": "Which team should handle this",
        "criteria": {"billing": "Payments", "technical": "Bugs", "sales": "Pricing"},
    },
    "frustration": {
        "type": "score",
        "instructions": "How frustrated is the customer",
        "criteria": ["Calm", "Frustrated", "Angry"],
    },
    "is_urgent": {"type": "noul", "instructions": "Conveys urgency"},
}


class TestJevEvaluate:
    @respx.mock
    async def test_happy_path_mixed_questions(self, harness):
        route = respx.post(URL).mock(return_value=httpx.Response(200, json=_mixed_answers()))

        with patched_container(auth_api_keys={"typesafe": "ts_key"}), patched_pricing():
            result = await harness.execute(
                "jev",
                {
                    "state": "Our API integration returns 500 errors and orders are blocked.",
                    "questions": json.dumps(QUESTIONS),
                },
            )

        harness.assert_envelope(result, success=True)
        payload = result["result"]

        # Request shape: string state, explicit model, questions passed through.
        sent = json.loads(route.calls[0].request.content)
        assert isinstance(sent["state"], str)
        assert sent["model"] == "jev-latest"
        assert sent["questions"]["department"]["type"] == "choice"
        # Auth is a bearer key from the typesafe credential.
        assert route.calls[0].request.headers["Authorization"] == "Bearer ts_key"

        # Flattened surface.
        assert payload["decisions"] == {
            "department": "technical",
            "frustration": 1.05,
            "is_urgent": 0.99,
        }
        assert payload["confidence"] == {"department": 0.81, "frustration": 0.92}
        assert payload["probabilities"]["department"]["technical"] == 0.88
        assert payload["legends"]["frustration"] == {"0": "Calm", "1": "Frustrated", "2": "Angry"}
        assert payload["input_tokens"] == 318
        assert payload["output_tokens"] == 34
        assert payload["model"] == "jev-1.13.0"
        # Raw answers preserved under the same ids.
        assert set(payload["answers"]) == {"department", "frustration", "is_urgent"}

    @respx.mock
    async def test_structured_state_sent_as_object(self, harness):
        route = respx.post(URL).mock(return_value=httpx.Response(200, json=_mixed_answers()))

        with patched_container(auth_api_keys={"typesafe": "ts_key"}), patched_pricing():
            result = await harness.execute(
                "jev",
                {
                    "state": json.dumps({"messages": ["a", "b"], "user": "u1"}),
                    "questions": json.dumps({"is_urgent": {"type": "noul", "instructions": "urgent?"}}),
                },
            )

        harness.assert_envelope(result, success=True)
        sent = json.loads(route.calls[0].request.content)
        assert sent["state"] == {"messages": ["a", "b"], "user": "u1"}

    @respx.mock
    async def test_bare_scalar_state_stays_a_string(self, harness):
        route = respx.post(URL).mock(return_value=httpx.Response(200, json=_mixed_answers()))

        with patched_container(auth_api_keys={"typesafe": "ts_key"}), patched_pricing():
            result = await harness.execute(
                "jev",
                {
                    "state": "42",
                    "questions": json.dumps({"is_urgent": {"type": "noul", "instructions": "urgent?"}}),
                },
            )

        harness.assert_envelope(result, success=True)
        assert json.loads(route.calls[0].request.content)["state"] == "42"


class TestQuestionsValidation:
    async def test_malformed_json_fails_fast(self, harness):
        with patched_container(auth_api_keys={"typesafe": "ts"}), patched_pricing():
            result = await harness.execute("jev", {"state": "s", "questions": "{not json"})

        harness.assert_envelope(result, success=False)
        assert "not valid JSON" in result["error"]

    async def test_unknown_question_type(self, harness):

        with patched_container(auth_api_keys={"typesafe": "ts"}), patched_pricing():
            result = await harness.execute(
                "jev",
                {"state": "s", "questions": json.dumps({"x": {"type": "vibe", "instructions": "..."}})},
            )

        harness.assert_envelope(result, success=False)
        assert "choice, score, noul" in result["error"]

    async def test_choice_requires_criteria_map(self, harness):

        with patched_container(auth_api_keys={"typesafe": "ts"}), patched_pricing():
            result = await harness.execute(
                "jev",
                {"state": "s", "questions": json.dumps({"x": {"type": "choice", "instructions": "..."}})},
            )

        harness.assert_envelope(result, success=False)
        assert "criteria" in result["error"]

    @respx.mock
    async def test_choice_list_criteria_normalized_to_labels(self, harness):

        route = respx.post(URL).mock(return_value=httpx.Response(200, json=_mixed_answers()))
        with patched_container(auth_api_keys={"typesafe": "ts_key"}), patched_pricing():
            result = await harness.execute(
                "jev",
                {
                    "state": "s",
                    "questions": json.dumps(
                        {"pick": {"type": "choice", "instructions": "pick one", "criteria": ["a", "b"]}}
                    ),
                },
            )

        harness.assert_envelope(result, success=True)
        sent = json.loads(route.calls[0].request.content)
        assert sent["questions"]["pick"]["criteria"] == {"a": None, "b": None}

    async def test_score_needs_two_to_ten_levels(self, harness):

        with patched_container(auth_api_keys={"typesafe": "ts"}), patched_pricing():
            result = await harness.execute(
                "jev",
                {
                    "state": "s",
                    "questions": json.dumps(
                        {"rate": {"type": "score", "instructions": "...", "criteria": ["only one"]}}
                    ),
                },
            )

        harness.assert_envelope(result, success=False)
        assert "2-10" in result["error"]

    async def test_choice_rejects_more_than_255_options(self, harness):

        with patched_container(auth_api_keys={"typesafe": "ts"}), patched_pricing():
            result = await harness.execute(
                "jev",
                {
                    "state": "s",
                    "questions": json.dumps(
                        {
                            "big": {
                                "type": "choice",
                                "instructions": "...",
                                "criteria": {f"opt{i}": "d" for i in range(256)},
                            }
                        }
                    ),
                },
            )

        harness.assert_envelope(result, success=False)
        assert "255" in result["error"]


class TestHttpErrors:
    @respx.mock
    async def test_unauthorized_becomes_actionable_error(self, harness):

        respx.post(URL).mock(return_value=httpx.Response(401, json={"detail": "bad key"}))
        with patched_container(auth_api_keys={"typesafe": "ts_bad"}), patched_pricing():
            result = await harness.execute(
                "jev",
                {"state": "s", "questions": json.dumps({"x": {"type": "noul", "instructions": "..."}})},
            )

        harness.assert_envelope(result, success=False)
        assert "401" in result["error"]

    @respx.mock
    async def test_429_retries_once_then_succeeds(self, harness):

        route = respx.post(URL).mock(
            side_effect=[
                httpx.Response(429, json={"detail": "slow down"}),
                httpx.Response(200, json=_mixed_answers()),
            ]
        )
        with patched_container(auth_api_keys={"typesafe": "ts_key"}), patched_pricing():
            result = await harness.execute(
                "jev",
                {"state": "s", "questions": json.dumps({"x": {"type": "noul", "instructions": "..."}})},
            )

        harness.assert_envelope(result, success=True)
        assert route.call_count == 2


class TestToolSurface:
    def test_tool_registration_and_handles(self):
        from services.node_registry import get_node_class
        from services.node_spec import get_node_spec

        cls = get_node_class("jev")
        assert cls.usable_as_tool is True
        assert cls.tool_name == "jev"
        assert cls.hide_input_handle is False
        assert cls.hide_output_handle is False

        handles = get_node_spec("jev").get("handles") or []
        names = {h.get("name") for h in handles}
        assert {"input-main", "output-main"} <= names

    def test_params_tool_schema_is_flat(self):
        from services.node_registry import get_node_class

        cls = get_node_class("jev")
        assert cls.tool_name == "jev"
        # Flat tool-facing schema: no $defs / $ref indirection (agent
        # tool schemas are built from Params; nested models would break
        # provider function-calling).
        schema = cls.Params.model_json_schema()
        assert "$defs" not in schema
        assert "$ref" not in schema
        assert set(schema["required"]) == {"state", "questions"}
