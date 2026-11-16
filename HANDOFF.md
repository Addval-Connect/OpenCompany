# Handoff — OpenCompany local + sandbox Odoo

**Fecha:** 2026-11-12 (sesión 3 — fix H1 A+B+C; sin commit)
**Estado:** H1 implementado y verificado (159 tests verdes); D (modelo/skill) pendiente; generación 6 sin cambios.
**Uso:** archivo temporal para abrir el siguiente hilo. No commitear; borrar cuando ya no aporte.

---

## Actualización 2026-11-12 — H1 (A+B+C) implementado

**Causa raíz confirmada** (historial Temporal del turno P3, 24 pasos LLM): OpenRouter devuelve
HTTP 200 con `finish_reason="error"` y una tool-call parcial (`{"content": `) cuando el proveedor
corta la generación a ~90 s. `OpenAIProvider._normalize` ignoraba `finish_reason` y el objeto
`error`; el runtime lo trataba como tool-call válida con JSON inválido y devolvía el error al
modelo, que reintentaba la misma generación larga. 15 de 24 pasos fallaron a ~90-98 s (1.414 s
en pasos fallidos); sin freno, el bucle duró ~30 min hasta el Reset manual.

**Alcance aprobado e implementado:** A (frontera del proveedor), B (silla de seguridad),
C (observabilidad). **No** se tocó modelo, skills ni configuración.

**Rama de trabajo:** `feat/h1-safety-seat` (commit `235df70d`). `main` local queda en
`origin/main` (`66d11413`), sin push. Los cambios de sandbox (`odooJsonRpc` + `HANDOFF.md`)
siguen sin commitear en la rama de trabajo.

| Capa | Cambio |
|---|---|
| A — proveedor | `openai.py`: detecta `finish_reason=error` y `length`+tool-call truncada; lee `choice.error`/`resp.error`, `native_finish_reason`, `error.metadata.error_type`; con salida parcial lanza `LLMError(OUTPUT_TRUNCATED, retryable=False)`; sin salida parcial conserva la clasificación retryable (timeout/rate-limit/server). También cubre la Responses API (`status=failed` / `incomplete` con tool-calls). |
| A — protocolo | `protocol.py`: nueva categoría `LLMErrorCategory.OUTPUT_TRUNCATED` + mensaje público seguro; `LLMResponse.native_finish_reason` y `LLMResponse.provider_error` (diagnóstico). |
| B — runtime | `agent_progress.py` (nuevo): `NoProgressGuard` compartido — aborta con 2 firmas idénticas `(tool, raw_arguments)` o 3 pasos consecutivos sin tool ejecutable; se resetea con cualquier llamada ejecutable. |
| B — loops | `agent_runtime.py`: guard en `run_native_agent_loop` + `_truncation_error` genérico para proveedores no-OpenAI. `agent_workflow.py`: guard en `AgentWorkflow`, `error_type="AgentNoProgress"`, fase `failed`, y hint en el tool-result de parse-error (“no repitas; divide la escritura”). |
| C — logs | `agent_activities.py`: log por paso de `finish_reason`, `native_finish_reason`, `provider_error_type`, tool-calls y parse-errors; log de fallo del proveedor con categoría, código y request id. |

**Archivos nuevos/modificados (sin commit):**

- `server/services/agent_progress.py` — **nuevo**
- `server/services/agent_runtime.py`
- `server/services/llm/protocol.py`
- `server/services/llm/providers/openai.py`
- `server/services/temporal/agent_activities.py`
- `server/services/temporal/agent_workflow.py`
- `server/tests/services/test_agent_progress.py` — **nuevo**
- `server/tests/services/test_native_agent_runtime.py`
- `server/tests/llm/test_providers.py`
- `server/tests/temporal/test_agent_workflow.py`

**Verificación (con techo de memoria obligatorio):**

| Comando | Resultado |
|---|---|
| `( ulimit -v 4194304; timeout 180 pytest tests/llm/test_providers.py tests/services/test_agent_progress.py tests/services/test_native_agent_runtime.py tests/temporal/test_agent_workflow.py tests/nodes/test_odoo_jsonrpc_tool_args.py -q )` | **159 passed** |
| `( ulimit -v 4194304; timeout 300 pytest tests/llm tests/services tests/temporal -q )` | **1158 passed**, 1 fallo no relacionado: `test_process_service_ports.py::test_start_rejects_occupied_declared_port_before_spawn` (puerto/entorno; no toca este cambio) |
| `( ulimit -v 4194304; timeout 120 pytest --collect-only -q )` | 4121/4157 recogidos, 36 deseleccionados |
| `ruff check` sobre los archivos tocados | limpio |

**Residual / siguiente paso:** D1–D2 (chunking/`json_patch` y modelo más rápido o thinking off) no
implementados; R4 (timeout de transporte) opcional. El guard no se serializa a través de
`continue_as_new` y no cuenta errores de ejecución de tools (solo llamadas inutilizables); el
`max_iterations` sigue siendo 200.

---

## Seed realista 2026-11-12 — sandbox Odoo

Ejecutado con `OpenCompany-sandbox/seed_sandbox.py` (idempotente; segunda corrida sin
duplicados). Backup previo: `OpenCompany-sandbox/backups/odoo_sandbox_before_seed_2026-11-12.dump`.

| Entidad | Datos creados/actualizados |
|---|---|
| Empresa | `Addval Connect Sandbox` — RUT `76.543.210-3`, Av. Providencia 1234, Providencia, Metropolitana, CLP |
| Tasas CLP | USD `950`, UF `39.000`, UTM `67.000` (fecha 2026-11-12) |
| Cliente | `Minera Los Andes SpA` — RUT `76.111.222-8`, Las Condes |
| Proveedor | `Repuestos Industriales del Sur Ltda.` — RUT `78.987.654-1`, San Pedro de la Paz |
| Categorías | `Repuestos` y `Kits de mantenimiento` (hijas de Goods; coste standard, valorización periódica) |
| Repuestos | `REP-001` filtro aceite, `REP-002` rodamiento SKF 6205, `REP-003` correa A-42, `REP-004` sello 25 mm (almacenables) |
| Kit | `KIT-001` kit de mantenimiento preventivo; BOM `BOM-KIT-001` normal (2×REP-001 + 1×REP-002 + 1×REP-003) |
| Servicio | `SRV-001` mantenimiento preventivo en terreno |
| Venta | `S00001` borrador, cliente Minera Los Andes, 2 líneas, subtotal 114.800 + IVA 21.812 = **136.612 CLP** |
| Compra | `P00001` borrador (RFQ), proveedor Repuestos del Sur, 3 líneas, subtotal 128.800 + IVA 24.472 = **153.272 CLP** |

**Nota de idempotencia:** Odoo normaliza el RUT sin puntos (`76111222-8`); la búsqueda del
seed usa esa forma. La primera corrida duplicó cliente/proveedor por buscar con puntos; los
duplicados se eliminaron (sin órdenes asociadas) y la segunda corrida quedó limpia.

**Siguiente paso natural:** repetir P1–P4 (o al menos P3/P4) en el workflow para validar que
los agentes ya ven datos reales; luego R2 (modelo) con ese material. Las órdenes quedaron en
borrador a propósito, sin side effects de stock/contabilidad.

---

## Rutas

| Qué | Ruta |
|---|---|
| Repo (fork Addval) | `/home/jp-addval/Desarrollos/OpenCompany` |
| Sandbox Odoo | `/home/jp-addval/Desarrollos/OpenCompany-sandbox/odoo` |
| Datos OpenCompany | `/home/jp-addval/.opencompany-addval` |
| Secretos / entorno del servicio | `/home/jp-addval/.config/opencompany/opencompany.env` |
| Unit systemd | `/etc/systemd/system/opencompany.service` |
| **Informe de hallazgos** | `/home/jp-addval/Desarrollos/OpenCompany-sandbox/informe-hallazgos-2026-11-11.md` |
| **Batería de pruebas** | `/home/jp-addval/Desarrollos/OpenCompany-sandbox/pruebas-nivel1.md` |

> El enlace temporal `/home/jp-addval/OpenCompany -> …/Desarrollos/OpenCompany` ya no se necesita
> (los hilos nuevos trabajan con la ruta real); se puede borrar si nada lo referencia.

---

## Servicios

| Servicio | Estado / detalle |
|---|---|
| OpenCompany (systemd) | `active`, `127.0.0.1:5678`, login `single`, owner `jcontreras@addval.cl` |
| Odoo sandbox (Docker) | `odoo-db-1` + `odoo-odoo-1`, `http://localhost:8069`, base `odoo_sandbox`, `admin/admin` |
| Temporal | gRPC `:5681`, UI `:5680` — **proceso hijo del servicio**: reiniciar el servicio reinicia Temporal |

Comandos útiles:

```bash
sudo systemctl status opencompany --no-pager
sudo journalctl -u opencompany -f
cd ~/Desarrollos/OpenCompany-sandbox/odoo && docker compose ps
T=~/.opencompany-addval/packages/temporal/temporal_cli_latest_linux_amd64.tar.gz.untar/temporal
$T --address localhost:5681 workflow show -w <wid> -r <rid> --output json   # diagnóstico de bucles
```

---

## Workflows

| Workflow | Estado |
|---|---|
| `ArmandoOdoo` | Original de producción (Odoo SaaS `ines-ordenes.odoo.com`). **Intacto — no tocar sin autorización.** |
| `ArmandoOdoo Sandbox` | Copia 38 nodos. Odoo local. **Generación 6 corriendo** (g5 aplicó Reset limpio el 11-11). Conversación de g6 sin mensajes de negocio; estado del proyecto en archivos del workspace. |

- Workspace sandbox: `~/.opencompany-addval/namespaces/default/workspaces/ArmandoOdoo_Sandbox_1/`
- Proyecto: `proyectos/sandbox-odoo/` con `00-entrada`…`09-qa` + `coordinador/estado.json` (válido, 5 rondas registradas)
- Entregables de introspección en `02-instancia/`: financiero (21.7K), inventario (2.8K), ventas (14K), compras (10.8K)

---

## Lo hecho en esta sesión (2026-11-11, sesión 2)

1. **Idioma `es_CL` instalado** en `odoo_sandbox`: idioma activo, plan contable chileno traducido (205 cuentas, 27 impuestos), `admin` en `es_CL`, contenedor reiniciado.
2. **Nodo `odooJsonRpc` ampliado**: campo opcional `lang` (inyecta `context.lang`; vacío = comportamiento histórico; sobrevive al override de instancia y gana al modelo). `lang="es_CL"` grabado en los 2 nodos del workflow sandbox; el original no se tocó. Verificado end-to-end (P1 devolvió "Banco"/"IVA Crédito Fiscal", cero "Bank").
3. **Batería nivel 1 ejecutada (P1–P4)**: los 4 flujos de dominio aceptados, solo lectura, fronteras respetadas, brechas reportadas honestamente. Todo auditado contra BD/Temporal/archivos.
4. **Hallazgos documentados** (ver informe): H1 bucle de cierre (ver abajo), H2 `estado.json` truncado a mitad de escritura (el Coordinador lo auto-reparó), fortalezas F1–F4.
5. **Recuperación operativa**: tras un reinicio del servicio, un Resume quedó pegado (WebSocket muerto en la pestaña) y el turno de cierre de P3 entró en bucle → `Reset` (g5) → `Start` (g6) lo resolvió.

### Archivos del repo SIN COMITEAR (no commitear sin autorización)

- `server/nodes/tool/odoo_jsonrpc/__init__.py` — parche previo (`http://` para sandbox) **+** campo `lang` (sesión 2)
- `server/tests/nodes/test_odoo_jsonrpc_tool_args.py` — **nuevo** (14/14 tests: 9 previos + 5 de `lang`); ruff limpio
- **Fix H1 (A+B+C)** — ver sección “Actualización 2026-11-12”: `agent_progress.py` (**nuevo**), `agent_runtime.py`, `protocol.py`, `openai.py`, `agent_activities.py`, `agent_workflow.py` + tests
- `server/config/model_registry.json` — lo regenera el servidor
- `HANDOFF.md` — este archivo

---

## Hallazgo H1 (resumen) — el más importante

**Turno de cierre del Coordinador entra en bucle si el modelo trunca tool-calls.**
Modelo `z-ai/glm-5.3-flash` (OpenRouter) con thinking: generación se corta a ~90 s → tool_call llega truncado (`{"content": `) → runtime devuelve el error como tool-result → el modelo reintenta → bucle. Sin fallo a nivel de actividad (HTTP 200), `max_iterations=200` ≈ 5 h (inefectivo), reintentos LLM *unlimited-with-backoff*, `CONTINUED_AS_NEW` renueva el historial. **Causa raíz confirmada el 2026-11-12:** OpenRouter reporta `finish_reason="error"` + tool-call parcial y el adaptador lo descartaba; ver “Actualización 2026-11-12”.
**Recomendaciones priorizadas (detalle en el informe):**

- **R1 (código, prioridad):** silla de seguridad — `max_iterations` configurable y bajo para turnos de cierre (25–30) + cierre con error controlado avisando al consultor. Archivo: `services/agent_runtime.py` (`run_native_agent_loop`) + llamadores.
- **R2 (config, es el pendiente #5 del handoff):** decidir modelo de los 7 agentes; para el Coordinador, uno robusto en tool-calling o thinking off.
- **R3 (código mínimo):** escritura atómica (temporal + rename) de archivos de estado del proyecto.
- **R4 (opcional):** revisar timeout de transporte LLM (~90 s).

---

## Pendientes / próximos pasos (orden propuesto)

1. **R1 — silla de seguridad en el runtime** — **hecho** (2026-11-12; ver actualización A+B+C). Queda D1/D2 (chunking/`json_patch` y modelo) y R2.
2. **R2 — decidir modelo** (conecta con #5 del handoff original).
3. **Seed realista** (#2 original) — **hecho** (2026-11-12; ver sección “Seed realista”): clientes, proveedores, productos, BOM, cotización y RFQ; RUT/dirección y tasas CLP.
4. **9 ítems de `definir_para_circuito_repuestos`** (exuestos por el Coordinador en P4): umbral, aprobadores, motor, bloqueo, tratamiento de repuestos — criterio funcional del consultor.
5. **Blueprint** (`03-blueprint/proyecto.yaml` — no existe; lo piden los agentes) y prueba **G1/G2** (#4 original) antes de tocar CARGA.
6. **Documentos del cliente** en `00-entrada` (#3 original).
7. Opcional: quitar el symlink `/home/jp-addval/OpenCompany`; limpiar `HANDOFF.md` cuando deje de aportar.

---

## Reglas de trabajo

- **No cambiar configuración sin autorización explícita del usuario.**
- No usar credenciales del Odoo de producción en esta instancia.
- No commitear `HANDOFF.md` ni los parches sin autorización; borrar el handoff al terminar.
- La API key y los secretos viven en el entorno/BD; no copiarlos a archivos ni al chat.
- Key OpenRouter activa: termina en **`f07b`** (no guardar la key aquí). Saldo de referencia: ~27 USD al inicio del día.

---

## Prompt sugerido para el nuevo hilo

> Contexto: repo en `/home/jp-addval/Desarrollos/OpenCompany` (fork Addval, v0.2.1). Servicio `opencompany` en `127.0.0.1:5678` con login; datos en `~/.opencompany-addval`. Sandbox Odoo en `~/Desarrollos/OpenCompany-sandbox/odoo` (Docker, `odoo_sandbox` en `:8069`, `admin/admin`, es_CL activo, plan contable en español). Workflow `ArmandoOdoo Sandbox` en **generación 6**, batería de nivel 1 completada 4/4 (informe y evidencia en `~/Desarrollos/OpenCompany-sandbox/informe-hallazgos-2026-11-11.md` y `pruebas-nivel1.md`). Nodo `odooJsonRpc` con campo `lang` sin commitear (tests 14/14). Pendientes: R1 silla de seguridad en el runtime, decidir modelo (R2), seed realista, 9 ítems del circuito de repuestos, blueprint/proyecto.yaml, G1/G2. No cambies configuración sin mi autorización.
