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
    baseURL: "http://localhost:8975",
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
    // Copy the repo layouts into a throwaway tmp dir so an e2e save cycle
    // never mutates the human-owned YAML. Port 8975 (not the daemon default
    // 8765) so e2e can run alongside a live dev/user daemon.
    command:
      // mpris.yaml is copied in so the daemon's now-playing pump gate
      // (``_has_nowplaying``) is satisfied; DECKD_FAKE_MPRIS injects a
      // seeded FakeMprisBackend (one playing player) so now-playing.spec
      // can assert the surface + chrome dot without a session bus or a
      // real MPRIS player on the runner (see daemon/deckd/__main__.py).
      'cd .. && rm -rf /tmp/deckd-e2e-layouts && mkdir /tmp/deckd-e2e-layouts && cp layouts/default.yaml layouts/editor.yaml layouts/mpris.yaml /tmp/deckd-e2e-layouts/ && rm -f client/e2e/.daemon.log && PYTHONUNBUFFERED=1 PYTHONPATH=scripts/no-evdev DECKD_FAKE_MPRIS=client/e2e/fixtures/mpris-seed.json .venv/bin/deckd --layouts-dir /tmp/deckd-e2e-layouts --client-dist client/dist --no-auth --port 8975 --verbose > client/e2e/.daemon.log 2>&1',
    cwd: __dirname,
    port: 8975,
    reuseExistingServer: false,
    timeout: 30000,
  },
});