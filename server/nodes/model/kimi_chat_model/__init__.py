from .._base import ChatModelBase

from .._credentials import KimiCredential


class KimiChatModelNode(ChatModelBase):
    type = "kimiChatModel"
    display_name = "Kimi"
    subtitle = "Chat Model"
    group = ("model",)
    description = "Kimi models by Moonshot AI (K3 1M context; K2 tiers 256K, thinking on by default)"
    credentials = (KimiCredential,)
