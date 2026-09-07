from typing import Optional

from pydantic import Field

from .._base import ChatModelBase, ChatModelParams

from .._credentials import BedrockCredential


class BedrockChatModelParams(ChatModelParams):
    """Same knobs as the first-party Claude node, minus ``top_k``.

    ``top_k`` is declared on ``anthropicChatModel`` but read by nothing on the
    execution path, and it is rejected outright by the 4.7+ generations. It is
    not carried over here.
    """

    thinking_enabled: bool = Field(default=False)
    thinking_budget: Optional[int] = Field(
        default=2048,
        ge=1024,
        le=16000,
        json_schema_extra={"displayOptions": {"show": {"thinking_enabled": [True]}}},
    )


class BedrockChatModelNode(ChatModelBase):
    type = "bedrockChatModel"
    display_name = "Claude on Bedrock"
    subtitle = "Chat Model"
    group = ("model", "tool")
    description = (
        "Anthropic Claude models served by AWS Bedrock — billed through AWS, "
        "with region-scoped inference profile ids (us.anthropic.*)"
    )

    usable_as_tool = True
    tool_name = "bedrock_chat_model"
    tool_description = (
        "Consult Anthropic Claude (hosted on AWS Bedrock) as an advisor — a stronger model the "
        "operator wired in to guide your reasoning. Call AT THE START of any complex task to plan "
        "your approach, WHEN STUCK (errors recurring, approach not converging), and BEFORE "
        "DECLARING DONE to sanity-check completeness. Pose ONE focused question in `prompt` — "
        "include the context the advisor needs (the advisor cannot see your conversation). Do NOT "
        "set `model`, `api_key`, `temperature`, or other fields; the operator configured them. "
        "Returns brief tactical guidance — you do the work."
    )

    credentials = (BedrockCredential,)
    Params = BedrockChatModelParams
