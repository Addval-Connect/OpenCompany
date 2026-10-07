# AGENTS.md

OpenCompany: React Flow canvas frontend + Python FastAPI backend where each workflow node is a self-contained Python plugin folder. Start with [CONTRIBUTING.md](CONTRIBUTING.md) (repo map + "how to add X" recipes); [CLAUDE.md](CLAUDE.md) is the long-form doc index — don't duplicate it here, don't skip it either. Do **not** follow guides under `docs-internal/ARCHIVE/`; they are retired and the linked substitutes exist.

## Stack & commands

- bun 1.4 is the only package manager (`preinstall.js` rejects `npm`); Python 3.12 + uv for the server. No Node at runtime — Node 22 exists only so bun can run vite/vitest/eslint on it.
- Every root `bun run <verb>` is a thin wrapper over the Python CLI: `start/dev/serve/build/clean/stop/deploy` -> `python -m cli <verb>` (see [docs-internal/SCRIPTS.md](docs-internal/SCRIPTS.md)).
- Full app: `bun install && bun run dev` (Vite HMR + uvicorn); `bun run stop` to stop. Production single-port: `bun run build && bun run start` (port from `.env.template` / `.env`; `build` scaffolds `.env` on first run).
- The `company` CLI has no deps beyond the package itself; `company doctor` reports the environment, `company provision` repairs the Python side.

## Verification (CI = predeploy.yml, called by ci.yml)

- **TypeScript gate**: `bun run --filter react-flow-client typecheck` from root. TypeScript 7 (native Go compiler) pinned in root `devDependencies`; `client/` keeps `typescript@^5` because of typescript-eslint's peer range — a `cli/tests/test_release_pipeline_config.py` locks this. `typecheck:tsc` (tsc 5.9) is only a triage second opinion.
- Frontend tests + lint: `bun run test:frontend` / `bun run --filter react-flow-client lint`.
- Backend: `cd server && uv run pytest tests/ -v` (uv-managed venv), or `bun run test:backend` from root; `bun run test:nodes` adds handler coverage.
- CLI tests: `python -m pytest cli/tests/ -v` (needs `pytest pytest-asyncio pyyaml`).
- Default pytest excludes `live`-marked tests (they hit real LLM APIs and cost money); opt in via `pytest -m live`. Single tests: `uv run pytest tests/test_x.py::test_y`. Plugin import sanity: `uv run pytest --collect-only` from `server/`.

## Gotchas

- **`server/uv.lock` is committed.** After editing `server/pyproject.toml`, run `uv lock` in `server/` and commit the lock; CI fails on `uv lock --check`, and the desktop app installs `--frozen` from it.
- `uv sync` prunes anything outside the resolved set: boto3, beautifulsoup4, pypdf stay **main** dependencies (extras get uninstalled by the next `bun install`). Never move them back into `[project.optional-dependencies]`.
- Cross-package scripts must use `bun --cwd=client run <script>` (`=` form mandatory on bun 1.4). Never `bunx`.
- `desktop/` is a **standalone bun package, not a root workspace member** — root `bun install/run` never touches it; use `cd desktop && bun run stage && bun run dev` (its test:invariants needs `stage` first).
- Changes to `server/pyproject.toml` or root `package.json` may be locked by CLI contract tests (`test_release_pipeline_config.py`); run `cli/tests` when touching manifests.
- Python lint is ruff (line-length 140, from `server/`); client lint is eslint (`client/eslint.config.js`).

## Architecture facts that surprise agents

- **Backend is SSOT for node schemas/UI**: a new node = one self-contained folder `server/nodes/<category>/<node>/__init__.py` (NodeSpec + execute, auto-registers on import) — **zero frontend TypeScript edits**. Recipe: [server/nodes/README.md](server/nodes/README.md) / [docs-internal/node_creation.md](docs-internal/node_creation.md); icon = `icon.svg`, color = `meta.json`.
- Contract tests run automatically over every registered plugin (`test_plugin_contract.py`, `test_node_spec.py`, `test_plugin_self_containment.py` = no cross-plugin imports). New backend `uiHint` flags need a matching entry in `server/tests/test_node_spec.py`'s `known` set.
- `server/services/handlers/` holds only cross-cutting orchestration (`tools.py`, `triggers.py`, `todo.py`) — per-node logic lives inside the plugin since Wave 11.
- UI visibility is config, not code: `server/config/node_allowlist.json` (see [docs-internal/node_allowlist.md](docs-internal/node_allowlist.md)).
- Execution: WorkflowService routes through Temporal when `TEMPORAL_ENABLED`, falls back to a sequential walk; new trigger/event work uses the Wave 12 plugin-facing registries (`register_*` hooks) — never hand-edit `event_waiter.py`.
- LLM providers are native SDKs in `server/services/llm/`; OpenAI-compatible providers are a `_COMPAT_PROVIDERS` entry + `llm_defaults.json` JSON block. New agent types: append to the `AI_AGENT_TYPES` frozenset in `server/constants.py`.
