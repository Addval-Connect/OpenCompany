"""Blue Process — Webhook Trigger node.

Receives events dispatched by Blue Process (record.created, node.completed, …)
and fires a workflow execution for each one.

Blue Process signs every delivery with HMAC-SHA256:
  X-Blueflow-Signature: sha256=<hex>
This node verifies the signature when a secret is configured so the workflow
only fires for genuine events.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from services.plugin import (
    NodeContext,
    TriggerNode,
    Operation,
    TaskQueue,
)
from services.event_waiter import register_filter_builder
from services.deployment.canary_registry import register_canary_trigger_type


BLUEFLOW_EVENTS = [
    "record.created",
    "node.activated",
    "node.completed",
    "node.rejected",
    "node.commented",
    "blue.evaluated",
    "record.completed",
    "record.rejected",
]

EVENT_LABELS = {
    "record.created":   "Expediente creado",
    "node.activated":   "Etapa activada",
    "node.completed":   "Etapa completada",
    "node.rejected":    "Etapa rechazada",
    "node.commented":   "Comentario / archivo adjunto",
    "blue.evaluated":   "Blue evaluó criterios",
    "record.completed": "Expediente completado (éxito)",
    "record.rejected":  "Expediente rechazado (fallo)",
}


class BlueflowReceiveParams(BaseModel):
    events: List[str] = Field(
        default_factory=lambda: ["record.created"],
        title="Eventos a escuchar",
        description=(
            "Selecciona los eventos de Blue Process que disparan este workflow. "
            "Deja vacío para recibir todos."
        ),
        json_schema_extra={
            "multiselect": True,
            "options": [{"value": k, "label": v} for k, v in EVENT_LABELS.items()],
        },
    )
    secret: str = Field(
        default="",
        title="Webhook Secret",
        description=(
            "Secreto configurado en Blue Process al registrar el webhook. "
            "Cuando está presente, se verifica la firma HMAC-SHA256 de cada entrega. "
            "Deja vacío para omitir la verificación (no recomendado en producción)."
        ),
        json_schema_extra={"secret": True, "password": True},
    )


class BlueflowReceiveOutput(BaseModel):
    event: str = Field(description="Tipo de evento (record.created, node.completed, …)")
    record_id: Optional[str] = Field(default=None, description="ID del expediente")
    record_name: Optional[str] = Field(default=None, description="Nombre del expediente")
    node_id: Optional[str] = Field(default=None, description="ID del nodo de flujo")
    node_name: Optional[str] = Field(default=None, description="Nombre de la etapa")
    actor: Optional[str] = Field(default=None, description="Actor que disparó el evento")
    organization_id: Optional[str] = Field(default=None, description="ID de la organización")
    timestamp: Optional[str] = Field(default=None, description="Timestamp ISO del evento")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Payload completo del webhook")


class BlueflowReceiveNode(TriggerNode):
    type = "blueflowReceive"
    display_name = "Blueflow — Recibir evento"
    subtitle = "Webhook de Blue Process"
    group = ("trigger",)
    description = (
        "Se activa cuando Blue Process dispara un webhook. "
        "Recibe eventos como 'expediente creado', 'etapa completada', etc. "
        "y pasa el payload al flujo."
    )
    task_queue = TaskQueue.TRIGGERS_EVENT

    Params = BlueflowReceiveParams
    Output = BlueflowReceiveOutput

    handles = (
        {
            "name": "output-main",
            "kind": "output",
            "position": "right",
            "label": "Evento",
        },
    )
    ui_hints = {"isTrigger": True}

    @Operation("trigger")
    async def trigger(self, ctx: NodeContext, params: BlueflowReceiveParams) -> BlueflowReceiveOutput:
        payload: Dict[str, Any] = ctx.raw.get("_trigger_payload", {})
        return BlueflowReceiveOutput(
            event=payload.get("event", ""),
            record_id=payload.get("recordId"),
            record_name=payload.get("recordName"),
            node_id=payload.get("nodeId"),
            node_name=payload.get("nodeName"),
            actor=payload.get("actor"),
            organization_id=payload.get("organizationId"),
            timestamp=payload.get("timestamp"),
            payload=payload,
        )


# ─── Webhook intake ──────────────────────────────────────────────────────────
# Blue Process delivers to the generic /webhook/<path> route.
# The path format is: /webhook/blueflow/<nodeId>
# The webhook verifier and filter are registered below.

def _build_blueflow_filter(params: Dict[str, Any]):
    """Build filter function for blueflowReceive node parameters."""
    import hmac
    import hashlib

    allowed_events: List[str] = params.get("events") or []
    secret: str = params.get("secret", "").strip()

    def _filter(data: Dict[str, Any]) -> bool:
        # Verify HMAC signature when a secret is configured
        if secret:
            sig_header: str = data.get("_headers", {}).get("x-blueflow-signature", "")
            raw_body: bytes = data.get("_raw_body", b"")
            expected = "sha256=" + hmac.new(
                secret.encode(), raw_body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(sig_header, expected):
                return False

        # Event type filter (empty = accept all)
        event: str = data.get("event", "")
        if allowed_events and event not in allowed_events:
            return False
        return True

    return _filter


register_canary_trigger_type("blueflowReceive", "com.blueflow.webhook.received")
register_filter_builder("blueflowReceive", _build_blueflow_filter)


__all__ = ["BlueflowReceiveNode"]
