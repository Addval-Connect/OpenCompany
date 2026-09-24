"""RFC-0003 D13 on the node side: choosing a named endpoint.

Agents carry it in their ``provider`` field; the OpenAI-compatible chat-model
node in its ``endpoint`` field. Both resolve to the provider reference the
runtime keys everything by. RLM, which builds its own clients, refuses what
it cannot route instead of sending it to api.openai.com.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

import services.llm  # noqa: F401 — populate the registry
from constants import AI_CHAT_MODEL_TYPES, detect_ai_provider
from nodes.agent.ai_agent import AIAgentParams
from nodes.model._option_loaders import load_ai_providers, load_endpoint_models, load_endpoints
from nodes.model.openai_compatible_chat_model import OpenAICompatibleChatModelNode
from services.llm.endpoints import SavedEndpoint

REF = "openai_compatible:home"
HOME = SavedEndpoint(ref=REF, label="Home vLLM", base_url="http://host:8000/v1", kind="generic", models=["a", "b"])


class TestProviderRef:
    @pytest.mark.parametrize("value", ["openai", "ollama", REF])
    def test_registered_providers_and_named_endpoints_are_accepted(self, value):
        assert AIAgentParams(provider=value).provider == value

    @pytest.mark.parametrize("value", ["openai_compatible", "nope", "ollama:home", ""])
    def test_a_bare_endpoint_id_or_unknown_provider_is_rejected(self, value):
        with pytest.raises(ValidationError):
            AIAgentParams(provider=value)


class TestDetectProvider:
    def test_agents_carry_the_reference_in_their_provider_field(self):
        assert detect_ai_provider("aiAgent", {"provider": REF}) == REF

    def test_the_chat_model_node_carries_it_in_its_endpoint_field(self):
        assert "openaiCompatibleChatModel" in AI_CHAT_MODEL_TYPES
        assert detect_ai_provider("openaiCompatibleChatModel", {"endpoint": REF}) == REF

    def test_no_endpoint_yields_the_bare_id_which_the_unifier_refuses(self):
        assert detect_ai_provider("openaiCompatibleChatModel", {}) == "openai_compatible"


class TestLoaders:
    async def test_providers_then_endpoints_in_declared_order(self):
        with patch("nodes.model._option_loaders._endpoints", AsyncMock(return_value=[HOME])):
            options = await load_ai_providers({})

        values = [o["value"] for o in options]
        assert values[0] == "openai"  # llm_defaults.json order, not import order
        assert "openai_compatible" not in values
        assert options[-1] == {"name": "Home vLLM (OpenAI-compatible)", "value": REF}

    async def test_the_node_lists_endpoints_only(self):
        with patch("nodes.model._option_loaders._endpoints", AsyncMock(return_value=[HOME])):
            assert await load_endpoints({}) == [{"name": "Home vLLM", "value": REF}]

    async def test_models_come_from_the_selected_endpoint(self, monkeypatch):
        auth = AsyncMock()
        auth.get_stored_models = AsyncMock(return_value=["a", "b"])
        monkeypatch.setattr("services.plugin.deps.get_auth_service", lambda: auth)

        assert await load_endpoint_models({"endpoint": REF}) == [
            {"name": "a", "value": "a"},
            {"name": "b", "value": "b"},
        ]
        auth.get_stored_models.assert_awaited_once_with(REF)
        assert await load_endpoint_models({"endpoint": "ollama"}) == []
        assert await load_endpoint_models({}) == []


class TestChatModelNode:
    def test_the_endpoint_is_chosen_first_and_models_follow_it(self):
        schema = OpenAICompatibleChatModelNode.Params.model_json_schema()["properties"]

        assert list(schema)[0] == "endpoint"
        assert schema["endpoint"]["loadOptionsMethod"] == "openaiCompatibleEndpoints"
        assert schema["model"]["loadOptionsMethod"] == "openaiCompatibleModels"
        assert schema["model"]["loadOptionsDependsOn"] == ["endpoint"]
        # A `provider` sibling of `model` would trigger the panel's stored-key effect.
        assert "provider" not in schema

    def test_it_stays_single_purpose(self):
        assert OpenAICompatibleChatModelNode.usable_as_tool is False
        assert "tool" not in OpenAICompatibleChatModelNode.group


class TestRlmGuard:
    @pytest.mark.parametrize("provider", [REF, "ollama"])
    async def test_rlm_refuses_a_provider_it_cannot_route(self, provider):
        from services.rlm.service import RLMService

        result = await RLMService(auth=None).execute("node-1", {"provider": provider, "model": "m", "prompt": "hi"})

        assert result["success"] is False
        assert "cannot run on provider" in result["error"]

    async def test_a_connected_chat_model_is_routed_by_its_own_provider(self):
        # Chat-model nodes carry no ``provider`` field; reading one sent an
        # Anthropic key to the OpenAI backend.
        from services.rlm.adapters import ChatModelExtractor

        backends, kwargs = await ChatModelExtractor.extract(
            [{"node_type": "anthropicChatModel", "parameters": {"model": "claude-x", "api_key": "sk-ant"}}], None
        )

        assert backends == ["anthropic"]
        assert kwargs == [{"model_name": "claude-x", "api_key": "sk-ant"}]

    @pytest.mark.parametrize(
        ("node_type", "parameters"),
        [("openaiCompatibleChatModel", {"endpoint": REF}), ("ollamaChatModel", {})],
    )
    async def test_rlm_refuses_a_connected_chat_model_it_cannot_route(self, node_type, parameters):
        from services.rlm.adapters import ChatModelExtractor

        with pytest.raises(ValueError, match="cannot use the"):
            await ChatModelExtractor.extract(
                [{"node_type": node_type, "parameters": {**parameters, "model": "m", "api_key": "k"}}], None
            )
