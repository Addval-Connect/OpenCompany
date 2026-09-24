"""The ``provider`` field every LLM agent declares.

A provider reference: a registered provider id, or a named
OpenAI-compatible endpoint ``openai_compatible:<slug>`` (RFC-0003 D13).
Options come from the ``aiProviders`` loader (``nodes/model``), so a newly
saved endpoint appears without a NodeSpec change. The value travels as-is
through key injection, Temporal payloads and the unifier, which is why it
is one string rather than a provider plus a separate endpoint field.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, Field


def _check_provider_ref(value: str) -> str:
    """Accept a registered provider, or a named endpoint of the endpoint provider."""
    from services.llm.config import ENDPOINT_PROVIDER, split_provider_ref
    from services.llm.registry import has_provider

    name, slug = split_provider_ref(value)
    if not has_provider(name) or (name == ENDPOINT_PROVIDER) != bool(slug):
        raise ValueError(f"unknown LLM provider {value!r}")
    return value


ProviderRef = Annotated[
    str,
    AfterValidator(_check_provider_ref),
    Field(json_schema_extra={"loadOptionsMethod": "aiProviders"}),
]


__all__ = ["ProviderRef"]
