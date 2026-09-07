"""AWS Bedrock provider for Anthropic models.

Bedrock serves the same Messages API as Anthropic's first-party endpoint, so
this provider subclasses ``AnthropicProvider`` and replaces exactly one thing:
the client. Message translation, tool compilation, thinking handling and
``_normalize`` are inherited verbatim — duplicating them would guarantee the
two drift apart on the next Claude generation.

Two authentication modes, both resolved from the single ``api_key`` slot that
``ChatUnifier`` is able to hand a factory (the factory is synchronous and
cannot await the auth service, so there is no second credential channel):

``aws-sigv4``
    The documented sentinel meaning "sign with the host's own AWS credential
    chain" — env vars, ``~/.aws/credentials``, ``AWS_PROFILE``, SSO cache, or
    the EC2 instance role. Needs ``boto3``. An empty credential is treated the
    same way, since a blank value can only mean "use the ambient chain".

anything else
    A Bedrock **API key** (bearer token, the ``ABSK…`` form from the Bedrock
    console). Sent as ``Authorization: Bearer …``; no ``boto3`` involved.

Never both: the SDK raises ``ValueError`` if bearer and SigV4 credentials are
supplied together, which is why the sentinel exists rather than "empty means
SigV4, non-empty means both".

Model ids are **inference profile** ids, not foundation-model ids — every
current Claude model on Bedrock is ``INFERENCE_PROFILE``-only, so
``us.anthropic.claude-opus-5`` invokes and the bare ``anthropic.claude-opus-5``
does not.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any, Dict, List, Optional

from core.logging import get_logger
from services.llm.protocol import LLMResponse, Message, ThinkingConfig, ToolDef
from services.llm.providers.anthropic import AnthropicProvider
from services.plugin import NodeUserError

logger = get_logger(__name__)

# The credential value that means "there is no credential here; use the AWS
# credential chain". A sentinel rather than an empty string because
# ``services/ai.py`` refuses to run any agent whose provider has no stored
# api_key at all (three separate ``if not api_key`` gates) — the same reason
# the local-LLM credentials store the literal "ollama".
SIGV4_SENTINEL = "aws-sigv4"

_MISSING_BOTO3 = (
    "AWS Bedrock is set to sign with the host's AWS credential chain, but "
    "boto3 is not installed in the server environment. Install it (it is a "
    "declared dependency — re-run `uv sync` from server/), or store a Bedrock "
    "API key in the Bedrock credential instead of the 'aws-sigv4' sentinel."
)

_UNRESOLVED_CREDENTIALS = (
    "AWS Bedrock could not resolve AWS credentials. Configure them on the "
    "server host (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, an AWS_PROFILE in "
    "~/.aws, or an instance role), or store a Bedrock API key in the Bedrock "
    "credential instead of the 'aws-sigv4' sentinel."
)


def _uses_credential_chain(api_key: Optional[str]) -> bool:
    # Stripped before the emptiness check too: a whitespace-only value is a
    # stray paste, not a bearer token, and forwarding it as one produces a 403
    # that reads as "your AWS account denied this".
    value = (api_key or "").strip()
    return not value or value.lower() == SIGV4_SENTINEL


def resolve_region(explicit: Optional[str] = None) -> Optional[str]:
    """Region precedence, highest first.

    ``AWS_DEFAULT_REGION`` is checked here on purpose: the Anthropic SDK reads
    only ``AWS_REGION``, and a host configured the long-standing boto way would
    otherwise silently fall back to the SDK's ``us-east-1`` default and 404 on
    a model that is only enabled elsewhere.

    Returning ``None`` hands the decision back to the SDK (boto3 session
    region, then its warn-and-default).
    """

    from services.llm.config import LLM_DEFAULTS

    candidates = (
        explicit,
        os.environ.get("AWS_REGION"),
        os.environ.get("AWS_DEFAULT_REGION"),
        LLM_DEFAULTS.get("providers", {}).get("bedrock", {}).get("aws_region"),
    )
    for candidate in candidates:
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return None


class BedrockProvider(AnthropicProvider):
    provider_name = "bedrock"

    def __init__(
        self,
        api_key: str,
        *,
        proxy_url: Optional[str] = None,
        max_retries: int = 2,
        aws_region: Optional[str] = None,
    ):
        import anthropic

        kwargs: Dict[str, Any] = {"max_retries": max(0, int(max_retries))}

        region = resolve_region(aws_region)
        if region:
            kwargs["aws_region"] = region

        if _uses_credential_chain(api_key):
            if importlib.util.find_spec("boto3") is None:
                raise NodeUserError(_MISSING_BOTO3)
        else:
            # Bearer token. Passing it alongside any aws_* credential is a
            # ValueError inside the SDK, so nothing else goes in.
            kwargs["api_key"] = api_key.strip()

        if proxy_url:
            # A proxy would break SigV4 (the signature covers the host) and
            # buys nothing in bearer mode, where the endpoint is already a
            # regional AWS URL. Honouring it silently would produce 403s that
            # look like bad credentials.
            logger.warning(
                "ignoring configured proxy for AWS Bedrock",
                provider=self.provider_name,
            )

        self._client = anthropic.AsyncAnthropicBedrock(**kwargs)

    async def chat(
        self,
        messages: List[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        thinking: Optional[ThinkingConfig] = None,
        tools: Optional[List[ToolDef]] = None,
        context_management: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        """Inherited Anthropic request path, minus server-side compaction.

        The ``compact-2026-01-12`` beta is a first-party Anthropic API feature
        and is not offered on ``bedrock-runtime``; forwarding it would 400 the
        whole request. Dropping it here costs nothing the agent runtime relies
        on — its own client-side compaction (``CompactionService``) is a
        separate, provider-neutral path.
        """

        if context_management:
            logger.debug(
                "dropping server-side context management (unsupported on Bedrock)",
                provider=self.provider_name,
                model=model,
            )

        try:
            return await super().chat(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking=thinking,
                tools=tools,
                context_management=None,
            )
        except RuntimeError as error:
            # The SDK resolves AWS credentials lazily, per request, and reports
            # a total failure as a bare RuntimeError. Every other RuntimeError
            # is a genuine bug and must keep its traceback.
            if "credentials" in str(error).lower():
                raise NodeUserError(_UNRESOLVED_CREDENTIALS) from error
            raise

    async def fetch_models(self, api_key: str) -> List[str]:
        """Curated ids validated by a one-token call.

        Bedrock's model inventory lives on the ``bedrock`` control plane, not
        on ``bedrock-runtime``, so the Messages client cannot list it and a
        bearer token is not accepted there at all. Same shape as the
        ``supports_model_listing: false`` providers: return the curated list,
        but only after proving the credential and region actually work — an
        unvalidated list would make a misconfigured deployment look healthy
        until the first real run.
        """

        from services.llm.config import curated_models

        curated = curated_models(self.provider_name)
        if not curated:
            raise ValueError(
                "llm_defaults.json providers.bedrock declares no popular_models, "
                "so there is no model list to serve."
            )

        try:
            await self._client.messages.create(
                model=curated[0],
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
        except RuntimeError as error:
            if "credentials" in str(error).lower():
                raise NodeUserError(_UNRESOLVED_CREDENTIALS) from error
            raise
        return curated


# ---------------------------------------------------------------------------
# Plugin self-registration
# ---------------------------------------------------------------------------
# ``AsyncAnthropicBedrock`` raises the same ``anthropic.APIError`` hierarchy as
# the first-party client, so the ref is identical — and still lazy, so
# registering this provider imports neither anthropic nor boto3.

from services.llm.registry import ProviderSpec, register_provider

register_provider(
    ProviderSpec(
        name="bedrock",
        factory=BedrockProvider,
        sdk_exception_refs=("anthropic:APIError",),
    )
)
