/**
 * Download + verify + extract the pinned third-party runtimes (uv,
 * python-build-standalone, Node) for one or more targets into
 * `stage/runtime/<os>-<arch>/{uv,python,node}`.
 *
 *   bun run scripts/fetch-runtimes.ts                 # host target
 *   bun run scripts/fetch-runtimes.ts --target mac-arm64,mac-x64
 *
 * Versions live in `runtimes.json` and nowhere else. Every archive is
 * checked against the upstream checksum manifest before extraction:
 *   uv     -> `<asset>.sha256` sidecar files on the GitHub release
 *   python -> the release's `SHA256SUMS`
 *   node   -> `SHASUMS256.txt` in the dist directory
 * Downloads are cached in `vendor/<name>/<version>/` so CI can restore
 * them; a cache hit is still re-verified.
 *
 * Resulting layout (what src/main/paths.ts expects):
 *   runtime/uv/uv[.exe]
 *   runtime/python/python.exe            (win)  | runtime/python/bin/python3 (posix)
 *   runtime/node/node.exe, npm.cmd        (win)  | runtime/node/bin/{node,npm,npx} (posix)
 */

import { chmodSync, existsSync, readdirSync, rmSync } from "node:fs";
import { join } from "node:path";

import {
  DESKTOP_DIR,
  STAGE_DIR,
  VENDOR_DIR,
  type TargetKey,
  digestFromManifest,
  download,
  ensureDir,
  extractArchive,
  fail,
  fetchText,
  fileSizeMb,
  log,
  parseTargetArg,
  readJson,
  sha256File,
} from "./_lib";

interface Asset {
  file: string;
  strip: number;
}
interface RuntimeSpec {
  version?: string;
  release?: string;
  base: string;
  checksum: "sidecar" | string;
  assets: Record<string, Asset>;
}
interface Runtimes {
  uv: RuntimeSpec;
  python: RuntimeSpec;
  node: RuntimeSpec;
}

const RUNTIMES = readJson<Runtimes>(join(DESKTOP_DIR, "runtimes.json"));

function baseUrl(spec: RuntimeSpec): string {
  return spec.base.replace("{version}", spec.version ?? "").replace("{release}", spec.release ?? "");
}

async function expectedDigest(spec: RuntimeSpec, asset: Asset): Promise<string> {
  const base = baseUrl(spec);
  if (spec.checksum === "sidecar") {
    const text = await fetchText(`${base}${asset.file}.sha256`);
    const m = text.trim().match(/^([0-9a-fA-F]{64})/);
    if (!m) throw new Error(`Unparseable sidecar checksum for ${asset.file}: ${text.slice(0, 80)}`);
    return m[1]!.toLowerCase();
  }
  const manifest = await fetchText(`${base}${spec.checksum}`);
  const digest = digestFromManifest(manifest, asset.file);
  if (!digest) throw new Error(`${asset.file} not found in ${spec.checksum}`);
  return digest;
}

async function fetchOne(name: keyof Runtimes, spec: RuntimeSpec, target: TargetKey): Promise<string> {
  const asset = spec.assets[target];
  if (!asset) fail(`runtimes.json: ${name} has no asset for ${target}`);
  const version = spec.version ?? spec.release ?? "unknown";
  const cacheDir = join(VENDOR_DIR, name, version);
  const archive = join(cacheDir, asset.file);
  ensureDir(cacheDir);

  const expected = await expectedDigest(spec, asset);
  if (existsSync(archive) && sha256File(archive) === expected) {
    log(`${name} ${version} [${target}] cached (${fileSizeMb(archive)} MB)`);
  } else {
    const url = `${baseUrl(spec)}${asset.file}`;
    log(`${name} ${version} [${target}] downloading ${url}`);
    await download(url, archive);
    const actual = sha256File(archive);
    if (actual !== expected) {
      rmSync(archive, { force: true });
      fail(`${asset.file} sha256 mismatch: expected ${expected}, got ${actual}`);
    }
    log(`${name} ${version} [${target}] verified (${fileSizeMb(archive)} MB)`);
  }

  const dest = join(STAGE_DIR, "runtime", target, name);
  rmSync(dest, { recursive: true, force: true });
  extractArchive(archive, dest, asset.strip);
  return dest;
}

function markExecutable(dir: string): void {
  if (process.platform === "win32") return;
  const bin = existsSync(join(dir, "bin")) ? join(dir, "bin") : dir;
  for (const entry of readdirSync(bin)) {
    try {
      chmodSync(join(bin, entry), 0o755);
    } catch {
      /* symlinks / dirs */
    }
  }
}

function verifyLayout(target: TargetKey, dirs: Record<keyof Runtimes, string>): void {
  const win = target.startsWith("win");
  const checks: Array<[string, string]> = [
    ["uv", join(dirs.uv, win ? "uv.exe" : "uv")],
    ["python", win ? join(dirs.python, "python.exe") : join(dirs.python, "bin", "python3")],
    ["node", win ? join(dirs.node, "node.exe") : join(dirs.node, "bin", "node")],
    ["npm", win ? join(dirs.node, "npm.cmd") : join(dirs.node, "bin", "npm")],
  ];
  for (const [label, path] of checks) {
    if (!existsSync(path)) fail(`${label} missing after extraction: ${path}`);
  }
}

export async function fetchRuntimes(targets: TargetKey[]): Promise<void> {
  for (const target of targets) {
    const dirs = {
      uv: await fetchOne("uv", RUNTIMES.uv, target),
      python: await fetchOne("python", RUNTIMES.python, target),
      node: await fetchOne("node", RUNTIMES.node, target),
    };
    if (target.startsWith(process.platform === "win32" ? "win" : process.platform === "darwin" ? "mac" : "linux")) {
      markExecutable(dirs.uv);
      markExecutable(dirs.python);
      markExecutable(dirs.node);
    }
    verifyLayout(target, dirs);
    log(`runtime staged for ${target} -> ${join(STAGE_DIR, "runtime", target)}`);
  }
}

export function pinnedVersions(): { uv: string; python: string; node: string } {
  return {
    uv: RUNTIMES.uv.version!,
    python: RUNTIMES.python.version!,
    node: RUNTIMES.node.version!,
  };
}

if (import.meta.main) {
  fetchRuntimes(parseTargetArg(process.argv)).catch((err) => fail(String(err?.stack ?? err)));
}
