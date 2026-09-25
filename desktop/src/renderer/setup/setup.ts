/// <reference lib="dom" />

export {};

interface DesktopSetupApi {
  onLog: (cb: (line: string) => void) => void;
  onPhase: (cb: (payload: { phase: string; label: string }) => void) => void;
  onState: (cb: (payload: { state: string; message?: string; detail?: string; logPath?: string }) => void) => void;
  retry: () => void;
  openLogs: () => void;
  quit: () => void;
}

declare global {
  interface Window {
    desktop: DesktopSetupApi;
  }
}

const MAX_LOG_LINES = 400;

const card = document.querySelector<HTMLElement>(".card")!;
const message = document.getElementById("message")!;
const detail = document.getElementById("detail")!;
const logEl = document.getElementById("log")!;
const retryBtn = document.getElementById("retry") as HTMLButtonElement;
const logsBtn = document.getElementById("logs") as HTMLButtonElement;
const quitBtn = document.getElementById("quit") as HTMLButtonElement;

const lines: string[] = [];

function appendLine(line: string): void {
  lines.push(line);
  if (lines.length > MAX_LOG_LINES) lines.splice(0, lines.length - MAX_LOG_LINES);
  logEl.textContent = lines.join("\n");
  logEl.scrollTop = logEl.scrollHeight;
}

window.desktop.onLog(appendLine);
window.desktop.onPhase(({ label }) => {
  message.textContent = label;
});
window.desktop.onState(({ state, message: msg, detail: det }) => {
  card.dataset.state = state;
  if (msg) message.textContent = msg;
  if (state === "error") {
    detail.textContent = det ?? "";
    detail.hidden = !det;
    retryBtn.hidden = false;
  } else {
    detail.hidden = true;
    retryBtn.hidden = true;
  }
});

retryBtn.addEventListener("click", () => {
  card.dataset.state = "starting";
  retryBtn.hidden = true;
  detail.hidden = true;
  appendLine("--- retry ---");
  window.desktop.retry();
});
logsBtn.addEventListener("click", () => window.desktop.openLogs());
quitBtn.addEventListener("click", () => window.desktop.quit());
