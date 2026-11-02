# Sincronización con upstream (zeenie-ai/OpenCompany) — Análisis de bringup

Estado al 2026-11-02, branch `chore/upstream-bringup-review`.

## Foto de la divergencia

| Métrica | Valor |
|---|---|
| Merge-base | `637aea0b` |
| Commits upstream no presentes en el fork | **522** |
| Commits del fork no presentes en upstream | 99 (tenancy, telegram, msTodo, branding, skills odoo) |
| Archivos tocados por upstream | 2,141 |
| Archivos tocados por el fork | 778 |
| Archivos en conflicto potencial | 578 (252 en `server/`) |
| **Merge completo `upstream/main` → fork** | **225 conflictos** |

La mayoría de los 225 conflictos de un merge completo están en documentos/CI/branding
(divergencia intencional del fork: nombres, workflows GH, READMEs, lockfiles) — ahí
conviene quedarse con **ours**. El riesgo real está en ~60 archivos de `server/` que
ambos lados modificaron (temporal, deployment, chat models, llm providers).

## Categorías upstream por valor/riesgo

### W1 — Seguridad (tomar sí o sí, riesgo bajo)
| Commit | Qué | Conflicto en cherry-pick |
|---|---|---|
| `ad038ae6` | HTTP node no puede alcanzar puertos propios (SSRF) | 1 archivo (`nodes/android/_router.py`) |
| `276d833b` | WhatsApp media en workspace + validación de URLs | 1 archivo (`google/drive/__init__.py`) |
| `1a5523e1` | Validación de comandos ADB port-forward | 1 archivo (`nodes/android/_router.py`) |
| `6a7f6bad` | 4 paquetes Python vulnerables (lock) | ✅ aplica limpio |
| `2b041365`, `e3b28104`, `0cab9a8a`, `48d1790c` | floors de seguridad Python | conflicto solo en `uv.lock`/`pyproject.toml` → resolver regenerando con `uv lock` |
| `5ba15944`, `6fd165ec`, `a8e390ca` | floors JS (bun audit) | conflicto en `bun.lock`/`package.json` → regenerar con `bun install` |

### W2 — Fiabilidad Temporal (serie 1b.x, ~23 fixes)
Directamente relevantes para nuestra clase de incidente (runs fallidos, workers,
re-arms, controllers):

| Commit | Qué |
|---|---|
| `1416f5b5` (1b.13) | bug en código de workflow falla el task, no el run |
| `03504492` (1b.15) | Update calls en proceso responden pending en vez de colgar |
| `3e0d91f5` (1b.16) | paging de cola del controller reintenta sin límite |
| `c6c55451` (1b.17) | deadline de poll acotado; errores de credenciales fallan rápido |
| `2f62393e` (1b.18) | ciclo de poll bajo el límite de payload |
| `675375dc` (1b.19) | carry de AgentWorkflow conserva seed keys |
| `525736d2` (1b.24) | circuit breaker cuenta un run fallido una vez |
| `2dcd53f9` (1b.20) | compensaciones reintentan hasta aterrizar |
| `a95120ed` + `986b8484` (1b.22/1b.46) | undo de Start fallido completo y seguro entre generaciones |
| `9357689a` (1b.23) | boot reejecuta un Reset interrumpido |
| `a6f9af68` (1b.21) | Reset cierra el trabajo abierto de la generación |
| `d379ab3e` (1b.36) | workers de main-queue registran lo mismo |
| `02c002c3` (1b.37) | workers paran juntos |
| `02800a04` (1b.34) | worker pool siempre polléa |
| `56f0b397` | standalone worker polléa namespace/queue del backend |
| `ded22c7d` (1b.32) | re-arm refresca snapshot de listener conocido |
| `427c4ac4`, `444c70a5`, `0c427055`, `663cb651` | LLM steps: retries/budgets correctos |
| `5635ac6c` (1b.29) | task de workflow fallido loguea ERROR |

Coste de cherry-pick individual: 2–14 conflictos c/u, concentrados en
`services/temporal/` (worker.py, workflow.py, agent_workflow.py, activities.py) —
archivos donde el fork también tiene cambios (tenancy, interceptors).
Requiere resolución cuidadosa + suite temporal completa.

### W3 — Observabilidad/ops (barato, valioso)
| Commit | Qué |
|---|---|
| `4ef27b5a` (1b.39) | log cuando el event loop está bloqueado |
| `77c1a3aa` (1b.38b) | run atascado en el engine visible en Home |
| `bc26edc8` (1b.30) | alerta de retries + attention store |

### W4 — Features grandes (posponer)
- RFC-0007: ApprovalWorkflow, chat waits (AP.4a–c, AP.5) — ~15 commits
- gateway/, mobile/, home UX/orb — ~50+ commits
- Estas traen superficies nuevas; conviene traerlas cuando W1/W2 estén asentadas.

### Nota — fixes de cron upstream
`45c504fe` fix(cron): una Schedule de workflow borrado no bloquea Start — relevante
para nuestro caso (schedule huérfana); revisar si complementa `fix/tenant-namespace-artifacts`.

## Recomendación de ejecución

1. **W1 ya**: cherry-pick de seguridad; resolver lockfiles regenerando (`uv lock`,
   `bun install`), nunca a mano. ~1 día con suite completa.
2. **W2 en tandas de 4–6 commits** por PR, empezando por los que tocan
   `deployment/` y `worker.py` (más alineados con producción EC2). Suite
   temporal + smoke en EC2 por tanda.
3. **W3** junto con la primera tanda de W2 (superficie pequeña).
4. **Estrategia de largo plazo**: el cherry-pick perpetuo no escala (522 y creciendo).
   Después de asentar W1+W2, planificar un **merge completo por fases** con
   `-X ours` en docs/CI/branding y resolución manual solo en los ~60 archivos
   compartidos de `server/`, para volver a estar cerca de upstream.

## Qué NO se toca (protecciones del fork)

Branches de protección del trabajo propio: tenancy (client registry, fail-closed,
rearm con namespace), telegram multi-bot + skills, msTodo, branding Bluedoc Workers,
skills odoo_impl, EC2 deploy scripts. Cualquier tanda que toque
`services/deployment/*`, `services/temporal/worker.py`, `nodes/telegram/*`,
`nodes/microsoft/*` se revisa contra esos archivos primero.
