/**
 * The staged bundle (desktop/stage, produced by scripts/stage.ts) must
 * satisfy every path the backend's core.approot and the shell's paths.ts
 * assume. Run after `bun run stage` and before packaging; CI fails the
 * release if the tree drifts from what cli/commands/build.py produces.
 */

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { resolveLayout, targetKey } from "@main/paths";

const DESKTOP = resolve(__dirname, "..", "..");
const STAGE = join(DESKTOP, "stage");
const APP_ROOT = join(STAGE, "app-root");
const RUNTIME = join(STAGE, "runtime", targetKey(process.platform, process.arch));
const staged = existsSync(join(APP_ROOT, "server", "main.py"));
const runtimesStaged = existsSync(RUNTIME);

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

describe.skipIf(!staged)("staged app-root", () => {
  it("contains the sibling layout core.approot expects", () => {
    for (const rel of [
      "server/main.py",
      "server/core/approot.py",
      "server/core/desktop.py",
      "server/pyproject.toml",
      "server/uv.lock",
      "client/dist/index.html",
      ".env.template",
      "package.json",
      ".opencompany/workflows",
    ]) {
      expect(existsSync(join(APP_ROOT, rel)), rel).toBe(true);
    }
    expect(readdirSync(join(APP_ROOT, ".opencompany", "workflows")).filter((f) => f.endsWith(".json")).length).toBeGreaterThan(0);
    expect(readdirSync(join(APP_ROOT, "client", "dist", "assets")).length).toBeGreaterThan(0);
  });

  it("ships no venv, caches, tests, CLI or client sources", () => {
    const files = walk(APP_ROOT).map((p) => p.slice(APP_ROOT.length + 1).replace(/\\/g, "/"));
    const leaked = files.filter(
      (f) =>
        f.startsWith("server/.venv/") ||
        f.includes("/__pycache__/") ||
        f.endsWith(".pyc") ||
        f.startsWith("server/tests/") ||
        f.startsWith("cli/") ||
        f.startsWith("bin/") ||
        f.startsWith("scripts/") ||
        f.startsWith("client/src/") ||
        f.includes("/node_modules/") ||
        f.endsWith(".db"),
    );
    expect(leaked).toEqual([]);
  });

  it("carries the version the root package.json declares", () => {
    const root = JSON.parse(readFileSync(join(DESKTOP, "..", "package.json"), "utf-8")) as { version: string };
    const stagedPkg = JSON.parse(readFileSync(join(APP_ROOT, "package.json"), "utf-8")) as { version: string };
    expect(stagedPkg.version).toBe(root.version);
    const manifest = JSON.parse(readFileSync(join(STAGE, "manifest.json"), "utf-8")) as { appVersion: string; runtimes: Record<string, string> };
    expect(manifest.appVersion).toBe(root.version);
    expect(manifest.runtimes.python ?? "").toMatch(/^3\.12\./);
    expect(manifest.runtimes.bun ?? "").toMatch(/^\d+\.\d+\.\d+$/);
    expect(manifest.runtimes.node).toBeUndefined();
  });
});

describe.skipIf(!staged || !runtimesStaged)("staged runtimes", () => {
  const layout = resolveLayout({ resources: STAGE, userData: join(STAGE, "_ud"), runtimeDir: RUNTIME });

  it("has uv, python and bun where paths.ts looks, and no node or npm", () => {
    expect(existsSync(layout.uvBin), layout.uvBin).toBe(true);
    expect(existsSync(layout.pythonBin), layout.pythonBin).toBe(true);
    expect(existsSync(layout.bunBin), layout.bunBin).toBe(true);
    expect(existsSync(join(layout.bunDir, "LICENSE.md"))).toBe(true);
    expect(existsSync(join(layout.runtimeDir, "node"))).toBe(false);
  });

  it("runs the bundled interpreters", () => {
    const py = spawnSync(layout.pythonBin, ["--version"], { encoding: "utf-8" });
    expect(py.status, py.stderr).toBe(0);
    expect(`${py.stdout}${py.stderr}`).toMatch(/Python 3\.12\./);
    const bun = spawnSync(layout.bunBin, ["--version"], { encoding: "utf-8" });
    expect(bun.status).toBe(0);
    expect(bun.stdout.trim()).toMatch(/^\d+\.\d+\.\d+$/);
    const uv = spawnSync(layout.uvBin, ["--version"], { encoding: "utf-8" });
    expect(uv.status).toBe(0);
    expect(uv.stdout).toMatch(/^uv \d+\.\d+\.\d+/);
  });
});
