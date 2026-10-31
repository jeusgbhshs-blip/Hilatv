import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/canvas-mock.test.ts"],
    reporters: ["verbose"],
  },
});
