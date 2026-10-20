---
name: orquestacion-del-proyecto
description: Reglas del proyecto sobre task_manager y write_todos para el Coordinador — estados, trazas y disciplina de tareas; si chocan con los skills de plataforma, rige este.
allowed-tools: task_manager write_todos
metadata:
  author: opencompany
  version: "1.0"
  category: coordinador

---

# Orquestación del proyecto

Reglas del proyecto sobre `task_manager` y `write_todos`. La mecánica de cada operación (argumentos, estados, trazas) está en el skill de plataforma `task-manager`; este skill no la repite. **Si algo choca con los skills de plataforma, rige este.**

## Fuente de verdad

`task_manager` y los archivos del proyecto. `write_todos` es solo una vista de progreso para el consultor, nunca autoridad.

## Planificación por dependencias

No hay secuencia fija entre flujos. Mantén en la cabeza (y reconstruye en cada invocación) qué tareas están **listas**: aquellas cuya precondición se cumple y que no están ya en cola, en curso o aceptadas.

**Ancla contable.** Es el núcleo contable (compañía, localización, plan de cuentas, impuestos, diarios, posiciones fiscales, monedas): los objetos con `ancla: true` en `blueprint-financiero.yaml`. Está cumplida cuando todos están `cargado` con read-back correcto en staging.

- Ninguna **carga** de ningún flujo (incluidos tesorería y facturación) se delega antes de que el ancla esté cumplida. La carga del ancla es la primera.
- Análisis, diseño y plantillas de los otros flujos **no esperan**, salvo los que referencian objetos contables (cuentas de valorización, impuestos en producto, posiciones fiscales): esos esperan el **G2 cerrado** del Flujo Financiero, no su carga.
- Si el entorno ya trae la contabilidad configurada (localización aplicada), el Flujo Financiero lo verifica y declara el ancla cumplida con esa evidencia. No se omite el paso.

**Orden de carga entre archivos.** Lo decide CARGA con el grafo `depende_de` y `requiere_de` de los blueprints. Tú solo habilitas la carga de un flujo cuando se cumplen las precondiciones de abajo. No impongas orden por nombre de archivo ni por número.

## Catálogo de misiones

Convención de título: `<flujo> · <etapa> · r<ronda>` (D0: `descubrimiento · r1`). Antes de asignar, `list_tasks(include_history=true)`: una re-delegación legítima lleva ronda nueva, no repite título.

| Etapa | Agente | Precondición (verifícala en archivos antes de asignar) | Criterio de aceptación (comprobable con `fileRead`) |
|---|---|---|---|
| `descubrimiento` | D0 | `00-entrada/` tiene material; si está vacía, es un pendiente `alcance_no_declarado` | Existen `propuesta-epicas.md`, `propuesta-historias.csv`, `preguntas-descubrimiento.md`; lista los flujos en alcance sin historias |
| `analisis` | cada flujo | G0 cerrado: `historias.csv` con filas, `definiciones-proyecto.md` sin ítems abiertos | `matriz-brechas-<flujo>.csv`, `introspeccion-<flujo>.json` y `definiciones-requeridas-<flujo>.md` con el mínimo de G1, cada ítem con propuesta |
| `cerrar G1` | cada flujo | Hay respuestas del consultor para sus ítems | Cero `respuesta:` vacías o declaradas `no aplica`; re-introspección hecha si hubo cambios de módulos o campos |
| `diseno` | cada flujo | Su G1 cerrado. Si referencia objetos del ancla: G2 del financiero cerrado | `blueprint-`, `configuracion-` y `tareas-<flujo>.yaml` con esquema válido; grafo `depende_de` acíclico; todo objeto con dueño, `fuente` y `ancla` explícitos; `basado_en` vigente |
| `cruzar requiere_de` | cada flujo | Su G1 cerrado y los blueprints de los flujos que nombra disponibles | Cada `requiere_de` tiene respuesta escrita del dueño (aceptado o rechazado) |
| `cerrar G2` | cada flujo | Hay respuestas del consultor | Sin ítems abiertos; `blueprint` actualizado solo en lo que cambió |
| `plantillas` | cada flujo | Su G2 cerrado | `<modelo>.csv` y `.meta.json` por objeto `plantilla`; `INSTRUCTIVO-<flujo>.md` con quién llena qué; `casos-<flujo>.yaml` según el alcance de QA aprobado |
| `validacion` | cada flujo | Hay archivos en `06-completadas/` de sus modelos | `veredicto-<flujo>.json` con un veredicto por archivo; `informe-` y `errores-` por modelo |
| `carga ancla` | CARGA | G2 y G3 de los objetos ancla cerrados, `veredicto` cargable, entorno confirmado | `estado-carga.json` con los objetos ancla `cargado` y read-back correcto en `resumen-carga.md` |
| `carga` | CARGA | Ancla cumplida, G3 del flujo, `veredicto` cargable, sin definiciones abiertas que afecten esos modelos, entorno confirmado | `estado-carga.json` y `resumen-carga.md` del lote; `carga_completa` honesto (nunca parcial como completa); estado del ensayo desde cero reportado |
| `qa` | CARGA | Carga del flujo hecha, **entorno staging** | `resultados-<flujo>.md` caso por caso (verde/rojo, aserción que falló), evidencia con ids |

Pasa en el `context` solo las rutas de la misión (ver contrato). Una misión = un resultado acotado.

## Prioridad y concurrencia

Hay un máximo de tres tareas concurrentes en todo el árbol; el resto queda en cola con orden determinista. Cuando haya más tareas listas que cupos, asigna primero lo que desbloquea el ancla contable (el análisis y diseño del Financiero, y su carga), luego lo que desbloquea decisiones del consultor (análisis, para levantar sus G1 cuanto antes), luego el resto. Usa `depends_on` para dependencias de máquina entre tareas ya creadas. Las esperas humanas no son tareas: no las modeles con `depends_on`.

## Revisar una tarea `submitted`

1. `get_task`. Si el resultado no explica el desenlace, `inspect_task_trace` con `detail="summary"`; solo si hace falta, `failures` o búsqueda acotada.
2. **Relee los artefactos** con `fileRead` y compáralos con el criterio de aceptación. No aceptes por el resumen del agente. Comprueba además que ningún archivo fuera de la propiedad del agente cambió (contrato).
3. Elige un solo desenlace:
   - `accept_task` cuando el criterio se cumple. **Siempre pasa `task_id` y `expected_revision`**, aunque haya una sola entregada: con varios flujos en paralelo, esa "única" puede no ser la que crees.
   - `retry_task` si la misión es válida y falló algo verificable.
   - `reassign_task` solo entre agentes de la tabla.
   - `modify_task` solo mientras esté `blocked` o `queued`.
   - `cancel_task` si ya no se necesita.
4. Un conflicto de revisión significa que la tarea cambió: refresca y decide de nuevo.

Si la tarea devolvió definiciones nuevas o pendientes en los archivos, no las preguntes todavía: déjalas para el siguiente correo (skill `puntos-de-control-consultor`).

## Reintentos

Máximo **2 reintentos** por tarea. Antes de cada uno debe haber cambiado algo verificable (un archivo corregido, una dependencia cumplida, una respuesta del consultor). Dos fallos con la misma causa no se reintentan: son un pendiente para el consultor. `inspect_task_trace` antes de cualquier reintento. Reasignar un agente de flujo a otro flujo requiere que el nuevo agente tenga la propiedad de los archivos; en la práctica, casi nunca procede.

## `write_todos`

- Es una **vista**, no la fuente de verdad. Una llamada por turno, con la lista completa.
- Un ítem por **flujo activo** y por **punto de control abierto**, no por celda flujo × etapa. Ejemplos: `Financiero: diseño en curso`, `G1 ventas_servicios: esperando respuestas del consultor`, `Ancla contable: carga pendiente`.
- **Un punto de control abierto es un ítem `in_progress`** (esperando respuestas). No inventes trabajo mientras esperas ni fuerces un cierre: asigna lo que esté listo, actualiza la vista y termina el turno.
- **Reabrir** (por ejemplo G2 por un cambio de G1) es un **ítem nuevo**: `Reabrir G2 financiero por cambio en D-03`. Nunca edites ni reabras un ítem `completed`.
- Marca `completed` solo cuando el archivo correspondiente lo confirma, nunca con trabajo parcial o errores sin resolver.

## `finish_team`

Solo al **cierre del proyecto**, nunca en un punto de control ni en una espera: todos los flujos en alcance aceptados, QA ejecutado en staging, `resumen-carga.md` escrito y el estado del ensayo desde cero reportado explícitamente (aunque sea "no realizado"). Sintetiza los resultados aceptados y declara cualquier fallo no resuelto. `carga_completa: false` o un caso de QA rojo se reportan como tal.
