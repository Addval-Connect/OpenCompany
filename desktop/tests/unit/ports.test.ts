import { createServer } from "node:net";

import { describe, expect, it } from "vitest";

import { choosePort, isPortFree } from "@main/ports";

function listen(): Promise<{ port: number; close: () => Promise<void> }> {
  return new Promise((resolve) => {
    const server = createServer();
    server.listen({ port: 0, host: "127.0.0.1" }, () => {
      const port = (server.address() as { port: number }).port;
      resolve({ port, close: () => new Promise((r) => server.close(() => r())) });
    });
  });
}

describe("isPortFree", () => {
  it("detects a bound port", async () => {
    const held = await listen();
    expect(await isPortFree(held.port)).toBe(false);
    await held.close();
    expect(await isPortFree(held.port)).toBe(true);
  });
});

describe("choosePort", () => {
  const busy = new Set<number>();
  const isFree = async (p: number) => !busy.has(p);

  it("takes the first free preferred port", async () => {
    busy.clear();
    const d = await choosePort({ preferred: [5678], scanFrom: 5679, scanTo: 5699, isFree, probe: async () => null });
    expect(d).toEqual({ port: 5678, attach: false });
  });

  it("prefers the persisted port over the default", async () => {
    busy.clear();
    const d = await choosePort({ preferred: [5683, 5678], scanFrom: 5679, scanTo: 5699, isFree, probe: async () => null });
    expect(d.port).toBe(5683);
  });

  it("attaches when the preferred port is an OpenCompany backend", async () => {
    busy.clear();
    busy.add(5678);
    const d = await choosePort({
      preferred: [5678],
      scanFrom: 5679,
      scanTo: 5699,
      isFree,
      probe: async (p) => (p === 5678 ? { service: "python", version: "9.9.9" } : null),
    });
    expect(d).toEqual({ port: 5678, attach: true, existingVersion: "9.9.9" });
  });

  it("scans past a busy foreign port instead of attaching to it", async () => {
    busy.clear();
    busy.add(5678);
    busy.add(5679);
    const d = await choosePort({ preferred: [5678], scanFrom: 5679, scanTo: 5699, isFree, probe: async () => null });
    expect(d).toEqual({ port: 5680, attach: false });
  });

  it("never attaches when attach is disabled", async () => {
    busy.clear();
    busy.add(5678);
    const d = await choosePort({
      preferred: [5678],
      scanFrom: 5679,
      scanTo: 5699,
      isFree,
      probe: async () => ({ service: "python" }),
      allowAttach: false,
    });
    expect(d).toEqual({ port: 5679, attach: false });
  });

  it("throws when nothing is free", async () => {
    await expect(
      choosePort({ preferred: [1], scanFrom: 2, scanTo: 3, isFree: async () => false, probe: async () => null }),
    ).rejects.toThrow(/No free port/);
  });
});
