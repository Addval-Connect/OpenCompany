/** Small persisted shell state (`desktop-state.json`). */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export interface DesktopState {
  /** Last port the backend was served on; reused so the SPA origin (and its localStorage) stays stable. */
  port?: number;
  lastAppVersion?: string;
  lastProvisionStamp?: string;
}

export function loadState(file: string): DesktopState {
  try {
    if (!existsSync(file)) return {};
    const parsed = JSON.parse(readFileSync(file, "utf-8")) as DesktopState;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function saveState(file: string, state: DesktopState): void {
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(state, null, 2) + "\n", "utf-8");
}
