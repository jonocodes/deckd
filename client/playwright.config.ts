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
    // DECKD_BIN: ./.venv is the plain-uv layout; a flox checkout has no
    // ./.venv and gets `deckd` from the activated env on PATH.
    //
    // --no-focus: without it the e2e daemon watches the *developer's* real
    // desktop focus (macOS always has a working backend), so the editor
    // opens on whatever app happens to be frontmost — "No layout for
    // firefox yet" instead of the default layout the specs assert on.
    // DECKD_FAKE_INPUT: log injections instead of performing them; the
    // PYTHONPATH=scripts/no-evdev shadow only covers the Linux sink.
    // mpris.yaml is copied in so the daemon's now-playing pump gate
    // (``_has_nowplaying``) is satisfied; DECKD_FAKE_MPRIS injects a
    // seeded FakeMprisBackend (one playing player) so now-playing.spec
    // can assert the surface + chrome dot without a session bus or a
    // real MPRIS player on the runner (see daemon/deckd/__main__.py).
    command:
      'cd .. && DECKD_BIN=.venv/bin/deckd && [ -x "$DECKD_BIN" ] || DECKD_BIN=deckd; rm -rf /tmp/deckd-e2e-layouts && mkdir /tmp/deckd-e2e-layouts && cp layouts/default.yaml layouts/editor.yaml layouts/mpris.yaml /tmp/deckd-e2e-layouts/ && rm -f client/e2e/.daemon.log && PYTHONUNBUFFERED=1 PYTHONPATH=scripts/no-evdev DECKD_FAKE_INPUT=1 DECKD_FAKE_MPRIS=client/e2e/fixtures/mpris-seed.json "$DECKD_BIN" --layouts-dir /tmp/deckd-e2e-layouts --client-dist client/dist --no-auth --no-focus --port 8975 --verbose > client/e2e/.daemon.log 2>&1',
    cwd: __dirname,
    port: 8975,
    reuseExistingServer: false,
    timeout: 30000,
  },
});