import { defineConfig } from "@playwright/test";

const webOrigin = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3100";
const webPort = new URL(webOrigin).port || "3100";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "canvas-demo.spec.ts",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: webOrigin,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `npm run dev -- --hostname 127.0.0.1 --port ${webPort}`,
    cwd: __dirname,
    url: webOrigin,
    timeout: 120_000,
    reuseExistingServer: true,
  },
  projects: [
    {
      name: "desktop",
      use: { browserName: "chromium", viewport: { width: 1440, height: 900 } },
    },
  ],
});
