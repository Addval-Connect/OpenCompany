# OpenCompany desktop shell

Electron host for the OpenCompany backend. It ships `uv`, a standalone
Python and Node inside the installer, provisions the backend's virtual
environment in the user's data directory on first launch, spawns uvicorn,
and shows the backend-served UI in a native window.

Full documentation: [docs-internal/desktop_app.md](../docs-internal/desktop_app.md)
and the backend contract in
[docs-internal/desktop_host_contract.md](../docs-internal/desktop_host_contract.md).

## Develop

This directory is a standalone bun package (not a workspace member).

```bash
# once, from the repo root: build the client + sidecar the shell serves
bun install && bun run --filter react-flow-client build && bun run --filter opencompany-nodejs-executor build

cd desktop
bun install
bun run stage            # app-root + pinned runtimes for this machine -> stage/
bun run dev              # electron-vite dev (main/preload HMR, setup page HMR)
```

Run against the checkout without staging or provisioning:

```bash
OPENCOMPANY_DESKTOP_APP_ROOT=..  OPENCOMPANY_DESKTOP_VENV_PYTHON=../server/.venv/bin/python  bun run dev
```

## Test

```bash
bun run typecheck
bun run test              # unit (vitest)
bun run test:invariants   # staged tree matches what the backend expects
bun run build && bun run test:e2e   # Playwright Electron smoke
```

## Package

```bash
bun run gen-icons
bun run dist              # installers -> release/
```

Versions of the bundled runtimes are pinned in `runtimes.json`.
