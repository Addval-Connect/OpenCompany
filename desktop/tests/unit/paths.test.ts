import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { bundledPython, electronOs, resolveLayout, targetKey, venvPython } from "@main/paths";

describe("resolveLayout", () => {
  it("derives the sibling layout under resources and pyenv under userData", () => {
    const l = resolveLayout({ resources: "/res", userData: "/ud", platform: "linux" });
    expect(l.appRoot).toBe(join("/res", "app-root"));
    expect(l.serverDir).toBe(join("/res", "app-root", "server"));
    expect(l.clientDist).toBe(join("/res", "app-root", "client", "dist"));
    expect(l.runtimeDir).toBe(join("/res", "runtime"));
    expect(l.uvBin).toBe(join("/res", "runtime", "uv", "uv"));
    expect(l.pythonBin).toBe(join("/res", "runtime", "python", "bin", "python3"));
    expect(l.nodeBin).toBe(join("/res", "runtime", "node", "bin", "node"));
    expect(l.venvDir).toBe(join("/ud", "pyenv", "venv"));
    expect(l.userEnvFile).toBe(join("/ud", "desktop.env"));
    expect(l.logsDir).toBe(join("/ud", "logs"));
  });

  it("uses Windows executable names", () => {
    const l = resolveLayout({ resources: "C:\\res", userData: "C:\\ud", platform: "win32" });
    expect(l.uvBin.endsWith(join("uv", "uv.exe"))).toBe(true);
    expect(l.pythonBin.endsWith(join("python", "python.exe"))).toBe(true);
    expect(l.nodeBin.endsWith(join("node", "node.exe"))).toBe(true);
    expect(l.nodeBinDir).toBe(l.nodeDir);
  });

  it("honours app-root and runtime overrides independently", () => {
    const l = resolveLayout({ resources: "/res", userData: "/ud", platform: "darwin", appRoot: "/repo", runtimeDir: "/rt" });
    expect(l.appRoot).toBe("/repo");
    expect(l.serverDir).toBe(join("/repo", "server"));
    expect(l.uvBin).toBe(join("/rt", "uv", "uv"));
  });
});

describe("helpers", () => {
  it("maps platforms to electron-builder os names and target keys", () => {
    expect(electronOs("win32")).toBe("win");
    expect(electronOs("darwin")).toBe("mac");
    expect(electronOs("linux")).toBe("linux");
    expect(targetKey("darwin", "arm64")).toBe("mac-arm64");
    expect(targetKey("win32", "x64")).toBe("win-x64");
    expect(targetKey("linux", "ia32")).toBe("linux-x64");
  });

  it("locates venv and bundled interpreters per platform", () => {
    expect(venvPython("/v", "win32")).toBe(join("/v", "Scripts", "python.exe"));
    expect(venvPython("/v", "linux")).toBe(join("/v", "bin", "python"));
    expect(bundledPython("/rt", "win32")).toBe(join("/rt", "python", "python.exe"));
    expect(bundledPython("/rt", "darwin")).toBe(join("/rt", "python", "bin", "python3"));
  });
});
