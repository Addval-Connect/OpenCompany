"""Blue Process — API Action node.

Sends requests to the Blue Process v1 API on behalf of an agent.
Auth: Bearer <api_key> via the Credentials panel.

Supported operations (mirrors /api/v1/*):
  - list_processes       GET  /processes
  - get_process          GET  /processes/:id
  - list_records         GET  /records
  - create_record        POST /records
  - get_record           GET  /records/:id
  - get_record_nodes     GET  /records/:id/nodes
  - complete_node        POST /records/:id/nodes/:nodeId/complete
  - reject_node          POST /records/:id/nodes/:nodeId/reject
  - comment_node         POST /records/:id/nodes/:nodeId/comment
  - list_webhooks        GET  /webhooks
  - register_webhook     POST /webhooks
  - delete_webhook       DELETE /webhooks/:id
  - test_webhook         POST /webhooks/:id/test
"""
from __future__ import annotations

import httpx
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.plugin import (
    ActionNode,
    NodeContext,
    NodeUserError,
    Operation,
    TaskQueue,
)
from services.plugin.credential import ApiKeyCredential, ProbeResult


# ─── Credential ──────────────────────────────────────────────────────────────

class BlueflowCredential(ApiKeyCredential):
    id = "blueflow"
    display_name = "Blue Process API Key"
    category = "Productivity"
    key_location = "bearer"  # injects Authorization: Bearer <key>
    docs_url = "http://localhost:3000"

    @classmethod
    async def _probe(cls, api_key: str) -> ProbeResult:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "http://localhost:3000/api/v1/processes",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if r.status_code == 200:
                return ProbeResult(valid=True, message="Conectado")
            if r.status_code == 401:
                return ProbeResult(valid=False, message="API Key inválida")
            return ProbeResult(valid=False, message=f"HTTP {r.status_code}")
        except Exception as exc:
            return ProbeResult(valid=False, message=f"No se pudo conectar: {exc}")


# ─── Params & Output ─────────────────────────────────────────────────────────

BlueflowOperation = Literal[
    "list_processes",
    "get_process",
    "list_records",
    "create_record",
    "get_record",
    "get_record_nodes",
    "complete_node",
    "reject_node",
    "comment_node",
    "list_webhooks",
    "register_webhook",
    "delete_webhook",
    "test_webhook",
]


class BlueflowActionParams(BaseModel):
    api_url: str = Field(
        default="http://localhost:3000",
        title="URL de la API",
        description="URL base de Blue Process (sin /api/v1).",
    )
    operation: BlueflowOperation = Field(
        default="list_records",
        title="Operación",
        description="Qué acción ejecutar en Blue Process.",
    )
    # IDs opcionales según la operación
    process_id: Optional[str] = Field(
        default=None,
        title="ID del Proceso",
        description="Requerido para get_process y create_record.",
    )
    record_id: Optional[str] = Field(
        default=None,
        title="ID del Expediente",
        description="Requerido para get_record, get_record_nodes, complete_node, reject_node, comment_node.",
    )
    node_id: Optional[str] = Field(
        default=None,
        title="ID del Nodo",
        description="Requerido para complete_node, reject_node, comment_node.",
    )
    webhook_id: Optional[str] = Field(
        default=None,
        title="ID del Webhook",
        description="Requerido para delete_webhook y test_webhook.",
    )
    # Cuerpo para operaciones POST
    body: Optional[Dict[str, Any]] = Field(
        default=None,
        title="Cuerpo (JSON)",
        description=(
            "Payload JSON para la operación. Ejemplos:\n"
            "create_record: {\"processId\": \"…\", \"name\": \"…\", \"fields\": {}}\n"
            "complete_node: {\"comment\": \"Aprobado\"}\n"
            "register_webhook: {\"url\": \"https://…\", \"events\": [\"record.created\"]}"
        ),
        json_schema_extra={"type": "object", "uiType": "json"},
    )

    model_config = ConfigDict(extra="ignore")


class BlueflowActionOutput(BaseModel):
    ok: bool
    operation: str
    status_code: int
    data: Any = None
    error: Optional[str] = None

    model_config = ConfigDict(extra="allow")


# ─── Node ─────────────────────────────────────────────────────────────────────

class BlueflowActionNode(ActionNode):
    type = "blueflowAction"
    display_name = "Blueflow — Acción API"
    subtitle = "API v1 de Blue Process"
    group = ("tool", "ai")
    description = (
        "Ejecuta operaciones en la API v1 de Blue Process: "
        "listar procesos, crear expedientes, completar etapas, "
        "administrar webhooks y más. "
        "Requiere una API Key configurada en Credentials."
    )
    task_queue = TaskQueue.REST_API
    credentials = (BlueflowCredential,)

    Params = BlueflowActionParams
    Output = BlueflowActionOutput

    def _base(self, params: BlueflowActionParams) -> str:
        return params.api_url.rstrip("/") + "/api/v1"

    # ── Operation ─────────────────────────────────────────────────────────

    @Operation("call")
    async def call(self, ctx: NodeContext, params: BlueflowActionParams) -> BlueflowActionOutput:
        base = self._base(params)
        op = params.operation
        body = params.body or {}

        try:
            async with ctx.connection(BlueflowCredential.id) as conn:
                if op == "list_processes":
                    r = await conn.get(f"{base}/processes")
                elif op == "get_process":
                    if not params.process_id:
                        raise NodeUserError("process_id es requerido para get_process")
                    r = await conn.get(f"{base}/processes/{params.process_id}")
                elif op == "list_records":
                    r = await conn.get(f"{base}/records")
                elif op == "create_record":
                    r = await conn.post(f"{base}/records", json=body)
                elif op == "get_record":
                    if not params.record_id:
                        raise NodeUserError("record_id es requerido para get_record")
                    r = await conn.get(f"{base}/records/{params.record_id}")
                elif op == "get_record_nodes":
                    if not params.record_id:
                        raise NodeUserError("record_id es requerido para get_record_nodes")
                    r = await conn.get(f"{base}/records/{params.record_id}/nodes")
                elif op == "complete_node":
                    if not params.record_id or not params.node_id:
                        raise NodeUserError("record_id y node_id son requeridos para complete_node")
                    r = await conn.post(f"{base}/records/{params.record_id}/nodes/{params.node_id}/complete", json=body)
                elif op == "reject_node":
                    if not params.record_id or not params.node_id:
                        raise NodeUserError("record_id y node_id son requeridos para reject_node")
                    r = await conn.post(f"{base}/records/{params.record_id}/nodes/{params.node_id}/reject", json=body)
                elif op == "comment_node":
                    if not params.record_id or not params.node_id:
                        raise NodeUserError("record_id y node_id son requeridos para comment_node")
                    r = await conn.post(f"{base}/records/{params.record_id}/nodes/{params.node_id}/comment", json=body)
                elif op == "list_webhooks":
                    r = await conn.get(f"{base}/webhooks")
                elif op == "register_webhook":
                    r = await conn.post(f"{base}/webhooks", json=body)
                elif op == "delete_webhook":
                    if not params.webhook_id:
                        raise NodeUserError("webhook_id es requerido para delete_webhook")
                    r = await conn.delete(f"{base}/webhooks/{params.webhook_id}")
                elif op == "test_webhook":
                    if not params.webhook_id:
                        raise NodeUserError("webhook_id es requerido para test_webhook")
                    r = await conn.post(f"{base}/webhooks/{params.webhook_id}/test")
                else:
                    raise NodeUserError(f"Operación desconocida: {op}")

        except NodeUserError:
            raise
        except Exception as exc:
            raise NodeUserError(f"Error al llamar a Blue Process: {exc}") from exc

        ok = r.status_code < 400
        data = None
        try:
            data = r.json()
        except Exception:
            data = r.text or None

        if not ok:
            msg = (data.get("error") or data.get("message") or str(data)) if isinstance(data, dict) else str(data)
            raise NodeUserError(f"Blue Process respondió HTTP {r.status_code}: {msg}")

        return BlueflowActionOutput(ok=True, operation=op, status_code=r.status_code, data=data)


__all__ = ["BlueflowActionNode", "BlueflowCredential"]
