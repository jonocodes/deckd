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
  throw new Error(
    `Chromium binary not found at ${pattern}. Set CHROMIUM_PATH to a chromium executable, or run \`nix-env -iA nixpkgs.playwright-chromium\`.`,
  );
}