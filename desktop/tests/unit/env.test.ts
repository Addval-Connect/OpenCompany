import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";

import { describe, expect, it } from "vitest";

import { buildBackendEnv, parseEnvFile, prependPath } from "@main/env";
import { resolveLayout } from "@main/paths";

function fakeLayout(withBinaries: boolean) {
  const root = mkdtempSync(join(tmpdir(), "oc-desktop-env-"));
  const resources = join(root, "res");
  const userData = join(root, "ud");
  const layout = resolveLayout({ resources, userData, platform: process.platform });
  if (withBinaries) {
    for (const p of [layout.uvBin, layout.nodeBin, layout.pythonBin]) {
      mkdirSync(join(p, ".."), { recursive: true });
      writeFileSync(p, "");
    }
  }
  mkdirSync(userData, { recursive: true });
  return layout;
}

describe("parseEnvFile", () => {
  it("matches the backend parser semantics", () => {
    const parsed = parseEnvFile(['# c', '', 'A=1', 'B="two words"', "C='x'", 'D=a=b', '  E  =  padded ', 'NOPE', 'F="mismatch\''].join("\n"));
    expect(parsed).toEqual({ A: "1", B: "two words", C: "x", D: "a=b", E: "padded", F: "\"mismatch'" });
  });
});

describe("prependPath", () => {
  it("puts new dirs first and dedupes", () => {
    const out = prependPath(["/usr/bin", "/x"].join(delimiter), "/x", "/bundled");
    expect(out.split(delimiter)).toEqual(["/x", "/bundled", "/usr/bin"]);
  });
});

describe("buildBackendEnv", () => {
  it("sets the host contract and strips leaked venv/python vars", () => {
    const layout = fakeLayout(true);
    const env = buildBackendEnv({
      layout,
      port: 5690,
      token: "tok",
      parentPid: 4242,
      baseEnv: { PATH: "/usr/bin", VIRTUAL_ENV: "/leak", PYTHONPATH: "/leak2", ELECTRON_RUN_AS_NODE: "1", HOME: "/home/u" },
    });
    expect(env.OPENCOMPANY_DESKTOP).toBe("1");
    expect(env.OPENCOMPANY_PARENT_PID).toBe("4242");
    expect(env.OPENCOMPANY_DESKTOP_TOKEN).toBe("tok");
    expect(env.OPENCOMPANY_DESKTOP_STDIN).toBe("1");
    expect(env.OPENCOMPANY_APP_ROOT).toBe(layout.appRoot);
    expect(env.OPENCOMPANY_CLIENT_DIST).toBe(layout.clientDist);
    expect(env.OPENCOMPANY_ENV_FILE).toBe(layout.userEnvFile);
    expect(env.PORT).toBe("5690");
    expect(env.PYTHON_BACKEND_PORT).toBe("5690");
    expect(env.HOST).toBe("127.0.0.1");
    expect(env.SERVE_STATIC_CLIENT).toBe("1");
    expect(env.UV_PROJECT_ENVIRONMENT).toBe(layout.venvDir);
    expect(env.UV_SYSTEM_CERTS).toBe("1"); // corporate MITM proxies; UV_NATIVE_TLS is deprecated
    expect(env.UV_NATIVE_TLS).toBeUndefined();
    expect(env.LOG_FORMAT).toBe("json");
    expect(env.OPENCOMPANY_UV_BIN).toBe(layout.uvBin);
    expect(env.OPENCOMPANY_NODE_BIN).toBe(layout.nodeBin);
    expect(env.VIRTUAL_ENV).toBeUndefined();
    expect(env.PYTHONPATH).toBeUndefined();
    expect(env.ELECTRON_RUN_AS_NODE).toBeUndefined();
    expect(env.HOME).toBe("/home/u");
  });

  it("prepends bundled node and uv to PATH but never the bare python dir", () => {
    const layout = fakeLayout(true);
    const env = buildBackendEnv({ layout, port: 1, token: "t", parentPid: 1, baseEnv: { PATH: "/usr/bin" } });
    const parts = (env.PATH as string).split(delimiter);
    expect(parts[0]).toBe(layout.nodeBinDir);
    expect(parts[1]).toBe(join(layout.uvBin, ".."));
    expect(parts).toContain(layout.uvToolBinDir);
    expect(parts.some((p) => p.includes(join("runtime", "python")))).toBe(false);
  });

  it("omits binary overrides when the runtimes are not present", () => {
    const layout = fakeLayout(false);
    const env = buildBackendEnv({ layout, port: 1, token: "t", parentPid: 1, baseEnv: { PATH: "/usr/bin" } });
    expect(env.OPENCOMPANY_UV_BIN).toBeUndefined();
    expect(env.OPENCOMPANY_NODE_BIN).toBeUndefined();
    expect((env.PATH as string).split(delimiter)[0]).toBe(layout.uvToolBinDir);
  });

  it("layers desktop.env but refuses to override contract keys", () => {
    const layout = fakeLayout(true);
    writeFileSync(layout.userEnvFile, "LOG_LEVEL=DEBUG\nPORT=1\nOPENCOMPANY_APP_ROOT=/evil\nTEMPORAL_ENABLED=false\n");
    const env = buildBackendEnv({ layout, port: 5690, token: "t", parentPid: 1, baseEnv: { PATH: "" } });
    expect(env.LOG_LEVEL).toBe("DEBUG");
    expect(env.TEMPORAL_ENABLED).toBe("false");
    expect(env.PORT).toBe("5690");
    expect(env.OPENCOMPANY_APP_ROOT).toBe(layout.appRoot);
  });
});
