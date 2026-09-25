"""RFC-0003 §6 / AG3: rooting a user-supplied base URL by asking the server.

The probe goes through the real openai SDK (``models.list()``), mocked at the
HTTP layer, because "the probe is the call execution makes" is the property
under test.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from services.llm.endpoints import redact_url, resolve_base_url, unconfigured_endpoint_message

MODELS = {
    "object": "list",
    "data": [{"id": "qwen3", "object": "model", "created": 0, "owned_by": "local"}],
}


@respx.mock
async def test_a_list_at_the_root_is_adopted_as_entered():
    respx.get("http://host:8080/models").mock(return_value=httpx.Response(200, json=MODELS))
    v1 = respx.get("http://host:8080/v1/models")

    resolved = await resolve_base_url("http://host:8080/", api_key="k")

    assert resolved.ok
    assert resolved.base_url == "http://host:8080"
    assert resolved.rewritten is False
    assert [m.id for m in resolved.models] == ["qwen3"]
    assert not v1.called


@respx.mock
async def test_a_200_that_is_not_a_list_is_not_adopted():
    """LM Studio answers routes it does not serve with HTTP 200 (RFC-0003 §2.1)."""
    respx.get("http://host:1234/models").mock(
        return_value=httpx.Response(200, json={"error": "Unexpected endpoint or method. (GET /models)"})
    )
    respx.get("http://host:1234/v1/models").mock(return_value=httpx.Response(200, json=MODELS))

    resolved = await resolve_base_url("http://host:1234", api_key="lm-studio")

    assert resolved.base_url == "http://host:1234/v1"
    assert resolved.rewritten is True


@respx.mock
async def test_a_rejected_key_at_the_root_does_not_stop_a_list_under_v1():
    respx.get("http://gateway/models").mock(return_value=httpx.Response(401, json={"error": {"message": "no"}}))
    respx.get("http://gateway/v1/models").mock(return_value=httpx.Response(200, json=MODELS))

    resolved = await resolve_base_url("http://gateway", api_key="k")

    assert resolved.base_url == "http://gateway/v1"


@respx.mock
async def test_a_key_rejected_everywhere_is_reported_and_nothing_adopted():
    respx.get("http://vllm:8000/models").mock(return_value=httpx.Response(404))
    respx.get("http://vllm:8000/v1/models").mock(return_value=httpx.Response(401, json={"error": "Unauthorized"}))

    resolved = await resolve_base_url("http://vllm:8000", api_key="wrong")

    assert not resolved.ok
    assert "rejected the API key" in resolved.reason
    assert "http://vllm:8000/v1" in resolved.reason


@respx.mock
async def test_nothing_answering_names_both_candidates():
    respx.get("http://host/models").mock(return_value=httpx.Response(404))
    respx.get("http://host/v1/models").mock(return_value=httpx.Response(404))

    resolved = await resolve_base_url("http://host", api_key="k")

    assert not resolved.ok
    assert "http://host or http://host/v1" in resolved.reason


@respx.mock
async def test_a_connection_failure_stops_after_one_candidate():
    root = respx.get("http://down:9/models").mock(side_effect=httpx.ConnectError("refused"))
    v1 = respx.get("http://down:9/v1/models")

    resolved = await resolve_base_url("http://down:9", api_key="k")

    assert not resolved.ok
    assert "Could not reach http://down:9" in resolved.reason
    assert root.call_count == 1
    assert not v1.called


@respx.mock
async def test_input_ending_in_v1_is_the_only_candidate():
    v1 = respx.get("http://host/v1/models").mock(return_value=httpx.Response(404))
    doubled = respx.get("http://host/v1/v1/models")

    resolved = await resolve_base_url("http://host/v1", api_key="k")

    assert not resolved.ok
    assert v1.called
    assert not doubled.called


async def test_a_scheme_less_url_is_refused_not_guessed():
    resolved = await resolve_base_url("localhost:8080", api_key="k")

    assert not resolved.ok
    assert "http://" in resolved.reason


@respx.mock
async def test_the_probe_sends_the_resolved_key_as_a_bearer_token():
    route = respx.get("http://host/models").mock(return_value=httpx.Response(200, json=MODELS))

    await resolve_base_url("http://host", api_key="sk-no-key-required")

    assert route.calls.last.request.headers["authorization"] == "Bearer sk-no-key-required"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://user:pass@host:8080/v1?key=secret#frag", "http://host:8080/v1"),
        ("https://api.example.com/v1", "https://api.example.com/v1"),
        ("http://[::1]:1234/v1", "http://[::1]:1234/v1"),
        ("http://host:notaport/v1", "http://host/v1"),
        (None, ""),
    ],
)
def test_redact_url_drops_what_can_carry_a_credential(url, expected):
    assert redact_url(url) == expected


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("openai_compatible:home", "The OpenAI-compatible endpoint 'home' is not configured. Add it under Credentials."),
        ("openai_compatible", "Choose an OpenAI-compatible endpoint. Save one under Credentials first if there is none."),
        ("openai", None),
        ("ollama", None),
    ],
)
def test_an_unsaved_endpoint_is_named_as_such(provider, expected):
    assert unconfigured_endpoint_message(provider) == expected
