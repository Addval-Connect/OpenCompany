# JavaScript Executor (`javascriptExecutor`)

| Field | Value |
|------|-------|
| **Category** | code_fs_process / code |
| **Backend handler** | [`server/nodes/code/javascript_executor/__init__.py::JavaScriptExecutorNode.execute_op`](../../../server/nodes/code/javascript_executor/__init__.py) (dispatched via `BaseNode.execute()` + `@Operation("execute")`; base in [`_base.py`](../../../server/nodes/code/_base.py)) |
| **Sidecar client** | [`server/nodes/code/_nodejs.py::get_nodejs_client`](../../../server/nodes/code/_nodejs.py) (singleton over [`server/nodes/code/_client.py::NodeJSClient`](../../../server/nodes/code/_client.py) — plugin-owned since July 2026; the old `nodejs_client.py` service module no longer exists) |
| **Tests** | [`server/tests/nodes/test_code_fs_process.py`](../../../server/tests/nodes/test_code_fs_process.py) |
| **Skill (if any)** | [`server/skills/coding_agent/javascript-skill/SKILL.md`](../../../server/skills/coding_agent/javascript-skill/SKILL.md) |
| **Dual-purpose tool** | yes - tool name `javascript_code` |

## Purpose

Runs user JavaScript through the persistent JS executor sidecar (Express on the
bun runtime, `server/nodejs/dist/index.js`) that the backend spawns on demand
from `nodes/code/_runtime.py` on the first JS/TS execution. The plugin does
**not** spawn a runtime per call - it POSTs the code to
`http://localhost:${NODEJS_EXECUTOR_PORT}/execute` via the shared
`get_nodejs_client()` singleton (an async `aiohttp` client). The sidecar
evaluates the script in a `node:vm` context and returns
`{success, output, console_output, ...}`.

The plugin merges the caller's upstream outputs (`ctx.raw["connected_outputs"]`)
into an `input_data` object, injects the workflow's `workspace_dir`
(`ctx.workspace_dir`) as a key, then forwards the payload with `language="javascript"`.
`connected_outputs` is injected by the executor for code-executor node types.

## Inputs (handles)

| Handle | Connection type | Required | Purpose |
|--------|-----------------|----------|---------|
| `input-main` | main | no | Upstream outputs merged into the sidecar-side `input_data` object |

## Parameters

| Name | Type | Default | Required | displayOptions.show | Description |
|------|------|---------|----------|---------------------|-------------|
| `code` | string (code editor) | (required, `min_length=1`) | yes | - | JavaScript source. User must assign to `output` |
| `timeout` | number | `30` (ge=1, le=600) | no | - | Seconds - multiplied by 1000 and forwarded as millisecond timeout to the sidecar |

`CodeExecutorParams` uses `extra="allow"` (extra params persist but are unread).

## Sidecar client singleton

`get_nodejs_client()` in [`_nodejs.py`](../../../server/nodes/code/_nodejs.py) lazily
constructs one `NodeJSClient` shared across the JS + TS plugins (base URL from
`NODEJS_EXECUTOR_URL`, else `http://localhost:${NODEJS_EXECUTOR_PORT}`; request
timeout from `NODEJS_EXECUTOR_TIMEOUT`; no per-call kwargs from the plugin) and,
unless `NODEJS_EXECUTOR_URL` points at an external executor, asks the
plugin-owned supervisor to `ensure_started()` the sidecar on the bun runtime
(`OPENCOMPANY_BUN_BIN`, else `bun` on PATH).

## Outputs (handles)

| Handle | Shape | Description |
|--------|-------|-------------|
| `output-main` | object | Standard envelope payload (node declares only `input-main` / `output-main`; `usable_as_tool=True` exposes the same payload as the `javascript_code` tool result) |

### Output payload

```ts
{
  output: any;              // Value the sidecar read from `output` in the script
  console_output: string;   // Captured console.log/.error etc.
}
```

`node_output_schemas.CodeExecutorOutput` declares only `output` (the
`_OutputBase` base allows extra fields like `console_output`).

## Logic Flow

```mermaid
flowchart TD
  A[execute_op] --> B{code strip empty?}
  B -- yes --> E[raise NodeUserError:<br/>No code provided]
  B -- no --> C[timeout_ms = timeout * 1000]
  C --> D[input_data = ctx.raw connected_outputs or {}<br/>inject workspace_dir]
  D --> F[get_nodejs_client<br/>lazy singleton]
  F --> G[client.execute<br/>POST /execute<br/>language=javascript]
  G -- ClientConnectorError --> H1[raise NodeUserError<br/>JS executor unreachable on NODEJS_EXECUTOR_PORT]
  G -- success=false --> H2[raise NodeUserError<br/>error=result.error]
  G -- success=true --> I[Return dict<br/>output, console_output]
```

## Decision Logic

- **Validation**: `code.strip() == ""` -> `raise NodeUserError("No code provided")`.
- **Timeout unit mismatch**: UI accepts seconds, plugin multiplies by 1000
  before forwarding. Default 30 -> 30000 ms. Pydantic clamps the input to 1-600 s.
- **`workspace_dir` injection**: unconditionally sets
  `input_data["workspace_dir"]`, shadowing any upstream node that happened to
  produce a key with that name.
- **Client reuse**: `get_nodejs_client()`'s `_client` is a **module-global**
  singleton in `_nodejs.py`, fixed at the env-derived `base_url`/`timeout`.
- **Sidecar error propagation**: if `result["success"]` is falsey, the
  plugin raises `NodeUserError(result["error"] or "JavaScript executor failed")`.
- **Sidecar down**: `aiohttp.ClientConnectorError` is caught and re-raised as a
  `NodeUserError` telling the LLM the JS executor is unreachable on
  `NODEJS_EXECUTOR_PORT` and to fall back to `python_executor`.

## Side Effects

- **Database writes**: none.
- **Broadcasts**: none from this handler.
- **External API calls**: `POST http://localhost:${NODEJS_EXECUTOR_PORT}/execute`
  (configurable via `NODEJS_EXECUTOR_URL`). Body:
  `{code, input_data, language: "javascript", timeout}`.
- **File I/O**: none from Python; the sidecar may read/write user packages at
  `server/nodejs/user-packages/` (`bun add` via `/packages/install`).
- **Subprocess**: none directly. The sidecar itself is a long-lived bun
  subprocess supervised by `nodes/code/_runtime.py` (spawned on demand, reaped
  by the lifespan's `shutdown_all_supervisors()`).
- **Module-level state**: the `_client` module global in `_nodejs.py` is created
  on first use and never reset.

## External Dependencies

- **Credentials**: none.
- **Services**: the persistent JS executor sidecar on bun (`OPENCOMPANY_BUN_BIN`
  or `bun` on PATH; bundled by the desktop app), spawned on demand by the
  plugin's supervisor - nothing has to be started by hand.
- **Python packages**: `aiohttp`.
- **Environment variables**: `NODEJS_EXECUTOR_URL`,
  `NODEJS_EXECUTOR_TIMEOUT`, `NODEJS_EXECUTOR_PORT`, `NODEJS_EXECUTOR_HOST`,
  `NODEJS_EXECUTOR_BODY_LIMIT` (all read by the sidecar itself).

## Edge cases & known limits

- **Module-level client singleton**: `_client` in `_nodejs.py` is cached on
  first call at the hard-coded `base_url`/`timeout`. Reset by setting
  `services.code._nodejs._client = None` (or `nodes.code._nodejs._client`).
- **Sidecar down**: connection refused surfaces as
  `error="Cannot connect to host localhost:<NODEJS_EXECUTOR_PORT> ssl:default
  [Connect call failed]"` or similar aiohttp message. No automatic retry.
- **`workspace_dir` key collision**: user code cannot read an upstream
  `workspace_dir` from `input_data` - the handler always overwrites it.
- **Timeout semantics**: the Python-side `timeout` is a ceiling on the
  aiohttp request itself (set once at client creation); the
  `timeout_ms` forwarded in the body is the sidecar's script timeout.
  These two can disagree - if the script timeout is longer than the aiohttp
  timeout, the HTTP call fails before the script finishes.
- **`console_output` may contain partial output**: the sidecar captures
  `console.*` calls into a buffer and returns it at end-of-run, so on a script
  timeout the response carries whatever was captured up to the abort.
- **JSON-only transport**: `output` must be JSON-serialisable on the sidecar
  side. Functions, `undefined`, `BigInt`, circular refs are stripped or
  rejected by `JSON.stringify` before return.

## Related

- **Skills using this as a tool**: [`javascript-skill/SKILL.md`](../../../server/skills/coding_agent/javascript-skill/SKILL.md)
- **Sibling nodes**: [`typescriptExecutor`](./typescriptExecutor.md), [`pythonExecutor`](./pythonExecutor.md), [`montyExecutor`](./montyExecutor.md)
- **Architecture docs**: [DESIGN.md](../../DESIGN.md), [Plugin System](../../plugin_system.md)
