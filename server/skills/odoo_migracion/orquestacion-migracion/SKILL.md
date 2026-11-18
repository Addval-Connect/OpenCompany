---
name: orquestacion-migracion
description: Reglas del Coordinador sobre task_manager y write_todos en la migración — catálogo de misiones, revisión de tareas y reintentos.
allowed-tools: task_manager write_todos data
metadata:
  author: addval
  version: "1.0"
  category: odoo_migracion

---

# Orquestación de la migración

Reglas del proyecto sobre `task_manager` y `write_todos`. La mecánica de cada operación está en el skill de plataforma `task-manager`; este skill no la repite. **Si algo choca con los skills de plataforma, rige este.**

## Fuente de verdad

`task_manager` y los archivos del proyecto. `write_todos` es solo una vista de progreso, nunca autoridad.

## El orden: un pipeline con una pausa humana entre etapas

La migración es secuencial por naturaleza: cada etapa consume lo que produjo la anterior. Lo que no es secuencial es **dentro** de la carga, donde los lotes de períodos distintos se pueden programar en paralelo **dentro de una misma fase** (nunca entre fases: la apertura va antes que los históricos, y las conciliaciones al final). Delega solo tareas cuya precondición se cumple.

## Catálogo de misiones

Título: `<etapa> · r<ronda>` (`carga historicos 2025-01 · r1` para cargas por lote). Antes de asignar, `list_tasks(include_history=true)`: una re-delegación legítima lleva ronda nueva.

| Etapa | Agente | Precondición (verifícala en archivos antes de asignar) | Criterio de aceptación (comprobable con `data`) |
|---|---|---|---|
| `analisis` | Analista | P1 cerrado: archivos en `00-entrada/fuente/` y fecha de corte por escrito | `perfil-fuente.json`, `calidad-fuente.json`, `control-fuente.json`, `preparacion-instancia.json`, `definiciones-requeridas.md` con el mínimo, cada ítem con propuesta |
| `cerrar P2` | Analista | Hay respuestas del consultor | Cero `respuesta:` vacías; perfil y control de la fuente vigentes |
| `diseno` | Analista | P2 cerrado | `estrategia.yaml`, `mapeo.yaml`, `tareas.yaml`, `casos-control.yaml`; cinco tablas de mapeo con sidecar e `INSTRUCTIVO.md`; ítems de P3 con propuesta |
| `cerrar P3` | Analista | Respuestas y tablas validadas en `05-validados/` | Sin ítems abiertos; diseño actualizado solo en lo que cambió |
| `transformacion` | Transformador | P3 cerrado y tablas validadas | `transformar.py`, lotes, `plan-conciliaciones.csv`, `manifiesto.json`, `rechazos-transformacion.csv`; la suma de lotes y apartadas iguala la fuente |
| `auditoria previa` | Auditor | Manifiesto vigente | `veredicto.json`, `cuadratura-previa.md` y el ítem de P4 en `definiciones-auditoria.md` |
| `carga <fase>` | CARGA | Ver abajo | `estado-carga.json` por lote; documentos electrónicos y folios iguales a cero |
| `auditoria posterior` | Auditor | Fase cargada; entorno staging (en producción, solo controles de lectura) | `resultados-control.md` caso por caso |

### Precondiciones de `carga <fase>`

- **Veredicto** `cargable` para los lotes de la fase y **cuadratura previa aprobada** (P4 respondido), sin lo cual solo se carga en borrador.
- La **fase anterior** terminada: `preparacion` → `apertura` → `partidas_abiertas` → `historicos <periodo>` → `conciliaciones`.
- **Entorno confirmado.** Si es `production`: `autorizacion_produccion` en el `context` (la agregas tú solo tras verificar la respuesta), ensayo en staging verde y respaldo informado. **QA y ensayos jamás contra producción.**
- Cero definiciones abiertas que afecten a esos lotes.

Pasa en el `context` solo las rutas de la misión. Una misión = un resultado acotado.

## Prioridad y concurrencia

Máximo tres tareas concurrentes en todo el árbol; el resto queda en cola. Dentro de una fase de carga, asigna los períodos en orden cronológico. `depends_on` solo para dependencias de máquina entre tareas ya creadas; las esperas humanas no son tareas.

## Revisar una tarea `submitted`

1. `get_task`. Si el resultado no explica el desenlace, `inspect_task_trace` con `detail="summary"`.
2. **Relee los artefactos** con `data` y compáralos con el criterio. No aceptes por el resumen del agente. Comprueba que ningún archivo fuera de la propiedad del agente cambió.
3. Un solo desenlace: `accept_task` (**siempre con `task_id` y `expected_revision`**), `retry_task`, `modify_task` (solo `blocked` o `queued`), `cancel_task`. Un conflicto de revisión significa que la tarea cambió: refresca y decide de nuevo.
4. Una tarea de CARGA con `documentos_electronicos_generados` o `folios_consumidos` distinto de cero **no se acepta**: detén las tareas siguientes y avisa al consultor en el mismo turno.

## Reintentos

Máximo **2 reintentos** por tarea, con un cambio verificable entre uno y otro. Dos fallos con la misma causa se escalan al consultor. **Una tarea de carga que ya publicó lotes no se reintenta a ciegas**: se relee `estado-carga.json` y se re-delega solo lo pendiente.

## `write_todos`

- Es una **vista**. Una llamada por turno, con la lista completa.
- Un ítem por **etapa en curso** y por **punto de control abierto**. Ejemplos: `Análisis: en curso`, `P2: esperando respuestas del consultor`, `Carga históricos: 3 de 12 períodos`.
- **Un punto de control abierto es un ítem `in_progress`.** No inventes trabajo mientras esperas: asigna lo que esté listo y termina el turno.
- **Reabrir** es un ítem nuevo (`Reabrir P3 por cambio en D-07`); nunca edites uno `completed`.
- Marca `completed` solo cuando el archivo correspondiente lo confirma.

## `finish_team`

Solo al **cierre del proyecto**: todos los lotes `conciliado` o justificados, `auditoria posterior` con todos los controles en verde, `resumen-carga.md` escrito y el estado del ensayo desde cero reportado (aunque sea "no realizado"). Declara cualquier control rojo, conciliación rechazada o lote sin publicar. Nunca en un punto de control.
