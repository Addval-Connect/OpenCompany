/**
 * First-run (and post-update) provisioning of the backend's Python
 * environment with the bundled `uv` and `python`.
 *
 *   uv sync --frozen --no-dev --extra docs --project <app-root>/server \
 *           --python <bundled python>
 *
 * The venv lands in userData (UV_PROJECT_ENVIRONMENT), never inside the
 * read-only bundle. A stamp (sha256 over uv.lock + pyproject.toml + the
 * bundled Python version + the uv version) decides whether a sync is
 * needed; an app update that changes none of those skips it entirely.
 *
 * Fallback: if uv rejects the bundled interpreter (corrupt extraction,
 * quarantine, missing exec bit), provision with a uv-managed download of
 * the same minor (`uv python install 3.12`) so first run still succeeds,
 * at the cost of one extra download.
 *
 * Pure with respect to Electron; the caller streams `onLine` into the setup
 * window.
 */

import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import type { Layout } from "./paths";
import { venvPython } from "./paths";

export const PYTHON_MINOR = "3.12";
export const STAMP_FILE = ".provision.json";

export interface Stamp {
  stamp: string;
  pythonVersion: string;
  uvVersion: string;
  interpreter: "bundled" | "managed";
  createdAt: string;
}

export interface ProvisionOptions {
  layout: Layout;
  env: NodeJS.ProcessEnv;
  onLine: (line: string) => void;
  /** Injected for tests. */
  runner?: typeof runCommand;
}

export function computeStamp(input: { lockText: string; pyprojectText: string; pythonVersion: string; uvVersion: string }): string {
  const h = createHash("sha256");
  h.update(input.lockText);
  h.update("\n--\n");
  h.update(input.pyprojectText);
  h.update("\n--\n");
  h.update(`python=${input.pythonVersion}\nuv=${input.uvVersion}\n`);
  return h.digest("hex");
}

export function readStamp(venvDir: string): Stamp | null {
  const file = join(venvDir, STAMP_FILE);
  try {
    if (!existsSync(file)) return null;
    return JSON.parse(readFileSync(file, "utf-8")) as Stamp;
  } catch {
    return null;
  }
}

export function writeStamp(venvDir: string, stamp: Stamp): void {
  mkdirSync(venvDir, { recursive: true });
  writeFileSync(join(venvDir, STAMP_FILE), JSON.stringify(stamp, null, 2) + "\n");
}

export function needsProvision(layout: Layout, expectedStamp: string): boolean {
  if (!existsSync(venvPython(layout.venvDir, layout.platform))) return true;
  const current = readStamp(layout.venvDir);
  return !current || current.stamp !== expectedStamp;
}

export interface CommandResult {
  code: number | null;
  output: string;
}

export function runCommand(
  bin: string,
  args: string[],
  opts: { cwd?: string; env: NodeJS.ProcessEnv; onLine?: (line: string) => void },
): Promise<CommandResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, { cwd: opts.cwd, env: opts.env, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    let output = "";
    const feed = (chunk: Buffer) => {
      const text = chunk.toString("utf-8");
      output += text;
      if (opts.onLine) {
        for (const line of text.split(/\r?\n|\r/)) if (line.trim()) opts.onLine(line);
      }
    };
    child.stdout.on("data", feed);
    child.stderr.on("data", feed);
    child.once("error", reject);
    child.once("close", (code) => resolve({ code, output }));
  });
}

export async function toolVersion(bin: string, env: NodeJS.ProcessEnv, runner = runCommand): Promise<string> {
  const res = await runner(bin, ["--version"], { env });
  const m = res.output.match(/(\d+\.\d+\.\d+[^\s]*)/);
  return m ? m[1]! : res.output.trim().split(/\s+/).pop() ?? "unknown";
}

export interface ExpectedStamp {
  stamp: string;
  pythonVersion: string;
  uvVersion: string;
}

export async function expectedStamp(layout: Layout, env: NodeJS.ProcessEnv, runner = runCommand): Promise<ExpectedStamp> {
  const lockText = readFileSync(join(layout.serverDir, "uv.lock"), "utf-8");
  const pyprojectText = readFileSync(join(layout.serverDir, "pyproject.toml"), "utf-8");
  const pythonVersion = existsSync(layout.pythonBin) ? await toolVersion(layout.pythonBin, env, runner) : `managed-${PYTHON_MINOR}`;
  const uvVersion = await toolVersion(layout.uvBin, env, runner);
  return { stamp: computeStamp({ lockText, pyprojectText, pythonVersion, uvVersion }), pythonVersion, uvVersion };
}

function syncArgs(layout: Layout, python: string | null): string[] {
  const args = ["sync", "--frozen", "--no-dev", "--extra", "docs", "--project", layout.serverDir];
  if (python) args.push("--python", python);
  return args;
}

/**
 * Provision (or re-sync) the venv. Resolves with the stamp that was written.
 * Throws with the tail of uv's output on failure.
 */
export async function runProvision(opts: ProvisionOptions, expected: ExpectedStamp): Promise<Stamp> {
  const { layout, onLine } = opts;
  const runner = opts.runner ?? runCommand;
  mkdirSync(dirname(layout.venvDir), { recursive: true });

  let interpreter: Stamp["interpreter"] = "bundled";
  let result: CommandResult;

  if (existsSync(layout.pythonBin)) {
    onLine(`Using bundled Python ${expected.pythonVersion} at ${layout.pythonBin}`);
    onLine("Installing backend dependencies (uv sync)...");
    result = await runner(layout.uvBin, syncArgs(layout, layout.pythonBin), {
      cwd: layout.serverDir,
      env: { ...opts.env, UV_PYTHON_PREFERENCE: "only-system" },
      onLine,
    });
    if (result.code !== 0) {
      onLine(`Bundled interpreter path failed (exit ${result.code}); falling back to a uv-managed Python ${PYTHON_MINOR}.`);
    }
  } else {
    onLine("Bundled Python not present; using a uv-managed interpreter.");
    result = { code: 1, output: "" };
  }

  if (result.code !== 0) {
    interpreter = "managed";
    const install = await runner(layout.uvBin, ["python", "install", PYTHON_MINOR], {
      env: { ...opts.env, UV_PYTHON_PREFERENCE: "only-managed" },
      onLine,
    });
    if (install.code !== 0) {
      throw new Error(`uv python install ${PYTHON_MINOR} failed (exit ${install.code}):\n${tail(install.output)}`);
    }
    onLine("Installing backend dependencies (uv sync)...");
    result = await runner(layout.uvBin, [...syncArgs(layout, null), "--python", PYTHON_MINOR], {
      cwd: layout.serverDir,
      env: { ...opts.env, UV_PYTHON_PREFERENCE: "only-managed" },
      onLine,
    });
    if (result.code !== 0) {
      throw new Error(`uv sync failed (exit ${result.code}):\n${tail(result.output)}`);
    }
  }

  if (!existsSync(venvPython(layout.venvDir, layout.platform))) {
    throw new Error(`uv sync reported success but ${venvPython(layout.venvDir, layout.platform)} does not exist`);
  }

  // Keep the cache from growing across app updates; failure is harmless.
  await runner(layout.uvBin, ["cache", "prune", "--ci"], { env: opts.env }).catch(() => undefined);

  // The backend runs with PYTHONPYCACHEPREFIX (the bundle is read-only on
  // macOS/Linux), and with a prefix set Python ignores the venv's in-tree
  // .pyc files too. Warm the prefix once here so the first launch does not
  // spend ~30 s recompiling 20k site-packages files. Non-fatal.
  onLine("Precompiling Python bytecode...");
  await runner(
    venvPython(layout.venvDir, layout.platform),
    ["-m", "compileall", "-q", "-j", "0", layout.venvDir, layout.serverDir],
    { env: { ...opts.env, PYTHONPYCACHEPREFIX: layout.pycacheDir, PYTHONUTF8: "1" } },
  ).catch(() => undefined);

  const stamp: Stamp = {
    stamp: expected.stamp,
    pythonVersion: expected.pythonVersion,
    uvVersion: expected.uvVersion,
    interpreter,
    createdAt: new Date().toISOString(),
  };
  writeStamp(layout.venvDir, stamp);
  onLine("Backend environment ready.");
  return stamp;
}

export function tail(text: string, lines = 25): string {
  const arr = text.trimEnd().split(/\r?\n/);
  return arr.slice(-lines).join("\n");
}
