import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/home-entries.test.ts", "lib/canvas-mock.test.ts", "lib/canvas-adapt.test.ts", "lib/canvas-client.test.ts", "lib/project-draft.test.ts"],
    reporters: ["verbose"],
  },
});
