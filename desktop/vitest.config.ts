import { resolve } from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@main": resolve(__dirname, "src/main") },
  },
  test: {
    include: ["tests/unit/**/*.test.ts", "tests/invariants/**/*.test.ts"],
    environment: "node",
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
});
