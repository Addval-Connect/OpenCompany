/**
 * Port selection with a stable origin.
 *
 * The SPA's localStorage / IndexedDB caches and any OAuth redirect URIs the
 * user registered are keyed to the origin, so the shell prefers the same
 * port every launch: the persisted one, else the .env.template default
 * (5678), else a scan. If the preferred port is busy AND already serving an
 * OpenCompany backend (a `company serve` the user left running), the shell
 * attaches to it instead of spawning a second one.
 */

import { createServer } from "node:net";

export interface PortDecision {
  port: number;
  /** True when an existing OpenCompany backend answers on `port`; do not spawn. */
  attach: boolean;
  existingVersion?: string;
}

export function isPortFree(port: number, host = "127.0.0.1"): Promise<boolean> {
  return new Promise((resolve) => {
    const server = createServer();
    server.once("error", () => resolve(false));
    server.listen({ port, host, exclusive: true }, () => {
      server.close(() => resolve(true));
    });
  });
}

export interface HealthProbe {
  service?: string;
  version?: string;
}

export async function probeOpenCompany(port: number, timeoutMs = 1500): Promise<HealthProbe | null> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(`http://127.0.0.1:${port}/health`, { signal: ctl.signal });
    if (!res.ok) return null;
    const body = (await res.json()) as HealthProbe;
    return body && body.service === "python" ? body : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export interface ChoosePortOptions {
  preferred: number[];
  scanFrom: number;
  scanTo: number;
  isFree?: (port: number) => Promise<boolean>;
  probe?: (port: number) => Promise<HealthProbe | null>;
  /** When false, never attach to a foreign backend (e2e tests). */
  allowAttach?: boolean;
}

export async function choosePort(opts: ChoosePortOptions): Promise<PortDecision> {
  const isFree = opts.isFree ?? isPortFree;
  const probe = opts.probe ?? probeOpenCompany;
  const allowAttach = opts.allowAttach ?? true;
  const tried = new Set<number>();

  for (const port of opts.preferred) {
    if (tried.has(port)) continue;
    tried.add(port);
    if (await isFree(port)) return { port, attach: false };
    if (allowAttach) {
      const existing = await probe(port);
      if (existing) return { port, attach: true, existingVersion: existing.version };
    }
  }
  for (let port = opts.scanFrom; port <= opts.scanTo; port++) {
    if (tried.has(port)) continue;
    if (await isFree(port)) return { port, attach: false };
  }
  throw new Error(`No free port between ${opts.scanFrom} and ${opts.scanTo}`);
}
