"""Dropdown loaders for LLM provider and endpoint selection.

The provider dropdown was a ``Literal`` on each agent's Params. A saved
endpoint cannot be a literal, so the options come from here instead and a
new endpoint appears without a NodeSpec change. Imports no LLM SDK: these
run on every parameter-panel render.
"""

from __future__ import annotations

from typing import Any, Dict, List


async def _endpoints():
    from services.llm.endpoints import list_endpoints
    from services.plugin.deps import get_auth_service

    return await list_endpoints(get_auth_service())


async def load_ai_providers(params: Dict[str, Any] | None = None) -> List[Dict[str, str]]:
    """Every registered provider, then one option per saved endpoint.

    Ordered as ``llm_defaults.json`` lists the providers, so the order is
    declared rather than an accident of import order. The bare
    ``openai_compatible`` id is not an option: it only exists as endpoints.
    """
    from services.llm.config import ENDPOINT_PROVIDER, LLM_DEFAULTS
    from services.llm.registry import all_providers

    blocks = LLM_DEFAULTS.get("providers", {})
    registered = set(all_providers()) - {ENDPOINT_PROVIDER}
    ordered = [name for name in blocks if name in registered]
    ordered += sorted(registered - set(ordered))
    options = [{"name": blocks.get(name, {}).get("display_name") or name, "value": name} for name in ordered]
    options += [{"name": f"{e.label} (OpenAI-compatible)", "value": e.ref} for e in await _endpoints()]
    return options


async def load_endpoints(params: Dict[str, Any] | None = None) -> List[Dict[str, str]]:
    """Saved endpoints only, for the OpenAI-compatible chat-model node."""
    return [{"name": e.label, "value": e.ref} for e in await _endpoints()]


async def load_endpoint_models(params: Dict[str, Any] | None = None) -> List[Dict[str, str]]:
    """Models the selected endpoint listed when it was saved."""
    from services.llm.config import ENDPOINT_PROVIDER, split_provider_ref
    from services.plugin.deps import get_auth_service

    ref = (params or {}).get("endpoint") or ""
    name, slug = split_provider_ref(ref)
    if name != ENDPOINT_PROVIDER or not slug:
        return []
    return [{"name": model, "value": model} for model in await get_auth_service().get_stored_models(ref)]


__all__ = ["load_ai_providers", "load_endpoint_models", "load_endpoints"]
