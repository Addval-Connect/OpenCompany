"""Blue Process — Recibir evento (Webhook Trigger clone).

Clon de webhookTrigger con un campo adicional `filter` que restringe
la ejecución a eventos cuyo campo `webhookName` (dentro del JSON body)
coincida con el valor configurado.

Formato del evento esperado (Blue Process):
  POST /webhook/<path>
  Body JSON: { "webhookName": "BluedocOrg", "event": "node.rejected", ... }

Si `filter` está vacío se aceptan todos los webhooks que lleguen al path.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.deployment.canary_registry import register_canary_trigger_type
from services.plugin import NodeContext, Operation, TriggerNode, TaskQueue


class BlueflowReceiveParams(BaseModel):
    path: str = Field(
        default="",
        description="Fragmento de URL — el webhook llega a /webhook/{path}",
    )
    filter: str = Field(
        default="",
        title="Filtro webhookName",
        description=(
            "Texto exacto a comparar con el campo `webhookName` del JSON body. "
            "Si se deja vacío se aceptan todos los eventos del path configurado."
        ),
    )
    method: Literal["GET", "POST", "PUT", "DELETE", "ALL"] = Field(
        default="POST",
        description="Método HTTP a aceptar. ALL acepta cualquier método.",
    )
    response_mode: Literal["immediate", "responseNode"] = Field(
        default="immediate",
        description=(
            "immediate: responde 200 OK de inmediato. "
            "responseNode: espera un nodo webhookResponse aguas abajo."
        ),
    )
    authentication: Literal["none", "header"] = Field(
        default="none",
        description="none: sin autenticación. header: requiere un header específico.",
    )
    header_name: str = Field(
        default="X-API-Key",
        description="Nombre del header cuando authentication=header.",
        json_schema_extra={"displayOptions": {"show": {"authentication": ["header"]}}},
    )
    header_value: str = Field(
        default="",
        description="Valor esperado del header cuando authentication=header.",
        json_schema_extra={
            "password": True,
            "displayOptions": {"show": {"authentication": ["header"]}},
        },
    )

    model_config = ConfigDict(extra="ignore")


class BlueflowReceiveOutput(BaseModel):
    method: Optional[str] = None
    path: Optional[str] = None
    headers: Optional[dict] = None
    query: Optional[dict] = None
    body: Optional[str] = None
    json_: Optional[dict] = Field(default=None)

    model_config = ConfigDict(extra="allow")


class BlueflowReceiveNode(TriggerNode):
    type = "blueflowReceive"
    display_name = "Blueflow — Recibir evento"
    subtitle = "Webhook de Blue Process"
    group = ("trigger",)
    description = (
        "Se activa cuando Blue Process envía un webhook al path configurado. "
        "El campo Filtro restringe la ejecución a eventos cuyo `webhookName` "
        "coincida exactamente con el valor indicado."
    )
    component_kind = "trigger"
    task_queue = TaskQueue.TRIGGERS_EVENT
    mode = "event"
    event_type = "webhook_received"

    Params = BlueflowReceiveParams
    Output = BlueflowReceiveOutput

    handles = (
        {"name": "output-main", "kind": "output", "position": "right", "label": "Evento", "role": "main"},
    )
    ui_hints = {"isTrigger": True}

    def build_filter(self, params: BlueflowReceiveParams) -> Callable[[Dict[str, Any]], bool]:
        """Filtra por path y, opcionalmente, por webhookName en el JSON body."""
        expected_path = params.path or ""
        webhook_name_filter = params.filter.strip()

        def matches(event: Dict[str, Any]) -> bool:
            # Path check (same logic as webhookTrigger)
            if expected_path and event.get("path") != expected_path:
                return False

            # webhookName filter — reads from the parsed JSON body
            if webhook_name_filter:
                json_body: Dict[str, Any] = event.get("json") or {}
                if json_body.get("webhookName", "") != webhook_name_filter:
                    return False

            # Header auth check
            if params.authentication == "header" and params.header_value:
                headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
                if headers.get(params.header_name.lower(), "") != params.header_value:
                    return False

            return True

        return matches

    @Operation("wait")
    async def wait(self, ctx: NodeContext, params: BlueflowReceiveParams) -> BlueflowReceiveOutput:
        raise NotImplementedError("Event triggers return via TriggerNode.execute, not the op body")


register_canary_trigger_type(BlueflowReceiveNode.type, "com.opencompany.webhook.received")


__all__ = ["BlueflowReceiveNode"]
