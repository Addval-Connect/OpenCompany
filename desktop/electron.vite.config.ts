import { resolve } from "node:path";

import { defineConfig, externalizeDepsPlugin } from "electron-vite";

// Three build contexts. The renderer here is ONLY the first-run setup /
// error page; the real UI is the backend-served SPA loaded from
// http://127.0.0.1:<port> at runtime, so nothing from client/ is built here.
export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    resolve: {
      alias: { "@main": resolve(__dirname, "src/main") },
    },
    build: {
      rollupOptions: {
        input: { index: resolve(__dirname, "src/main/index.ts") },
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: { index: resolve(__dirname, "src/preload/index.ts") },
      },
    },
  },
  renderer: {
    root: resolve(__dirname, "src/renderer"),
    build: {
      rollupOptions: {
        input: { setup: resolve(__dirname, "src/renderer/setup/index.html") },
      },
    },
  },
});
