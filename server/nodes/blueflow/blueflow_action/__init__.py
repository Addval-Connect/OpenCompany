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
from typing import Any, Dict, Literal, Optional

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
    key_location = "bearer"           # injects Authorization: Bearer <key>
    extra_fields = ("blueflow_api_url",)   # URL del servidor se guarda junto a la key
    docs_url = "https://github.com/Addval-Connect/blueprocess"

    @classmethod
    async def validate(cls, data: dict) -> dict:
        """Sobreescribe para pasar blueflow_api_url al probe y guardarla."""
        from core.container import container
        from services.status_broadcaster import get_status_broadcaster
        import time as _time

        api_key = (data.get("api_key") or "").strip()
        api_url = (data.get("blueflow_api_url") or "http://localhost:3000").rstrip("/")
        session_id = data.get("session_id", "default")

        if not api_key:
            return {"success": False, "valid": False, "error": "blueflow api_key required"}

        try:
            result = await cls._probe(api_key, api_url=api_url)
        except Exception as exc:
            from services.plugin.credential import classify_credential_error
            result = classify_credential_error(exc, display_name=cls.display_name)

        auth_service = container.auth_service()
        if result.valid:
            await auth_service.store_api_key(
                provider=cls.id, api_key=api_key,
                session_id=session_id,
                models=result.models, model_params=result.model_params,
            )
            # Guardar la URL como extra field
            await auth_service.store_api_key(
                provider="blueflow_api_url", api_key=api_url,
                session_id=session_id, models=[], model_params={},
            )

        broadcaster = get_status_broadcaster()
        await broadcaster.update_api_key_status(
            provider=cls.id, valid=result.valid,
            message=result.message, has_key=result.valid, models=result.models,
        )

        return {
            "success": True, "provider": cls.id,
            "valid": result.valid, "message": result.message,
            "models": result.models, "timestamp": _time.time(),
            **result.extra,
        }

    @classmethod
    async def _probe(cls, api_key: str, api_url: str = "http://localhost:3000") -> ProbeResult:
        url = api_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{url}/api/v1/processes",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if r.status_code == 200:
                procs = r.json()
                n = len(procs) if isinstance(procs, list) else "?"
                return ProbeResult(valid=True, message=f"Conectado — {n} proceso(s)")
            if r.status_code == 401:
                return ProbeResult(valid=False, message="API Key inválida o expirada")
            return ProbeResult(valid=False, message=f"Error HTTP {r.status_code}")
        except Exception as exc:
            return ProbeResult(valid=False, message=f"No se pudo conectar a {url}: {exc}")


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

    def _base(self, params: BlueflowActionParams, secrets: Optional[Dict[str, Any]] = None) -> str:
        # Prefer params.api_url; fall back to the URL saved in Credentials
        url = params.api_url or (secrets or {}).get("blueflow_api_url") or "http://localhost:3000"
        return url.rstrip("/") + "/api/v1"

    # ── Operation ─────────────────────────────────────────────────────────

    @Operation("call")
    async def call(self, ctx: NodeContext, params: BlueflowActionParams) -> BlueflowActionOutput:
        # Resolve secrets to get stored api_url if not overridden in params
        secrets = await BlueflowCredential.resolve()
        base = self._base(params, secrets)
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
