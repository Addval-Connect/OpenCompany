/**
 * Shared helpers for the desktop build scripts (run with `bun run`).
 *
 * Deliberately dependency-free: Node 22 / bun globals only (fetch, crypto,
 * fs, child_process). Archives are extracted with the platform `tar`, which
 * exists on Windows 10+ (bsdtar, also reads .zip), macOS and every Linux CI
 * image, so no extraction library is needed.
 */

import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { createWriteStream, existsSync, mkdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";

export const DESKTOP_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const REPO_ROOT = resolve(DESKTOP_DIR, "..");
export const STAGE_DIR = join(DESKTOP_DIR, "stage");
export const VENDOR_DIR = join(DESKTOP_DIR, "vendor");

export type TargetKey = "win-x64" | "mac-arm64" | "mac-x64" | "linux-x64";

/** electron-builder spells os as win|mac|linux and arch as x64|arm64. */
export function hostTargetKey(): TargetKey {
  const os = process.platform === "win32" ? "win" : process.platform === "darwin" ? "mac" : "linux";
  const arch = process.arch === "arm64" ? "arm64" : "x64";
  const key = `${os}-${arch}`;
  if (!["win-x64", "mac-arm64", "mac-x64", "linux-x64"].includes(key)) {
    throw new Error(`Unsupported host target ${key}`);
  }
  return key as TargetKey;
}

export function parseTargetArg(argv: string[]): TargetKey[] {
  const idx = argv.indexOf("--target");
  if (idx === -1) return [hostTargetKey()];
  const raw = argv[idx + 1];
  if (!raw) throw new Error("--target needs a value, e.g. --target mac-arm64,mac-x64");
  return raw.split(",").map((t) => t.trim()) as TargetKey[];
}

export function log(msg: string): void {
  process.stdout.write(`[desktop] ${msg}\n`);
}

export function fail(msg: string): never {
  process.stderr.write(`[desktop] ERROR: ${msg}\n`);
  process.exit(1);
}

export function run(cmd: string, args: string[], opts: { cwd?: string; env?: NodeJS.ProcessEnv } = {}): string {
  const res = spawnSync(cmd, args, {
    cwd: opts.cwd,
    env: { ...process.env, ...(opts.env ?? {}) },
    encoding: "utf-8",
    stdio: ["ignore", "pipe", "pipe"],
    shell: process.platform === "win32" && /\.(cmd|bat)$/i.test(cmd),
    maxBuffer: 64 * 1024 * 1024,
  });
  if (res.error) throw res.error;
  if (res.status !== 0) {
    throw new Error(`${cmd} ${args.join(" ")} exited ${res.status}\n${res.stderr}`);
  }
  return res.stdout;
}

export async function download(url: string, dest: string): Promise<void> {
  mkdirSync(dirname(dest), { recursive: true });
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok || !res.body) throw new Error(`GET ${url} -> ${res.status}`);
  const tmp = `${dest}.part`;
  await pipeline(Readable.fromWeb(res.body as never), createWriteStream(tmp));
  rmSync(dest, { force: true });
  // rename is atomic on the same volume
  const { renameSync } = await import("node:fs");
  renameSync(tmp, dest);
}

export async function fetchText(url: string): Promise<string> {
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new Error(`GET ${url} -> ${res.status}`);
  return res.text();
}

export function sha256File(path: string): string {
  const h = createHash("sha256");
  h.update(readFileSync(path));
  return h.digest("hex");
}

/**
 * Find `name`'s digest in a `sha256sum`-style manifest ("<hex>  <name>" or
 * "<hex> *<name>"). Returns null when absent.
 */
export function digestFromManifest(manifest: string, name: string): string | null {
  for (const line of manifest.split(/\r?\n/)) {
    const m = line.trim().match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
    if (m && m[2]!.trim() === name) return m[1]!.toLowerCase();
  }
  return null;
}

/**
 * The tar to extract with. On Windows the system bsdtar
 * (`%SystemRoot%\System32\tar.exe`) reads .zip, .tar.gz and .tar.xz; the GNU
 * tar that Git for Windows puts on PATH reads none of the zips and parses
 * `D:\...` as a remote host, so it is never used when bsdtar exists.
 */
export function tarBinary(): string {
  if (process.platform === "win32") {
    const system = join(process.env.SystemRoot ?? "C:\\Windows", "System32", "tar.exe");
    if (existsSync(system)) return system;
  }
  return "tar";
}

export function extractArchive(archive: string, dest: string, strip: number): void {
  mkdirSync(dest, { recursive: true });
  // Relative archive path from the destination so no argument carries a
  // drive colon (GNU tar would read it as host:path).
  const rel = relative(dest, archive);
  const args = ["-xf", rel];
  if (strip > 0) args.push(`--strip-components=${strip}`);
  run(tarBinary(), args, { cwd: dest });
}

export function fileSizeMb(path: string): string {
  return (statSync(path).size / (1024 * 1024)).toFixed(1);
}

export function ensureDir(path: string): void {
  mkdirSync(path, { recursive: true });
}

export function exists(path: string): boolean {
  return existsSync(path);
}

export function readJson<T = unknown>(path: string): T {
  return JSON.parse(readFileSync(path, "utf-8")) as T;
}
