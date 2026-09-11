import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { resolveLayout, venvPython } from "@main/paths";
import { type CommandResult, computeStamp, expectedStamp, needsProvision, readStamp, runProvision, tail, writeStamp } from "@main/provision";

function makeLayout(opts: { bundledPython: boolean }) {
  const root = mkdtempSync(join(tmpdir(), "oc-desktop-prov-"));
  const layout = resolveLayout({ resources: join(root, "res"), userData: join(root, "ud"), platform: process.platform });
  mkdirSync(layout.serverDir, { recursive: true });
  writeFileSync(join(layout.serverDir, "uv.lock"), "lock-v1");
  writeFileSync(join(layout.serverDir, "pyproject.toml"), "[project]\nname='x'\n");
  mkdirSync(join(layout.uvBin, ".."), { recursive: true });
  writeFileSync(layout.uvBin, "");
  if (opts.bundledPython) {
    mkdirSync(join(layout.pythonBin, ".."), { recursive: true });
    writeFileSync(layout.pythonBin, "");
  }
  return layout;
}

/** A fake command runner that records calls and fabricates the venv on sync. */
function fakeRunner(layout: ReturnType<typeof makeLayout>, opts: { failBundledSync?: boolean } = {}) {
  const calls: Array<{ bin: string; args: string[]; env: NodeJS.ProcessEnv }> = [];
  const runner = async (bin: string, args: string[], o: { env: NodeJS.ProcessEnv }): Promise<CommandResult> => {
    calls.push({ bin, args, env: o.env });
    if (args[0] === "--version") {
      return { code: 0, output: bin === layout.uvBin ? "uv 0.12.13 (abc 2026-09-01)" : "Python 3.12.14" };
    }
    if (args[0] === "sync") {
      const usesBundled = args.includes(layout.pythonBin);
      if (usesBundled && opts.failBundledSync) return { code: 2, output: "error: interpreter rejected" };
      const py = venvPython(layout.venvDir, layout.platform);
      mkdirSync(join(py, ".."), { recursive: true });
      writeFileSync(py, "");
      return { code: 0, output: "Resolved 219 packages" };
    }
    return { code: 0, output: "" };
  };
  return { runner, calls };
}

describe("computeStamp", () => {
  it("changes when any input changes", () => {
    const base = { lockText: "a", pyprojectText: "b", pythonVersion: "3.12.14", uvVersion: "0.12.13" };
    const s = computeStamp(base);
    expect(computeStamp({ ...base })).toBe(s);
    expect(computeStamp({ ...base, lockText: "a2" })).not.toBe(s);
    expect(computeStamp({ ...base, pyprojectText: "b2" })).not.toBe(s);
    expect(computeStamp({ ...base, pythonVersion: "3.12.15" })).not.toBe(s);
    expect(computeStamp({ ...base, uvVersion: "0.13.0" })).not.toBe(s);
  });
});

describe("needsProvision", () => {
  it("is true without a venv, false after a matching stamp, true again on mismatch", () => {
    const layout = makeLayout({ bundledPython: true });
    expect(needsProvision(layout, "s1")).toBe(true);
    const py = venvPython(layout.venvDir, layout.platform);
    mkdirSync(join(py, ".."), { recursive: true });
    writeFileSync(py, "");
    writeStamp(layout.venvDir, { stamp: "s1", pythonVersion: "3.12.14", uvVersion: "0.12.13", interpreter: "bundled", createdAt: "now" });
    expect(needsProvision(layout, "s1")).toBe(false);
    expect(needsProvision(layout, "s2")).toBe(true);
    expect(readStamp(layout.venvDir)?.stamp).toBe("s1");
  });
});

describe("runProvision", () => {
  it("syncs with the bundled interpreter and writes the stamp", async () => {
    const layout = makeLayout({ bundledPython: true });
    const { runner, calls } = fakeRunner(layout);
    const expected = await expectedStamp(layout, {}, runner);
    expect(expected.pythonVersion).toBe("3.12.14");
    expect(expected.uvVersion).toBe("0.12.13");

    const lines: string[] = [];
    const stamp = await runProvision({ layout, env: { PATH: "" }, onLine: (l) => lines.push(l), runner }, expected);

    const sync = calls.find((c) => c.args[0] === "sync")!;
    expect(sync.bin).toBe(layout.uvBin);
    expect(sync.args).toEqual(["sync", "--frozen", "--no-dev", "--extra", "docs", "--project", layout.serverDir, "--python", layout.pythonBin]);
    expect(sync.env.UV_PYTHON_PREFERENCE).toBe("only-system");
    expect(stamp.interpreter).toBe("bundled");
    expect(readStamp(layout.venvDir)?.stamp).toBe(expected.stamp);
    expect(calls.some((c) => c.args[0] === "python" && c.args[1] === "install")).toBe(false);
    expect(calls.some((c) => c.args[0] === "cache")).toBe(true);
    expect(lines.at(-1)).toBe("Backend environment ready.");
  });

  it("falls back to a uv-managed interpreter when the bundled one is rejected", async () => {
    const layout = makeLayout({ bundledPython: true });
    const { runner, calls } = fakeRunner(layout, { failBundledSync: true });
    const expected = await expectedStamp(layout, {}, runner);
    const stamp = await runProvision({ layout, env: {}, onLine: () => undefined, runner }, expected);

    const install = calls.find((c) => c.args[0] === "python" && c.args[1] === "install")!;
    expect(install.args).toEqual(["python", "install", "3.12"]);
    expect(install.env.UV_PYTHON_PREFERENCE).toBe("only-managed");
    const syncs = calls.filter((c) => c.args[0] === "sync");
    expect(syncs).toHaveLength(2);
    expect(syncs[1]!.args.slice(-2)).toEqual(["--python", "3.12"]);
    expect(stamp.interpreter).toBe("managed");
  });

  it("goes straight to a managed interpreter when none is bundled", async () => {
    const layout = makeLayout({ bundledPython: false });
    const { runner, calls } = fakeRunner(layout);
    const expected = await expectedStamp(layout, {}, runner);
    expect(expected.pythonVersion).toBe("managed-3.12");
    const stamp = await runProvision({ layout, env: {}, onLine: () => undefined, runner }, expected);
    expect(stamp.interpreter).toBe("managed");
    expect(calls.filter((c) => c.args[0] === "sync")).toHaveLength(1);
  });

  it("surfaces the tail of uv output on failure", async () => {
    const layout = makeLayout({ bundledPython: false });
    const runner = async (bin: string, args: string[]): Promise<CommandResult> =>
      args[0] === "--version" ? { code: 0, output: "uv 0.12.13" } : { code: 1, output: "line1\nline2\nfatal: no network" };
    const expected = await expectedStamp(layout, {}, runner);
    await expect(runProvision({ layout, env: {}, onLine: () => undefined, runner }, expected)).rejects.toThrow(/fatal: no network/);
  });
});

describe("tail", () => {
  it("keeps the last N lines", () => {
    expect(tail("a\nb\nc\nd", 2)).toBe("c\nd");
  });
});
