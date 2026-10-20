# Bitácora — Preparación de deploy: íconos quietos, catálogo plano de skills y retiro de executors (20 oct 2026)

> Bitácora **aparte y nueva** (a pedido del operador; no actualiza
> `bitacora-armandoodoo-2026-10-20.md` ni ninguna otra). Documenta tres tareas de
> preparación del deploy sobre la rama `feat/odoo-impl-multiproyecto`.
> Rango de commits: **`c8bc8a9c` (base) → `2f858f9f`**, en tres commits separados.
> Estado al cierre: **implementado, testeado y commiteado; sin deploy aún**.

## 1. Contexto y trazabilidad

Tres tareas acordadas en planificación previa a la ejecución:

1. **T1 — Íconos quietos**: los nodos del canvas se desplazaban al hover y
   "bailaban" durante el zoom.
2. **T2 — MasterSkills "Todos"**: la lista solo mostraba skills de la carpeta
   seleccionada; sin forma de buscar el catálogo completo.
3. **T3 — Retiro de executors**: eliminar pythonExecutor / javascriptExecutor /
   typescriptExecutor / montyExecutor, el sidecar `server/nodejs/` y sus restos;
   el reemplazo es `processManager` (decisión ya registrada en
   `bitacora-armandoodoo-2026-10-20.md`).

**Modo conservador de git**: no se usó `git add -A`/`-u` a ciegas; staging
explícito por commit. Los archivos *untracked* ajenos a esta sesión
(`bitacora-armandoodoo-2026-10-20.md`, `bitacora-cartolatax-2026-10-13.md`,
`server/scripts/materialize_skills_config.py`) **no fueron tocados**.

## 2. Commits

| Commit | Tarea | Contenido |
|---|---|---|
| `190f170d` | T1 | `fix(ui)` — sin lift de hover en nodos (6 archivos `client/src`) |
| `121b0285` | T2 | `feat(skills)` — vista "All skills" (3 archivos) |
| `2f858f9f` | T3 | `refactor(executors)` — retiro completo (118 archivos, −3507 líneas) |

Comando de trazabilidad para quien lo necesite:

```bash
git log c8bc8a9c..HEAD --oneline
git diff --name-only c8bc8a9c..HEAD
```

## 3. Qué cambió (resumen por tarea)

### T1 — Nodos sin movimiento (`190f170d`)
- Causa raíz: "hover lift" del design system — `translateY(-1px)` en
  `.node:hover` / `.sq-node-box:hover` (`base.css`), variante Renaissance de
  `-2px` con curva de rebote, y transiciones inline de 0.2–0.3 s en
  `AIAgentNode` / `SquareNode`; el zoom lo agravaba porque el contenido se
  desliza bajo el cursor y el hover entra/sale en cada frame.
- Fix: `translateY` eliminado de los `:hover` (la sombra queda como único
  feedback), `transform` fuera de las transiciones inline, y el shorthand
  `theme.transitions.fast` de los gears de Toolkit/Trigger acotado a
  background/border/color.

### T2 — "All skills" en MasterSkillEditor (`121b0285`)
- Backend: nuevo handler WS `list_all_skills`
  (`server/services/skills/handlers.py`) — lista plana del registro global con
  `folder` de origen por skill (129 skills / 21 carpetas verificados contra el
  árbol real). Skills de usuario (DB) siguen fusionándose client-side.
- Frontend: primera opción del dropdown **"All skills (N)"**; badge de carpeta
  por fila; el buscador ahora también matchea la carpeta; prefetch masivo
  desactivado en la vista completa (evita 100+ requests); los skills de
  carpetas bloqueadas por allowlist se ocultan igual que en el dropdown.
- **Clave de diseño**: la opción es estado de vista local — el parámetro
  persistido `skill_folder` **nunca** recibe el sentinel (lo leen el Connected
  Skills scan y la config guardada). Sin cambios de runtime: `skill_folder`
  nunca limitó la expansión.

### T3 — Retiro de executors (`2f858f9f`)
- **Borrado**: `server/nodes/code/` completo (4 executors + `_base.py`,
  `_nodejs.py`, `_client.py`, `_runtime.py`; `_claude_code.py` era un shim
  legacy sin importadores), `server/nodejs/` (sidecar Express-on-bun), skills
  `coding_agent/{python,javascript,monty}-skill`, dependencia `pydantic-monty`
  (`uv.lock` + `requirements.txt` regenerados), `bun.lock` regenerado (el
  workspace `server/nodejs` salió del `package.json` raíz → ahora `["client"]`).
- **Cola Temporal `code-exec` eliminada** (`TaskQueue`, concurrency + rate-limit
  en `worker.py`, `plugin_activities.py`, comentarios; piso de
  `test_task_queue_coverage` 9 → 8).
- **Referencias limpiadas**: `node_executor._NEEDS_CONNECTED_OUTPUTS`,
  `CodeExecutorOutput` en `node_output_schemas`, `constants.CODE_EXECUTOR_TYPES`,
  `visuals.json`, allowlist de prints, `tool_names_snapshot.json`, comentarios
  de ejemplo en `ai.py` / `plugin/base` / `node_registry` / `rlm/adapters` /
  `handlers/tools` / `agent_builder` / `social_receive` / `browser/_service`.
- **Skills vivos corregidos**: los que instruían usar `python_code` /
  `javascript_code` (code-mode, progressive-discovery, multi-tool-orchestration,
  proxy-config) ahora guían el patrón **process_manager** (escribir script al
  workspace + `python3 script.py`) y su frontmatter `allowed-tools` usa
  `process_manager` (resuelve icono vía `visuals.processManager`).
- **Deploy/desktop/CI**: `cli/commands/build.py` sin el paso del sidecar
  (pipeline de 6 → 5 pasos, renumerado), `clean.py`, `serve.py`; contract tests
  de `cli/tests` actualizados; `desktop/scripts/stage.ts` sin `bundleSidecar`,
  invariant test sin el boot-test del sidecar; README de desktop; workflows
  `desktop-release.yml` / `desktop-ci.yml` / `deploy-ec2.yml`;
  `.env.template` / `.env` sin `NODEJS_EXECUTOR_*` (puerto 5682 liberado).
- **Docs**: cards de los 4 nodos borradas + índice regenerado (`cli docs nodes`);
  actualizados workflow-schema, plugin_system, TEMPORAL_ARCHITECTURE, SCRIPTS,
  release_build_pipeline (sección sidecar marcada **RETIRED**), ci_cd,
  rlm_service, tool_building_pipeline, infrastructure_cost_analysis, errors
  (#26 CLOSED/obsolete), desktop_app, desktop_host_contract,
  cli_services_integration, browser_harness, gcp_vm_deploy_runbook,
  deployment_legacy, deploy/ec2 (README + bootstrap.sh), CONTRIBUTING, CLAUDE.md
  y los diagramas `system-overview.svg` / `runtime-trust-topology.svg`.
- **Blindaje**: `test_plugin_self_containment` ahora incluye `nodes/code` en su
  lista de paths muertos — reintroducirlo rompe CI.

## 4. Verificación ejecutada

| Suite | Resultado |
|---|---|
| `server: uv run pytest tests/ -q` | **3981 passed**, 3 skipped (6 fallos iniciales corregidos: piso de colas, plugin folder `code`, iconos de skills con frontmatter viejo) |
| `server: uv run pytest --collect-only` | sano — 3988 collected (plugins importan limpio) |
| `cli/tests` | **355 passed** (incluye contract de release pipeline y docs-lint) |
| `test:frontend` (vitest) | **469 passed** / 58 archivos |
| `typecheck` + `lint` frontend | OK |
| ruff (server, archivos tocados) | OK |
| `stage.ts` (desktop) | transpila OK (`bun build`) |

**Pendiente de verificación en una máquina con `desktop/node_modules`
instalados**: `cd desktop && bun install && bun run stage &&
bun run test:invariants` (aquí el typecheck de desktop falla por
dependencias no instaladas — preexistente, no causado por estos cambios).

## 5. Impacto conocido — aviso para trabajo concurrente (JT)

1. **Workflows sembrados NO migrados (decisión consciente)**:
   `.opencompany/workflows/AI_Assistant.json` y `AI_Employee.json` (e
   `import.json`) conservan nodos `pythonExecutor` vivos y skill-instructions
   que mencionan `python_code`/`javascript_code`. Tras este cambio esos tipos
   de nodo **ya no existen**: al abrir esos workflows el canvas mostrará los
   nodos rotos y ejecutarlos fallará. Migración a `processManager` pendiente
   como tarea aparte.
2. **`.env`**: `NODEJS_EXECUTOR_PORT/URL/TIMEOUT` ya no se usan (pueden borrar
   sin efecto; el template ya no los declara).
3. **Superficies tocadas que podrían colisionar con edición concurrente**:
   docs (`CLAUDE.md`, `docs-internal/*`), `cli/`, `desktop/`, workflows de
   GitHub, `package.json` raíz + `bun.lock`, `server/pyproject.toml` +
   `server/uv.lock`. Si hay trabajo en curso sobre esos archivos, rebasar
   contra `2f858f9f`.
4. **`bun install` tras pull**: obligatorio (lockfile cambió);
   `bun install && bun run build` para regenerar artefactos.
5. **Iconos**: si algún tema custom añadía su propio `:hover` con translate
   sobre `.node`, quedará inconsistente con la nueva regla "nodos quietos"
   (base.css documenta la intención).

## 6. Brechas funcionales aceptadas al retirar los executors

- `process_manager` corre cualquier binario del PATH pero **no** tiene límites
  de recursos (monty imponía tiempo/memoria) ni retorno estructurado de
  `output` — el patrón de reemplazo documentado es script-que-imprime-JSON +
  `get_output`.
- La gestión de paquetes npm del sidecar (`/packages/install`) desapareció; el
  equivalente es `bun add` vía `process_manager` o `core.js_runtime.add_package`.
