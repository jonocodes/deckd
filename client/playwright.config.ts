import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

import { findChromiumExe } from "./e2e/find-chromium.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  timeout: 30000,
  use: {
    baseURL: "http://localhost:8765",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: { executablePath: findChromiumExe() },
      },
    },
  ],
  webServer: {
    command:
      'cd .. && rm -f client/e2e/.daemon.log && PYTHONUNBUFFERED=1 PYTHONPATH=scripts/no-evdev .venv/bin/deckd --layouts-dir layouts --client-dist client/dist --verbose > client/e2e/.daemon.log 2>&1',
    cwd: __dirname,
    port: 8765,
    reuseExistingServer: false,
    timeout: 30000,
  },
});