import { execSync } from "node:child_process";
import { existsSync } from "node:fs";

export function findChromiumExe() {
  const override = process.env.CHROMIUM_PATH;
  if (override && existsSync(override)) return override;
  const pattern = "/nix/store/*-playwright-chromium/*/chrome";
  const out = execSync(`ls -d ${pattern} 2>/dev/null | head -1`, {
    encoding: "utf8",
  }).trim();
  if (out && existsSync(out)) return out;
  // No nix store (macOS / a plain npm checkout): return undefined so
  // Playwright falls back to its own managed browser — `npx playwright
  // install chromium` puts one in ~/Library/Caches/ms-playwright. Set
  // CHROMIUM_PATH to force a specific binary.
  return undefined;
}