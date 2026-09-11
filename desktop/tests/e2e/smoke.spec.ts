/**
 * Playwright Electron smoke: the packaged-shape app (out/) boots against a
 * pre-provisioned interpreter, the main window lands on the backend
 * origin, /health/ready is 200, and quitting leaves no backend behind.
 *
 * Env:
 *   OPENCOMPANY_DESKTOP_VENV_PYTHON  interpreter to use (CI: <repo>/server/.venv/...)
 *   OPENCOMPANY_DESKTOP_APP_ROOT     app-root to serve (default: desktop/stage/app-root,
 *                                    falls back to the repo checkout)
 * The test sets a throwaway userData dir, TEMPORAL_ENABLED=false (no 114 MB
 * download in CI) and NO_ATTACH so it never latches onto a dev backend.
 */

import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { _electron as electron, expect, test } from "@playwright/test";

const DESKTOP = resolve(__dirname, "..", "..");
const REPO = resolve(DESKTOP, "..");
const MAIN = join(DESKTOP, "out", "main", "index.js");

function defaultVenvPython(): string {
  return process.platform === "win32" ? join(REPO, "server", ".venv", "Scripts", "python.exe") : join(REPO, "server", ".venv", "bin", "python");
}

test("boots, serves the SPA on 127.0.0.1, reports ready, and shuts the backend down", async () => {
  test.skip(!existsSync(MAIN), "run `bun run build` first");
  const python = process.env.OPENCOMPANY_DESKTOP_VENV_PYTHON || defaultVenvPython();
  test.skip(!existsSync(python), `no interpreter at ${python}`);
  const stagedRoot = join(DESKTOP, "stage", "app-root");
  const appRoot = process.env.OPENCOMPANY_DESKTOP_APP_ROOT || (existsSync(join(stagedRoot, "server", "main.py")) ? stagedRoot : REPO);

  const userData = mkdtempSync(join(tmpdir(), "oc-desktop-e2e-"));
  const dataDir = mkdtempSync(join(tmpdir(), "oc-desktop-data-"));

  // Editor-hosted terminals (VS Code, Claude Code) export ELECTRON_RUN_AS_NODE=1,
  // which makes Electron boot as plain Node and `require('electron').app`
  // undefined. Never pass it through.
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;

  const app = await electron.launch({
    args: [MAIN],
    env: {
      ...env,
      OPENCOMPANY_DESKTOP_USER_DATA: userData,
      OPENCOMPANY_DESKTOP_VENV_PYTHON: python,
      OPENCOMPANY_DESKTOP_APP_ROOT: appRoot,
      OPENCOMPANY_DESKTOP_NO_ATTACH: "1",
      DATA_DIR: dataDir,
      TEMPORAL_ENABLED: "false",
    },
    timeout: 60_000,
  });

  // The setup window appears first; the main window replaces it once ready.
  const main = await app.waitForEvent("window", { predicate: (w) => w.url().startsWith("http://127.0.0.1:"), timeout: 180_000 });
  await main.waitForLoadState("domcontentloaded");
  const origin = new URL(main.url()).origin;
  expect(origin).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);

  const ready = await main.evaluate(async () => {
    const r = await fetch("/health/ready");
    return { status: r.status, body: await r.json() };
  });
  expect(ready.status).toBe(200);
  expect(ready.body.ready).toBe(true);
  await expect(main.locator("#root")).toBeVisible();

  const pidFile = join(userData, "backend.pid");
  const backendPid = existsSync(pidFile) ? Number(readFileSync(pidFile, "utf-8").trim()) : 0;
  expect(backendPid).toBeGreaterThan(0);

  await app.close();

  // After quit the backend must be gone (contract §5) and the pid file removed.
  let alive = true;
  const deadline = Date.now() + 40_000;
  while (Date.now() < deadline && alive) {
    try {
      process.kill(backendPid, 0);
      await new Promise((r) => setTimeout(r, 250));
    } catch {
      alive = false;
    }
  }
  expect(alive).toBe(false);
  expect(existsSync(pidFile)).toBe(false);
});
