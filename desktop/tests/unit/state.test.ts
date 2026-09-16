import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { loadState, saveState } from "@main/state";

describe("desktop state", () => {
  it("round-trips and tolerates a missing or corrupt file", () => {
    const dir = mkdtempSync(join(tmpdir(), "oc-desktop-state-"));
    const file = join(dir, "nested", "desktop-state.json");
    expect(loadState(file)).toEqual({});
    saveState(file, { port: 5690, lastAppVersion: "1.2.3" });
    expect(loadState(file)).toEqual({ port: 5690, lastAppVersion: "1.2.3" });
    writeFileSync(file, "{not json");
    expect(loadState(file)).toEqual({});
  });
});
