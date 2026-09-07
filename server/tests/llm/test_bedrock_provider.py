"""AWS Bedrock provider invariants.

Bedrock reaches the same Claude models through a different door, and every
interesting failure mode lives in the seam: which of the two authentication
schemes a stored credential selects, which region wins, and what the caller
sees when neither resolves. The message-translation layer is inherited from
``AnthropicProvider`` and is already covered by ``test_messages.py`` /
``test_providers.py`` — the point of subclassing was to not test it twice.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.llm  # noqa: F401 — side-effect import populates the registry
from services.llm.config import LLM_DEFAULTS, curated_models, resolve_temperature
from services.llm.providers.anthropic import AnthropicProvider
from services.llm.providers.bedrock import (
    SIGV4_SENTINEL,
    BedrockProvider,
    resolve_region,
)
from services.llm.registry import all_providers, get_provider
from services.plugin import NodeUserError

pytestmark = pytest.mark.unit


def _provider(api_key: str = "ABSKtest", **kwargs) -> BedrockProvider:
    """Construct with the SDK client patched out."""
    with patch("anthropic.AsyncAnthropicBedrock") as client_cls:
        provider = BedrockProvider(api_key, **kwargs)
    provider._client = MagicMock(name="AsyncAnthropicBedrock")
    provider._construction_kwargs = client_cls.call_args.kwargs
    return provider


def _client_kwargs(api_key: str, **kwargs) -> dict:
    with patch("anthropic.AsyncAnthropicBedrock") as client_cls:
        BedrockProvider(api_key, **kwargs)
    return client_cls.call_args.kwargs


class TestRegistration:
    def test_registered_under_its_own_name(self):
        assert "bedrock" in all_providers()
        assert get_provider("bedrock").factory is BedrockProvider

    def test_reuses_the_anthropic_sdk_exception_hierarchy(self):
        """``AsyncAnthropicBedrock`` raises ``anthropic.APIError`` too, so the
        unifier's one translation site covers it. A missing ref would make
        every Bedrock 4xx surface as an untranslated traceback."""
        spec = get_provider("bedrock")
        assert spec.sdk_exception_refs == ("anthropic:APIError",)
        assert all(issubclass(t, BaseException) for t in spec.sdk_exception_types)

    def test_inherits_the_anthropic_request_translation(self):
        """The whole reason this provider is 200 lines and not 500."""
        assert issubclass(BedrockProvider, AnthropicProvider)
        assert BedrockProvider._split_system is AnthropicProvider._split_system
        assert BedrockProvider._to_api_tool is AnthropicProvider._to_api_tool
        assert BedrockProvider._normalize is AnthropicProvider._normalize

    def test_declares_its_own_provider_name(self):
        """``_model_policy`` and the pricing/registry lookups key off this, so
        inheriting ``"anthropic"`` would read another provider's config."""
        assert BedrockProvider.provider_name == "bedrock"


class TestAuthenticationMode:
    def test_bearer_key_is_passed_as_api_key(self):
        kwargs = _client_kwargs("ABSKsecret")
        assert kwargs["api_key"] == "ABSKsecret"

    def test_sentinel_passes_no_api_key_at_all(self):
        """Passing both a bearer token and AWS credentials is a ValueError
        inside the SDK. The sentinel must therefore vanish, not be forwarded."""
        kwargs = _client_kwargs(SIGV4_SENTINEL)
        assert "api_key" not in kwargs

    @pytest.mark.parametrize("value", ["", "   ", "AWS-SIGV4", " aws-sigv4 "])
    def test_blank_and_cased_sentinel_all_mean_the_credential_chain(self, value):
        assert "api_key" not in _client_kwargs(value)

    def test_missing_boto3_is_a_user_error_not_an_import_crash(self):
        """The SigV4 path needs boto3; without it the SDK raises a bare
        RuntimeError from deep inside signing, which would reach the user as a
        traceback with no hint about what to install or configure."""
        with patch("importlib.util.find_spec", return_value=None):
            with pytest.raises(NodeUserError) as excinfo:
                _client_kwargs(SIGV4_SENTINEL)
        assert "boto3" in str(excinfo.value)

    def test_bearer_mode_does_not_require_boto3(self):
        """An API key is signed by nobody — the deployment should not need the
        AWS SDK at all to use one."""
        with patch("importlib.util.find_spec", return_value=None):
            kwargs = _client_kwargs("ABSKsecret")
        assert kwargs["api_key"] == "ABSKsecret"


class TestRegionResolution:
    def test_explicit_argument_wins(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        assert resolve_region("ap-southeast-2") == "ap-southeast-2"

    def test_aws_region_beats_the_json_default(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "eu-west-1")
        assert resolve_region() == "eu-west-1"

    def test_aws_default_region_is_honoured(self, monkeypatch):
        """The Anthropic SDK reads only ``AWS_REGION``. A host configured the
        long-standing boto way would otherwise fall through to the SDK's
        us-east-1 default and 404 on a model enabled elsewhere."""
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.setenv("AWS_DEFAULT_REGION", "sa-east-1")
        assert resolve_region() == "sa-east-1"

    def test_falls_back_to_the_json_default(self, monkeypatch):
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        expected = LLM_DEFAULTS["providers"]["bedrock"]["aws_region"]
        assert resolve_region() == expected

    def test_blank_env_var_does_not_win(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "  ")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
        assert resolve_region() == "us-west-2"

    def test_region_reaches_the_client(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "us-west-2")
        assert _client_kwargs("ABSKsecret")["aws_region"] == "us-west-2"


class TestChat:
    async def _chat(self, provider, **kwargs):
        with patch.object(
            AnthropicProvider, "chat", new=AsyncMock(return_value="normalized")
        ) as inherited:
            result = await provider.chat([], model="us.anthropic.claude-opus-5", **kwargs)
        return result, inherited

    async def test_delegates_to_the_inherited_request_path(self):
        result, inherited = await self._chat(_provider())
        assert result == "normalized"
        assert inherited.await_count == 1

    async def test_server_side_compaction_is_dropped(self):
        """The compact-2026-01-12 beta is first-party-only; forwarding it to
        bedrock-runtime 400s the entire request rather than degrading."""
        _, inherited = await self._chat(
            _provider(),
            context_management={"type": "compaction", "compact_threshold": 60000},
        )
        assert inherited.await_args.kwargs["context_management"] is None

    async def test_unresolvable_credentials_become_a_user_error(self):
        """The SDK resolves AWS credentials lazily, per request, and reports
        total failure as a bare RuntimeError."""
        provider = _provider(SIGV4_SENTINEL)
        boom = RuntimeError("could not resolve credentials from session")
        with patch.object(AnthropicProvider, "chat", new=AsyncMock(side_effect=boom)):
            with pytest.raises(NodeUserError) as excinfo:
                await provider.chat([], model="us.anthropic.claude-opus-5")
        assert "credentials" in str(excinfo.value).lower()

    async def test_other_runtime_errors_keep_their_traceback(self):
        """Blanket-translating RuntimeError would bury genuine server bugs in
        a one-line WARN with no stack."""
        boom = RuntimeError("something else broke")
        with patch.object(AnthropicProvider, "chat", new=AsyncMock(side_effect=boom)):
            with pytest.raises(RuntimeError) as excinfo:
                await _provider().chat([], model="us.anthropic.claude-opus-5")
        assert not isinstance(excinfo.value, NodeUserError)


class TestFetchModels:
    async def test_returns_the_curated_list_after_a_probe(self):
        provider = _provider()
        provider._client.messages.create = AsyncMock()
        models = await provider.fetch_models("ABSKsecret")

        assert models == curated_models("bedrock")
        # Validated, not merely declared: an unprobed list makes a
        # misconfigured deployment look healthy until the first real run.
        assert provider._client.messages.create.await_count == 1
        probe = provider._client.messages.create.await_args.kwargs
        assert probe["model"] == models[0]
        assert probe["max_tokens"] == 1

    async def test_credential_failure_surfaces_as_a_user_error(self):
        provider = _provider(SIGV4_SENTINEL)
        provider._client.messages.create = AsyncMock(
            side_effect=RuntimeError("could not resolve credentials from session")
        )
        with pytest.raises(NodeUserError):
            await provider.fetch_models(SIGV4_SENTINEL)


class TestModelIdContract:
    def test_curated_models_are_inference_profile_ids(self):
        """Every current Claude model on Bedrock is INFERENCE_PROFILE-only: a
        bare ``anthropic.claude-*`` foundation-model id is rejected at
        invocation, so a curated list of them would be uniformly broken."""
        for model in curated_models("bedrock"):
            assert model.startswith(("us.anthropic.", "global.anthropic.")), model

    def test_default_model_is_curated(self):
        block = LLM_DEFAULTS["providers"]["bedrock"]
        assert block["default_model"] in block["popular_models"]

    def test_profile_ids_classify_as_bedrock_and_bare_ids_do_not(self):
        """``detect_provider_from_model`` returns the first substring hit in
        llm_defaults.json file order, which is why the bedrock block sits
        before anthropic and matches on ``anthropic.`` rather than ``claude``."""
        from services.llm.config import detect_provider_from_model

        assert detect_provider_from_model("us.anthropic.claude-opus-5") == "bedrock"
        assert detect_provider_from_model("global.anthropic.claude-sonnet-5") == "bedrock"
        assert detect_provider_from_model("claude-opus-5") == "anthropic"
        assert detect_provider_from_model("claude-sonnet-4-6") == "anthropic"

    def test_node_type_maps_to_the_bedrock_provider(self):
        """Without the ``detect_ai_provider`` branch, ``bedrockChatModel``
        falls through to the final ``return "openai"`` and the run reads the
        wrong credential — the exact shape of the LM Studio 401 bug."""
        from constants import detect_ai_provider

        assert detect_ai_provider("bedrockChatModel") == "bedrock"

    @pytest.mark.parametrize(
        "model, max_output, context",
        [
            ("us.anthropic.claude-opus-5", 128000, 1048576),
            ("global.anthropic.claude-sonnet-5", 128000, 1048576),
            ("us.anthropic.claude-haiku-4-5-20251001-v1:0", 64000, 200000),
        ],
    )
    def test_token_maps_resolve_for_a_profile_id(self, model, max_output, context):
        """``ModelRegistry`` prefix-matches with ``startswith``, so bare
        family-name keys would silently fall through to ``_default`` (8192 out
        of a 128K cap). ``model_registry.json`` is OpenRouter-sourced and holds
        no ``us.anthropic.*`` ids, so llm_defaults.json is the only source.

        A fresh instance rather than the singleton: ``startup()`` is what loads
        llm_defaults, and the process-wide instance may not have been started.
        """
        from services.model_registry import ModelRegistryService

        registry = ModelRegistryService()
        registry.startup()
        assert registry.get_max_output_tokens(model, "bedrock") == max_output
        assert registry.get_context_length(model, "bedrock") == context
        assert registry.get_temperature_range(model, "bedrock") == (0.0, 1.0)

    def test_pricing_resolves_for_a_profile_id(self):
        """``get_pricing`` reaches these through substring containment; a miss
        would silently bill at the 1.00/5.00 global default.

        Loaded from source by path because ``tests/conftest.py`` replaces
        ``services.pricing`` with a stub whose ``get_pricing`` returns None --
        asserting against that would test nothing.
        """
        import importlib.util
        from pathlib import Path

        source = Path(__file__).resolve().parents[2] / "services" / "pricing.py"
        spec = importlib.util.spec_from_file_location("_real_pricing_for_test", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        service = module.PricingService()

        for model, expected in [
            ("us.anthropic.claude-opus-5", (5.00, 25.00)),
            ("global.anthropic.claude-sonnet-5", (3.00, 15.00)),
            ("us.anthropic.claude-haiku-4-5-20251001-v1:0", (1.00, 5.00)),
        ]:
            pricing = service.get_pricing("bedrock", model)
            assert (pricing.input_per_mtok, pricing.output_per_mtok) == expected, model

    def test_thinking_forces_temperature_one(self):
        """Same rule as first-party Anthropic: budget thinking with any other
        temperature is a 400."""
        assert resolve_temperature({"temperature": 0.2}, "us.anthropic.claude-opus-5", "bedrock", True) == 1.0

    def test_model_policy_matches_profile_prefixed_ids(self):
        """The JSON lists bare family names and ``_model_policy`` matches by
        substring — a startswith-only reading would apply the legacy request
        shape to a model that rejects it."""
        policy = _provider()._model_policy("us.anthropic.claude-opus-5")
        assert policy["adaptive_thinking"] is True
        assert policy["sampling_params"] is False


class TestAgentSelectability:
    @pytest.mark.parametrize(
        "module_path, params_name",
        [
            ("nodes.agent.ai_agent", "AIAgentParams"),
            ("nodes.agent.chat_agent", "ChatAgentParams"),
            ("nodes.agent._specialized", "SpecializedAgentParams"),
        ],
    )
    def test_bedrock_is_selectable_in_every_agent_dropdown(self, module_path, params_name):
        """An agent whose provider is absent from the Literal falls back to
        ``"openai"`` at runtime instead of failing validation."""
        import importlib
        import typing

        module = importlib.import_module(module_path)
        params = getattr(module, params_name)
        allowed = typing.get_args(params.model_fields["provider"].annotation)
        assert "bedrock" in allowed
