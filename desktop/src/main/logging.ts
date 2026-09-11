import { mkdirSync } from "node:fs";
import { join } from "node:path";

import log from "electron-log/main";

export function initLogging(logsDir: string): typeof log {
  mkdirSync(logsDir, { recursive: true });
  log.transports.file.resolvePathFn = () => join(logsDir, "main.log");
  log.transports.file.maxSize = 10 * 1024 * 1024;
  log.transports.file.format = "[{y}-{m}-{d} {h}:{i}:{s}.{ms}] [{level}] {text}";
  log.transports.console.format = "[{h}:{i}:{s}.{ms}] [{level}] {text}";
  log.initialize();
  return log;
}

export type Logger = typeof log;
