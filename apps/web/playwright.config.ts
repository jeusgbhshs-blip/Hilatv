import path from "node:path";

import { defineConfig } from "@playwright/test";

const here = __dirname;
const root = path.resolve(here, "../..");
const python = process.env.PYTHON ?? "python3";
const apiOrigin = process.env.HILATV_API_ORIGIN ?? "http://127.0.0.1:8000";
const webOrigin = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3000";
const apiPort = new URL(apiOrigin).port || "8000";
const webPort = new URL(webOrigin).port || "3000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 420_000,
  expect: { timeout: 180_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: webOrigin,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port ${apiPort}`,
      cwd: root,
      url: `${apiOrigin}/health`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: `npm run start -- --hostname 127.0.0.1 --port ${webPort}`,
      cwd: here,
      url: webOrigin,
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
  projects: [
    {
      name: "desktop",
      use: { browserName: "chromium", viewport: { width: 1440, height: 900 } },
    },
    {
      name: "mobile",
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
        userAgent:
          "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
      },
    },
  ],
});
