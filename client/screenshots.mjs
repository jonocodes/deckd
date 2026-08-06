import { chromium } from "playwright-core";
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { findChromiumExe } from "./e2e/find-chromium.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));

const PORT = 5199;
const BASE = `http://127.0.0.1:${PORT}`;
const SHOTS_DIR = resolve(__dirname, "..", "docs", "screenshots");

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function main() {
  mkdirSync(SHOTS_DIR, { recursive: true });

  console.log("Starting Vite dev server...");
  const vite = spawn("npx", ["vite", "dev", "--port", String(PORT), "--strictPort", "--host", "127.0.0.1"], {
    cwd: __dirname,
    stdio: "pipe",
  });

  // Give Vite a few seconds to start up
  await sleep(3000);
  console.log("Vite ready.");

  try {
    const chromePath = findChromiumExe();
    console.log(`Chromium: ${chromePath}`);

    const browser = await chromium.launch({ executablePath: chromePath, headless: true });
    const ctx = await browser.newContext({
      viewport: { width: 1200, height: 800 },
      deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    page.on("pageerror", (err) => console.log("[pageerror]", err.message));

    await page.goto(`${BASE}/screenshots.html`, { waitUntil: "networkidle", timeout: 30_000 });

    // Wait for all iframes to render (opacity transitions to 1)
    await page.waitForFunction(() => {
      const frames = document.querySelectorAll(".shot iframe");
      if (frames.length === 0) return false;
      return [...frames].every((f) => f.style.opacity === "1");
    }, { timeout: 30_000 });

    // Extra settle time for icons/fonts
    await page.waitForTimeout(1000);

    const shots = await page.$$(".shot");
    for (const shot of shots) {
      const label = await shot.getAttribute("data-shot");
      if (!label) continue;
      const path = resolve(SHOTS_DIR, `${label}.png`);
      await shot.screenshot({ path });
      console.log(`  ${label}.png`);
    }

    await browser.close();
  } finally {
    vite.kill("SIGTERM");
    await sleep(500);
  }

  console.log(`Done — ${SHOTS_DIR}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
