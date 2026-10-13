---
name: "contrato-sesion-importacion"
description: "Fuente única de verdad sobre qué significa cada campo, dónde vive y quién lo escribe. Cuatro agentes"
metadata:
  author: opencompany
  version: "1.0"
  category: "statement_import"

---

# Contrato de sesión de importación

Fuente única de verdad sobre qué significa cada campo, dónde vive y quién lo escribe. Cuatro agentes
actúan en turnos separados sin verse entre sí; sin contrato, los errores de integración serían
silenciosos.

## Dónde vive la sesión (tres soportes)

1. **Delegación durable (`task_manager`).** El Coordinador (team-lead `ai_employee` /
   `orchestrator_agent`) delega a cada worker A1–A4 con `task_manager` (`operation="assign_task"`,
   `assignee_node_id`, `title`, `mission`, `context={...}`, `acceptance_criteria={...}`). NO usa
   `delegate_to_*`. Cada `assign_task` crea un TeamTask durable cuyo ciclo
   `queued → running → submitted → accepted` reemplaza la máquina de estados; su finalización dispara
   el `taskTrigger` que el Coordinador observa.
2. **Estado de sesión (mission + context).** Los datos livianos de coordinación viajan en el
   `context` y regresan en el resultado. El "estado" NO es un campo que un worker sobrescriba: es el
   TeamTask que el Coordinador abre para el paso siguiente. El `context` lleva rutas
   workspace-relativas, no datos pesados.
3. **Artefactos pesados (archivos en el workspace).** Páginas extraídas, JSON intermedios y
   `json_cartola` viven como archivos bajo `~/.opencompany/workspaces/<slug>/…`, NO en el `context`.
   Se leen/escriben con `fileRead` / `fileModify` / `fsSearch` / `shell`; el `context` solo lleva las
   rutas.

## Esquema del estado (context + resultado de tarea)

**No hay campo de estado.** El avance NO se representa con un enum ni con `agente_actual`: lo lleva
el Task Manager (estado de las TeamTasks, ver `orquestar-sesion-cartola`). El `context` transporta
solo datos de dominio; los campos con ruta apuntan a archivos, no incrustan contenido.

```json
{
  "sesion_id": "uuid",
  "archivo": {
    "nombre_original": "string",
    "hash_sha256": "string",
    "formato_real": "pdf_texto|pdf_escaneado|zip_paginas|xlsx|desconocido",
    "paginas": 0,
    "ruta_paquete": "ruta workspace-relativa al directorio del paquete"
  },
  "custodio": {
    "codigo": "BANCHILE|ITAU|BICE|BCI|AMERIS|MONEDA|MERRILL|SANTANDER|UBS|null",
    "jurisdiccion": "nacional|extranjero|nacional_custodia_extranjera|null",
    "diccionario_id": "string|null",
    "diccionario_version": "string|null",
    "confianza": "alta|media|baja"
  },
  "ruta_json_cartola": "ruta workspace-relativa a cartola.json (no se incrusta el JSON)",
  "pendientes": [
    {
      "id": "P-001",
      "origen": "A2|A3|A4",
      "motivo": "disminucion_capital|reinversion|codigo_no_documentado|instrumento_sin_match|cliente_ambiguo|otro",
      "pregunta": "string",
      "opciones": ["string"],
      "referencia": { "movimiento_idx": 0, "campo": "string" },
      "respuesta": "string|null",
      "respondido_por": "string|null",
      "respondido_en": "iso8601|null"
    }
  ],
  "alertas": ["string"],
  "resultado_carga": {
    "lineas_ok": 0,
    "lineas_error": 0,
    "ids_odoo": [],
    "clave_idempotencia": "string"
  }
}
```

`resultado_carga.ids_odoo` son los enteros que devuelve `kardex.import.log.create`. La identidad de
una carga es ese id entero; **nunca** `kardex.import.log.name` (literal "...", no se parsea ni se usa
como clave). La clave natural es la tripleta `(custodian_id, account, kardex_period)`.

## Propiedad de campos

| Campo | Quién escribe | Quién solo lee |
|---|---|---|
| Paso siguiente (NO es campo: es el `assign_task`) | Solo el Coordinador | — |
| `archivo.*` | Procesa Archivos (A1) | Todos |
| `custodio.*` | Interpreta Cartola (A2) | A3, A4 |
| `cartola.json` (ref. `ruta_json_cartola`) | A2 lo crea; A3 lo enriquece (`fileRead`+`fileModify`) | A4 (`fileRead`) |
| `pendientes[]` (en el resultado) | Cualquier worker con duda (A2/A3/A4); Coordinador consolida | — |
| `resultado_carga` | Solo Importa a Odoo (A4) | Coordinador |
| Trazabilidad (registro durable + console) | Todos, solo agregando eventos | — |

## Regla de oro

Un worker no decide el avance: devuelve su resultado enriquecido y el Coordinador abre el
`assign_task` siguiente. Un worker produce solo el resultado natural de su rol (A2 devuelve la
cartola interpretada; no decide "ya se puede importar"). Si detecta algo que no sabe resolver,
escribe un pendiente estructurado y devuelve el control — nunca salta ni delega a otro worker.

## Casos de borde

- **Falta un campo del esquema**: no lo agregues por tu cuenta; el contrato debe evolucionar aquí,
  explícitamente.
- **Dos agentes escriben el mismo artefacto en turnos distintos**: la tabla de propiedad resuelve la
  ambigüedad. A3 siempre relee `cartola.json` con `fileRead` antes de enriquecerlo, para partir del
  contenido de A2 y no de una copia obsoleta en `context`.
- **`context` pesado**: nunca incrustes páginas ni el `json_cartola`; pasa la ruta y abre con
  `fileRead`.
