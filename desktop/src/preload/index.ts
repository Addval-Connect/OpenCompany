import { contextBridge, ipcRenderer } from "electron";

// Keep in sync with src/main/ipc.ts (preload cannot import from main).
const CH = {
  setupLog: "setup:log",
  setupPhase: "setup:phase",
  setupState: "setup:state",
  retry: "setup:retry",
  openLogs: "setup:open-logs",
  quit: "setup:quit",
} as const;

export interface DesktopSetupApi {
  onLog: (cb: (line: string) => void) => void;
  onPhase: (cb: (payload: { phase: string; label: string }) => void) => void;
  onState: (cb: (payload: { state: string; message?: string; detail?: string; logPath?: string }) => void) => void;
  retry: () => void;
  openLogs: () => void;
  quit: () => void;
}

const api: DesktopSetupApi = {
  onLog: (cb) => ipcRenderer.on(CH.setupLog, (_e, line: string) => cb(line)),
  onPhase: (cb) => ipcRenderer.on(CH.setupPhase, (_e, payload) => cb(payload)),
  onState: (cb) => ipcRenderer.on(CH.setupState, (_e, payload) => cb(payload)),
  retry: () => ipcRenderer.send(CH.retry),
  openLogs: () => ipcRenderer.send(CH.openLogs),
  quit: () => ipcRenderer.send(CH.quit),
};

contextBridge.exposeInMainWorld("desktop", api);
