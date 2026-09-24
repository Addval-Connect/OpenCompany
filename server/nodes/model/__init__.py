"""Plugins for the 'model' palette group. See ../__init__.py for the package layout.

Also owns the LLM provider dropdowns: the agent ``provider`` field and the
OpenAI-compatible chat-model node load their options from here, because
this folder owns the credentials those options are built from.
"""

from services.ws_handler_registry import register_option_loader

from ._option_loaders import load_ai_providers, load_endpoint_models, load_endpoints

register_option_loader("aiProviders", load_ai_providers)
register_option_loader("openaiCompatibleEndpoints", load_endpoints)
register_option_loader("openaiCompatibleModels", load_endpoint_models)
