/**
 * Copy the root package.json version (written by `company version sync`
 * from the git tag) into desktop/package.json so electron-builder's
 * artifacts and electron-updater's feed carry the same version as the
 * npm release. Run before `bun run dist` in CI.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { DESKTOP_DIR, REPO_ROOT, log } from "./_lib";

const root = JSON.parse(readFileSync(join(REPO_ROOT, "package.json"), "utf-8")) as { version: string };
const desktopPath = join(DESKTOP_DIR, "package.json");
const desktop = JSON.parse(readFileSync(desktopPath, "utf-8")) as { version: string };

if (desktop.version === root.version) {
  log(`desktop/package.json already at ${root.version}`);
} else {
  desktop.version = root.version;
  writeFileSync(desktopPath, JSON.stringify(desktop, null, 2) + "\n");
  log(`desktop/package.json -> ${root.version}`);
}
