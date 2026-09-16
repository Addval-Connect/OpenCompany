import { EventEmitter } from "node:events";

import { describe, expect, it } from "vitest";

import { type ChildLike, stopBackend, waitExit } from "@main/shutdown";

class FakeChild extends EventEmitter implements ChildLike {
  pid = 4242;
  exitCode: number | null = null;
  killed = false;
  stdinEnded = false;
  signals: Array<NodeJS.Signals | number | undefined> = [];
  stdin = { end: () => void (this.stdinEnded = true) };
  kill(signal?: NodeJS.Signals | number): boolean {
    this.signals.push(signal);
    this.killed = true;
    return true;
  }
  exit(code = 0): void {
    this.exitCode = code;
    this.emit("exit", code, null);
  }
}

describe("stopBackend", () => {
  it("returns immediately for an already-exited child", async () => {
    const child = new FakeChild();
    child.exitCode = 0;
    expect(await stopBackend({ child, port: 1, token: "t", post: async () => true })).toBe("already-exited");
  });

  it("posts the token, closes stdin and waits for a graceful exit", async () => {
    const child = new FakeChild();
    const posted: Array<[number, string]> = [];
    const promise = stopBackend({
      child,
      port: 5678,
      token: "secret",
      timeoutMs: 5000,
      platform: "win32",
      post: async (port, token) => (posted.push([port, token]), true),
      treeKill: () => {
        throw new Error("must not tree-kill on a graceful exit");
      },
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(posted).toEqual([[5678, "secret"]]);
    expect(child.stdinEnded).toBe(true);
    child.exit(0);
    expect(await promise).toBe("graceful");
    expect(child.signals).toEqual([]);
  });

  it("falls back to SIGTERM on POSIX when the POST is refused", async () => {
    const child = new FakeChild();
    const promise = stopBackend({ child, port: 1, token: "t", timeoutMs: 5000, platform: "linux", post: async () => false, treeKill: () => undefined });
    await new Promise((r) => setTimeout(r, 20));
    expect(child.signals).toEqual(["SIGTERM"]);
    child.exit(0);
    expect(await promise).toBe("signal");
  });

  it("tree-kills after the timeout", async () => {
    const child = new FakeChild();
    const killed: Array<[number, NodeJS.Platform]> = [];
    const promise = stopBackend({
      child,
      port: 1,
      token: "t",
      timeoutMs: 50,
      platform: "win32",
      post: async () => true,
      treeKill: (pid, platform) => {
        killed.push([pid, platform]);
        setTimeout(() => child.exit(1), 10);
      },
    });
    expect(await promise).toBe("tree-killed");
    expect(killed).toEqual([[4242, "win32"]]);
  });
});

describe("waitExit", () => {
  it("resolves false on timeout and true on exit", async () => {
    const child = new FakeChild();
    expect(await waitExit(child, 30)).toBe(false);
    setTimeout(() => child.exit(0), 10);
    expect(await waitExit(child, 1000)).toBe(true);
    expect(await waitExit(child, 1)).toBe(true);
  });
});
