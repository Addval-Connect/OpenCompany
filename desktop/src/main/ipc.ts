/** IPC channel names shared by main, preload and the setup renderer. */

export const IPC = {
  /** main -> setup: one log line */
  setupLog: "setup:log",
  /** main -> setup: { phase, label } */
  setupPhase: "setup:phase",
  /** main -> setup: { state: 'provisioning'|'starting'|'error'|'ready', message?, logPath? } */
  setupState: "setup:state",
  /** setup -> main */
  retry: "setup:retry",
  openLogs: "setup:open-logs",
  quit: "setup:quit",
} as const;

export type SetupState = "provisioning" | "starting" | "error" | "ready";

export interface SetupStatePayload {
  state: SetupState;
  message?: string;
  detail?: string;
  logPath?: string;
}
