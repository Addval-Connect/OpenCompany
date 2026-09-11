/**
 * Assemble `stage/` — everything electron-builder ships as extraResources.
 *
 *   stage/app-root/        the backend tree in the sibling layout core.approot expects
 *   stage/runtime/<t>/     uv, python, node for target <t> (see fetch-runtimes.ts)
 *   stage/manifest.json    what was staged, for the invariant test + release notes
 *
 * The app-root file list is NOT hand-maintained. `npm pack --dry-run --json`
 * at the repo root yields exactly the files the published npm package ships
 * (the root package.json `files` allowlist filtered by .npmignore), which is
 * the same sibling layout `company start` already runs from. We take that
 * list, drop what a desktop bundle never needs (the CLI, install scripts,
 * client sources, backend tests) and force-include the few files the
 * .npmignore hides but the desktop needs (server/uv.lock).
 *
 * The Node executor sidecar is re-bundled here with its dependencies
 * inlined: server/nodejs/dist/index.js is built with `--packages=external`,
 * and under bun's isolated linker `server/nodejs/node_modules/express` is a
 * symlink into <repo>/node_modules/.bun/ — copying it verbatim would ship a
 * dangling link and the JS executor would fail on first use.
 *
 *   bun run scripts/stage.ts                        # host target runtime
 *   bun run scripts/stage.ts --target mac-arm64,mac-x64
 *   bun run scripts/stage.ts --skip-runtimes        # app-root only
 */

import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, posix } from "node:path";

import { DESKTOP_DIR, REPO_ROOT, STAGE_DIR, fail, log, parseTargetArg, readJson, run } from "./_lib";
import { fetchRuntimes, pinnedVersions } from "./fetch-runtimes";

const APP_ROOT = join(STAGE_DIR, "app-root");

/** Prefixes (posix, repo-relative) a desktop bundle has no use for. */
const DROP_PREFIXES = [
  "cli/",
  "bin/",
  "scripts/",
  "client/src/",
  "client/public/",
  "server/tests/",
  "server/scripts/",
  "server/nodejs/", // re-bundled below
  "server/experiments/",
  "server/.venv/",
];
const DROP_EXACT = new Set(["install.sh", "install.ps1", "pyproject.toml", "client/package.json", "client/index.html", "client/vite.config.js", "client/vitest.config.ts", "client/tsconfig.json", "client/tsconfig.app.json", "client/tsconfig.node.json", "client/eslint.config.js", "client/components.json", "client/tailwind.config.js", "client/postcss.config.js"]);
const DROP_SEGMENTS = ["__pycache__", ".pytest_cache", "node_modules", ".vite"];
// Runtime / test artifacts that .npmignore's `*.db` should hide but npm's
// ignore matcher does not apply to dot-prefixed names (pytest leaves
// `server/.conversation-<hex>.db` behind).
const DROP_SUFFIXES = [".db", ".db-journal", ".db-shm", ".db-wal", ".sqlite", ".log", ".pyc", ".pyo"];

/** Files the .npmignore hides (lockfiles) but the desktop must ship. */
const FORCE_INCLUDE = ["server/uv.lock", "server/pyproject.toml", "server/nodejs/package.json", ".env.template", "package.json"];

function npmPackFileList(): string[] {
  const out = run(process.platform === "win32" ? "npm.cmd" : "npm", ["pack", "--dry-run", "--json", "--ignore-scripts"], { cwd: REPO_ROOT });
  const start = out.indexOf("[");
  const parsed = JSON.parse(out.slice(start)) as Array<{ files: Array<{ path: string }> }>;
  const first = parsed[0];
  if (!first) fail("npm pack --dry-run returned no package");
  return first.files.map((f) => f.path.replace(/\\/g, "/"));
}

function keep(path: string): boolean {
  if (DROP_EXACT.has(path)) return false;
  if (DROP_SUFFIXES.some((ext) => path.endsWith(ext))) return false;
  if (DROP_PREFIXES.some((p) => path.startsWith(p))) return false;
  if (path.split("/").some((seg) => DROP_SEGMENTS.includes(seg))) return false;
  if (path.startsWith("client/") && !path.startsWith("client/dist/")) return false;
  return true;
}

function copyInto(rel: string): void {
  const src = join(REPO_ROOT, rel);
  if (!existsSync(src)) fail(`staged file missing from checkout: ${rel} (run \`bun run build\` first?)`);
  const dest = join(APP_ROOT, rel);
  mkdirSync(dirname(dest), { recursive: true });
  copyFileSync(src, dest);
}

function bundleSidecar(): void {
  const sidecarDir = join(REPO_ROOT, "server", "nodejs");
  const outfile = join(APP_ROOT, "server", "nodejs", "dist", "index.js");
  mkdirSync(dirname(outfile), { recursive: true });
  // esbuild resolves through the sidecar's own node_modules (bun symlinks
  // are followed), so run it from there. The banner restores `require`
  // for the CJS-style dynamic requires inside express/body-parser once
  // they are inlined into an ESM output.
  const esbuild = process.platform === "win32" ? "bun.exe" : "bun";
  run(
    esbuild,
    [
      "x",
      "esbuild",
      "src/index.ts",
      "--bundle",
      "--platform=node",
      "--target=node22",
      "--format=esm",
      "--banner:js=import { createRequire as __oc_createRequire } from 'node:module'; const require = __oc_createRequire(import.meta.url);",
      `--outfile=${outfile}`,
    ],
    { cwd: sidecarDir },
  );
  const text = readFileSync(outfile, "utf-8");
  if (/^\s*(import|export)[^\n]*['"]express['"]/m.test(text) || /require\(["']express["']\)/.test(text)) {
    fail("sidecar bundle still references express externally; inlining failed");
  }
  log(`sidecar bundled -> ${posix.relative(REPO_ROOT.replace(/\\/g, "/"), outfile.replace(/\\/g, "/"))}`);
}

function stageAppRoot(): { files: number } {
  rmSync(APP_ROOT, { recursive: true, force: true });
  mkdirSync(APP_ROOT, { recursive: true });

  const listed = npmPackFileList();
  const kept = listed.filter(keep);
  const all = new Set<string>([...kept, ...FORCE_INCLUDE]);
  for (const rel of all) copyInto(rel);

  if (!existsSync(join(APP_ROOT, "client", "dist", "index.html"))) {
    fail("client/dist/index.html not staged — build the client first (bun run --filter react-flow-client build)");
  }
  bundleSidecar();
  return { files: all.size + 1 };
}

async function main(): Promise<void> {
  const argv = process.argv;
  const targets = parseTargetArg(argv);
  const skipRuntimes = argv.includes("--skip-runtimes");

  const { files } = stageAppRoot();
  log(`app-root staged: ${files} files`);

  if (!skipRuntimes) await fetchRuntimes(targets);

  const rootPkg = readJson<{ version: string }>(join(REPO_ROOT, "package.json"));
  const manifest = {
    stagedAt: new Date().toISOString(),
    appVersion: rootPkg.version,
    targets: skipRuntimes ? [] : targets,
    runtimes: pinnedVersions(),
    appRootFiles: files,
  };
  writeFileSync(join(STAGE_DIR, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  log(`manifest written -> ${join(STAGE_DIR, "manifest.json")}`);
  log(`done (desktop dir: ${DESKTOP_DIR})`);
}

main().catch((err) => fail(String(err?.stack ?? err)));
