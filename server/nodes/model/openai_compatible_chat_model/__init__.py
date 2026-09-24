"""OpenAI-compatible chat model: one of the user's named endpoints.

Pick an endpoint saved under Credentials > OpenAI-compatible (llama.cpp,
vLLM, a LiteLLM proxy, a second Ollama host, ...) and a model it serves.
The endpoint's reference, ``openai_compatible:<slug>``, is the provider the
runtime resolves (``constants.detect_ai_provider``), so its stored key and
resolved URL are used with no per-node configuration.
"""

from pydantic import BaseModel, Field

from .._base import ChatModelBase, ChatModelParams
from .._credentials import OpenAICompatibleCredential


class _EndpointField(BaseModel):
    # Pydantic lays fields out in reversed-MRO order, so declaring the
    # endpoint on a base listed after ChatModelParams renders it first,
    # above the prompt and model, where it is chosen.
    endpoint: str = Field(
        default="",
        description="Saved endpoint to send requests to.",
        json_schema_extra={"loadOptionsMethod": "openaiCompatibleEndpoints"},
    )


class OpenAICompatibleChatModelParams(ChatModelParams, _EndpointField):
    # The field is ``endpoint``, not ``provider``: a ``provider`` sibling of
    # ``model`` triggers the parameter panel's stored-key effect, which
    # would copy the endpoint's key into this node's ``api_key``.
    model: str = Field(
        default="",
        json_schema_extra={
            "placeholder": "Select a model...",
            "loadOptionsMethod": "openaiCompatibleModels",
            "loadOptionsDependsOn": ["endpoint"],
        },
    )


class OpenAICompatibleChatModelNode(ChatModelBase):
    type = "openaiCompatibleChatModel"
    display_name = "OpenAI-compatible"
    subtitle = "Chat Model"
    group = ("model",)
    description = "Any OpenAI-compatible server saved as a named endpoint: llama.cpp, vLLM, a LiteLLM proxy, and more"

    credentials = (OpenAICompatibleCredential,)
    Params = OpenAICompatibleChatModelParams
