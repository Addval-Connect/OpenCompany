---
name: orquestar-implementacion-odoo
description: >-
  Runbook del Coordinador de la implementación Odoo 19: delega A1 a A5 en orden con task_manager,
  verifica precondiciones antes de cada delegación, consolida pendientes y decide el avance. El
  Coordinador es el único que decide quién trabaja después.
allowed-tools: task_manager write_todos file_read
metadata:
  agente: COORD
  tipo: ORQ
  prioridad: P0
  siguiente_agente: A1
  icon: "🎯"
  author: addval
  version: "1.0"
  category: odoo_impl
---

# Orquestar la implementación (runbook COORD)

Llevas un proyecto de implementación de Odoo 19 desde épicas e historias de usuario hasta una
instancia configurada, cargada y con QA verde. Cinco workers hacen el trabajo; tú decides el orden,
verificas precondiciones y consolidas las dudas. Lee `contrato-implementacion-odoo` antes del primer
`assign_task`.

## El Task Manager ES la máquina de estados (no inventes una)

Cada delegación es `task_manager(operation="assign_task", assignee_node_id=…, title=…, mission=…,
context={…}, acceptance_criteria={…})`. El TeamTask que se crea recorre
`queued → running → submitted → accepted`, y **ese ciclo es el estado del proyecto**. No mantengas un
campo `etapa_actual`, no lleves un enum propio, no escribas un archivo de estado. Para saber dónde
vas: `task_manager(operation="list_tasks")`.

Nunca uses `delegate_to_*`. Un worker nunca delega a otro worker: te devuelve su resultado y tú abres
la tarea siguiente.

`write_todos` es tu tablero visible para el usuario — un ítem por etapa, actualizado al delegar y al
recibir. No es estado durable; es comunicación.

## Pipeline

```
A1  analiza-brechas-e-introspecciona   00-entrada/          → 01-analisis/, 02-instancia/
A2  disena-blueprint-y-backlog         01-, 02-             → 03-blueprint/, 04-backlog/
A3  genera-plantillas-de-carga         03-, 02-             → 05-plantillas/
    ── el consultor humano completa y devuelve a 06-completadas/ ──
A4  valida-archivos-completados        06-completadas/      → 07-validacion/
A5  carga-a-odoo-y-verifica            07-, 03-, 00-        → 08-carga/, 09-qa/
```

Lineal. Sin paralelismo entre etapas: cada una consume el artefacto de la anterior y una etapa
adelantada trabaja sobre datos que van a cambiar.

## Paso 1 — Abrir la sesión

Del mensaje del usuario extrae: nombre del proyecto, flujos en alcance, entorno objetivo
(`staging` / `production` / `development`) y ruta del proyecto en el workspace. Verifica con
`file_read` que `00-entrada/historias.csv` existe y tiene filas; si falta, no arranques — pide el
insumo al usuario y explica el formato del contrato.

Arma el `context` inicial del contrato (`sesion_id`, `proyecto`, `instancia` con
`introspeccion_fecha: null`, `rutas`, `pendientes: []`). Crea el tablero con `write_todos`.

## Paso 2 — Delegar en orden, verificando precondiciones

Antes de cada `assign_task`, la precondición. **No delegas si no se cumple**; consolidas el pendiente
y consultas al usuario primero (`consultar-al-usuario-en-lote-odoo`).

| Delegas a | Precondición | `acceptance_criteria` mínimo |
|---|---|---|
| **A1** | `00-entrada/historias.csv` con filas; nodo Odoo configurado | `01-analisis/matriz-brechas.csv` con una fila por HU; `02-instancia/introspeccion.json` con fecha de hoy |
| **A2** | `introspeccion.json` fechada contra la instancia actual; sin pendientes abiertos de `modulo_faltante` | `03-blueprint/blueprint.yaml` con `prefijo_xmlid` y `objetos[]` con `fuente` y `depende_de`; `04-backlog/tareas.yaml` |
| **A3** | Blueprint existe; sin pendientes abiertos sobre los modelos a plantillar | Un `NN_<modelo>.csv` + `.meta.json` por objeto `fuente: plantilla`, más `INSTRUCTIVO.md` |
| **A4** | `06-completadas/` tiene archivos devueltos por el consultor | `informe-<modelo>.md` y `errores-<modelo>.csv` por archivo; conteo de errores por código |
| **A5** | Cero errores abiertos en `07-validacion/`; entorno confirmado | `08-carga/bitacora-<modelo>.jsonl` + `resumen-carga.md`; `09-qa/resultados-<flujo>.md` |

En cada `mission` incluye: qué produce, dónde lo escribe, qué NO le corresponde, y las rutas del
`context` — nunca el contenido de los artefactos. Pasa rutas; el worker abre lo que necesita.

## Paso 3 — Cuándo NO avanzas al siguiente worker

- **A1 devolvió `confianza: baja`** o módulos faltantes que el blueprint necesita → consulta al
  usuario antes de A2. Un blueprint sobre una instancia mal leída se cae completo en la carga.
- **A2 dejó objetos `[VERIFICAR]` sin resolver** → vuelve a A1 para introspección puntual, no a A3.
- **A3 terminó** → **te detienes**. Este es el único punto donde el pipeline espera a una persona:
  informa al usuario qué archivos hay en `05-plantillas/`, qué dice el `INSTRUCTIVO.md` y que los
  devuelva a `06-completadas/`. No delegues A4 hasta que haya archivos ahí.
- **A4 reportó `E100` o `E320`** → esos archivos no se cargan. Devuélvelos al consultor (o a A3 si es
  un defecto de la plantilla) antes de delegar A5.
- **A4 reportó errores de fila abiertos** → A5 no carga ese archivo. Los archivos limpios sí pueden
  avanzar; A5 carga por archivo, no todo o nada.
- **El entorno es `production` sin confirmación explícita de base + rama** → pendiente
  `entorno_produccion`, y no delegas A5.
- **Hay pendientes con `respuesta: null`** que afectan a la etapa siguiente → consulta primero.

## Paso 4 — Consolidar pendientes

Los workers devuelven `pendientes[]`. Tú los acumulas en el `context` de la sesión y **los consultas
en lote**, no de uno en uno (`consultar-al-usuario-en-lote-odoo`). Al recibir respuestas, llenas
`respuesta` / `respondido_por` / `respondido_en` — un worker nunca escribe esos campos — y los pasas
en el `context` de la delegación siguiente.

Si la respuesta invalida un artefacto ya producido (cambia una clasificación, un campo, un xmlid),
re-delegas la etapa que lo produjo. No parchees el artefacto tú mismo.

## Paso 5 — Cerrar

Cuando A5 devuelve carga y QA, cierra con `cerrar-y-notificar-implementacion`.

## Fronteras de responsabilidad

- **A1** lee `00-entrada/` y la instancia. No diseña: clasifica brechas y reporta qué hay.
- **A2** diseña sobre lo que A1 encontró. No consulta Odoo, no genera archivos de carga.
- **A3** genera plantillas desde el blueprint. No reinterpreta el diseño ni decide campos que el
  blueprint no pidió.
- **A4** valida lo que devolvió el consultor. No corrige datos: los reporta con el código y la
  sugerencia.
- **A5** es el **único punto de escritura** en Odoo. No toma decisiones de negocio: si Odoo rechaza
  por criterio funcional, es un pendiente.

## Nunca

- No delegues dos etapas en paralelo.
- No pases el contenido de un artefacto en el `context` — solo su ruta.
- No inventes un campo de estado ni un archivo de estado.
- No dejes que un worker decida el avance.
- No cargues a producción sin confirmación explícita de base de datos y rama.
