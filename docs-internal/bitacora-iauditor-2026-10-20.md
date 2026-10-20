# Bitácora — IAuditor: modo estructural cross-namespace (20 oct 2026)

> Registro de la sesión del 20/oct/2026 sobre el workflow **IAuditor** del namespace
> **`mayatest`** en el host EC2 `i-019e13ccd38631d6e`. Workflow id
> `1ceb6131d0c8472cb054e0042c8e3ce9`, slug `IAuditor_1`, workspace
> `namespaces/mayatest/workspaces/IAuditor_1/`. Acceso: `deploy/ec2/ssh.sh`.
> Estado al cierre: **tool nueva desplegada y verificada, flujo mutado a 25 nodos /
> 33 aristas, rama `feat/iauditor-introspeccion` con PR abierto**.

## 1. Contexto

IAuditor audita sets de prompts y skills: A1 elucidación, A2 contradicciones/ambigüedades
y A3 candados técnicos en paralelo, COORD consolida y reporta. Hasta hoy el material
entraba por correo o chat y se guardaba en el workspace (`cartolas/*.md`, `set-audit.md`).
El pedido: que pueda **entrar a otros flujos, en otros namespaces, y auditarlos** — la
definición real desplegada (grafo, prompts, skills) como contexto estructural para
evidenciar candados técnicos y ambigüedades.

## 2. Diagnóstico (hallazgos con evidencia)

1. **`fs_search` ordenada y no conectada**: las misiones que COORD delega a A1/A2/A3
   ordenan "verifica con fs_search", pero `fsSearch:1` solo tenía arista hacia COORD.
   El paso de verificación de cada misión moría en los agentes. Patrón exacto de la
   lección nº8 de ArmandoOdoo (skills vs grafo real).
2. **Prompt de COORD con secciones duplicadas**: dos bloques FORMATO ("Máximo dos
   pantallas" vs "Máxima una pantalla") y dos bloques ENTREGA — la contradicción
   interna que A2 le detectaría al propio flujo.
3. **Contexts 1–4 con historial stale del 09-10** (auditoría CartolaTax previa) como
   memoria permanente.
4. **El sandbox de filesystem bloquea el acceso cross-namespace por diseño**:
   `fileRead`/`fsSearch`/`fileModify` están contenidas al workspace del workflow
   (`resolve_within`, sin `..`/`~`), y las definiciones de otros flujos ni siquiera
   viven en archivos sino en `namespaces/<ns>/workflow.db`.
5. **Vías descartadas**: `httpRequest` → API propia exige cookie JWT con claim
   `active_namespace` (sin auth máquina-a-máquina); el MCP `/mcp/` es de sesiones CLI.
   `processManager` + script Python funcionaría (el guardrail constriñe el cwd, no los
   archivos que el proceso abre) pero es un bypass del tenancy que dejaría
   `credentials.db` al alcance del LLM, sin contrato de datos.

## 3. Decisiones del operador

| Decisión | Resolución |
|---|---|
| Vía de aplicación | Tool node nueva (`workflowIntrospect`) en el repo, no bypass |
| Alcance cross-namespace | Todos los namespaces del host, read-only; allowlist opcional por env (`AUDITABLE_NAMESPACES`) |
| Quién recibe la tool | Solo COORD (el material baja al workspace y los agentes leen archivos) |
| Modo de operación | Conviven: set por correo/chat (como hoy) + structural (auditar flujo del host) |

## 4. Ejecución

### 4.1 Repo — rama `feat/iauditor-introspeccion` (apilada sobre `feat/odoo-impl-multiproyecto` / PR #56)

- **`d9d2cd23` feat(tools): workflowIntrospect** — `server/nodes/workflow/workflow_introspect/__init__.py`
  (ToolNode, `usable_as_tool`, `tool_name=workflow_introspect`):
  - `list_namespaces` / `list_workflows(namespace)` / `get_workflow(namespace, workflow, include)`.
  - Solo lectura: `sqlite3` stdlib con URI `mode=ro` en `asyncio.to_thread`; **nunca**
    `credentials.db`.
  - Namespace validado contra `NAMESPACE_PATTERN` (services.tenancy) **antes** de todo
    path join. Se usa el patrón y NO `is_valid_namespace`: su set de reservados bloquea
    `default`, que sí es legítimo de leer.
  - Allowlist del operador: `AUDITABLE_NAMESPACES` (env, comma/space); unset = todo lo
    que tenga `workflow.db` en disco; dirs con punto (backups `.owner-*`) invisibles.
  - Resolución del workflow: exacto (name/id/slug case-insensitive) → substring →
    ambiguo = error con candidatos (el LLM dice "CartolaTax", el flujo se llama
    "CartolaTax — Statement Import").
  - Truncado: per-string 20k + payload total 600k, desde el ORIGINAL (re-truncar
    compone marcadores y miente); reportado en `truncated`.
  - `+workflowIntrospect` en `node_allowlist.json`; tests en
    `tests/nodes/test_workflow_introspect.py` (traversal, read-only, ambigüedad,
    truncado, allowlist env, export).
- **`a8f99f00` fix(tools)**: resolución por substring no ambiguo (hallado en smoke real).
- **`0b919600` feat(tools): export_workflow** — escribe la definición íntegra (grafo +
  parámetros SIN truncar) como JSON pretty-printed (`indent=1`) en el workspace del
  workflow llamador (`estructura/<ns>__<slug>.json`, escritura atómica, ruta contenida
  vía `resolve_media`) y devuelve SOLO resumen + **índice de artefactos de prosa**
  (`json_path` de cada `system_message` y cada skill inline). Un workflow de 53 nodos
  ya no viaja por el contexto del LLM para terminar en un archivo.
- **`c77499cc` feat(skills)**: secciones MODO ESTRUCTURAL en
  `tlp-elucidaciones` (qué es un artefacto de prosa; el grafo no se elucida),
  `if-detector-logico` (tool fantasma, contrato roto, regla sin soporte — tipo
  `estructura`) e `if-auditor-tecnico` (candado verificado contra el grafo con campo
  `evidencia`).

### 4.2 Deploys

Dos pasadas `OC_INSTANCE_ID=i-019e13ccd38631d6e ./deploy/ec2/deploy.sh --skip-build`
(el cliente no cambió). Verificado en host: allowlist con el nodo, `grep -c 'MODO
ESTRUCTURAL'` = 1 en los 3 skills, registro del plugin vía `import nodes` + `registered_node_classes`
(OJO: importar solo `services.node_registry` NO dispara el walker — verificación
mal hecha la primera vez dio un falso negativo), 0 imports fallidos en app.log.

### 4.3 Smoke E2E de la tool (host real)

- `list_namespaces` → `addval-connect, addval-tax, bluedoc, default, investability, mayatest`.
- `list_workflows(addval-tax)` → CartolaTax — Statement Import.
- `get_workflow("CartolaTax")` → 52 nodos / 51 aristas / 53 filas de parámetros.
- `export_workflow` contra CartolaTax escribió en el workspace real de IAuditor_1:
  **480.695 bytes / 1.106 líneas / 41 artefactos indexados** (prompts + skills inline
  con su `json_path` exacto).
- Traversal (`../../etc`) rechazado; INSERT sobre la conexión `mode=ro` falla con
  `OperationalError` — read-only verificado.
- Paginación verificada: sección `parameters` empieza en la línea 581; las keys de
  nodo son greppables (el patrón de lectura A1: fs_search grep → file_read offset).

### 4.4 Mutación del flujo (script `/tmp/opencode/mut_iauditor.py`)

Backup previo: `backups-oc/workflow-mayatest-20261020-222820.db`. `BEGIN IMMEDIATE` +
asserts (23 nodos / 28 aristas, sin `workflowIntrospect` previo) que abortan sin
escribir; **dry-run contra copia en `/tmp` primero**, luego real. Cambios:

1. **Grafo**: +2 nodos (`workflowIntrospect:1` pos (140,-180), `documentParser:1` pos
   (420,20)) y +5 aristas: las 2 nuevas → COORD (`output-tool`→`input-tools`) y
   `fsSearch:1` → `aiAgent:1/2/3` (el fix del hallazgo 1). Resultado: **25 nodos / 33 aristas**.
2. **node_parameters**: upsert de los 2 nuevos (introspect `operation=list_namespaces`,
   parser `docx`); COORD reescrito (13.590 chars); A2/A3 con apéndice estructural
   alineado a sus skills de disco; `masterSkill:2` inline de `tlp-elucidaciones` con la
   sección MODO ESTRUCTURAL (el inline manda sobre el disco — lección 3 de CartolaTax);
   `context:1-4` con `memory_content=""`.
3. **FORMATO/ENTREGA deduplicados**: una sola definición de informe (dos pantallas) y
   una sola regla de entrega.

### 4.5 Verificación

Read-back completo del script (nodos, aristas, needles de texto, contexts vacíos).
El JSON exportado es navegable por línea. Registry con la tool cargada.

## 5. Credenciales del namespace (hallazgo operativo)

`mayatest` tiene **openrouter** (los LLM de COORD/A1–A3 corren) y client_id/secret de
Microsoft, pero **`oauth_tokens` está vacío**: el poll `msMailReceive` y el envío
`ms_mail` fallarán hasta reconectar Microsoft **dentro de** `mayatest` (tokens
por-namespace — lección 4 de CartolaTax). El camino por chat no depende de eso.

## 6. Estado al cierre

- Repo: rama `feat/iauditor-introspeccion` (3 commits) pusheada; PR abierto (apilado
  sobre #56).
- Server: desplegado y saludable; tool verificada E2E; flujo mutado y verificado.
- Workspace de IAuditor_1 con el material de ejemplo
  `estructura/addval-tax__CartolaTax_Statement_Import_1.json` (producto del smoke).

## 7. Pendientes

1. **Merge de PR #56** y luego el de esta rama (o rebase si se pide).
2. **Reconectar Microsoft dentro de `mayatest`** si se quiere la vía correo.
3. Primera corrida real de humo conversacional: pedirle a IAuditor por chat "audita el
   flujo del namespace addval-tax" y revisar el informe.
4. Opcional (Fase 3+): `dataSource` (`data`) para lecturas JSON acotadas de los
   elucidaciones grandes; `processManager` para troceo por script.
5. Opcional: sincronizar disk↔inline con `server/scripts/materialize_skills_config.py`
   (untracked, de la sesión ArmandoOdoo) si se importan workflows a hosts frescos.

## 8. Lecciones

1. **El material estructural no debe pasar por el contexto del LLM**: exportar al
   workspace y devolver un índice (rutas JSON exactas) es el patrón que escala; el
   `get_workflow` inline queda para lecturas quirúrgicas.
2. **Verificar el registro de un plugin importando `nodes` completo**, no solo el
   registry: el walker de auto-descubrimiento es quien registra, y traga excepciones
   de import con `logger.exception`.
3. **Dry-run contra copia de la BD antes de toda mutación** atrapó cero errores esta
   vez, pero el needle de verificación mal elegido sí se corrigió gracias al read-back.
4. La resolución difusa (exacto → substring → ambiguo con candidatos) es ergonomía del
   LLM, no un lujo: el modelo nunca va a citar el nombre largo exacto la primera vez.
