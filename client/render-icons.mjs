import { chromium } from "playwright-core";
import { mkdirSync, readFileSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { findChromiumExe } from "./e2e/find-chromium.mjs";

/**
 * Rasterise the deckd brand SVGs into every PNG the app needs (issue #165).
 *
 * The SVG in ``client/public/icon.svg`` is the source of truth. Browsers are
 * happy to consume it directly for the favicon and the ``any`` manifest icon,
 * but the maskable PWA icon, the iOS apple-touch-icon, and the macOS ``.icns``
 * all need real pixels. Rather than pull in an SVG rasteriser, we drive the
 * Playwright Chromium that the e2e suite already installs.
 *
 * Outputs (all git-tracked):
 *   client/public/icon-192.png, icon-512.png            (any)
 *   client/public/icon-maskable-192.png, -512.png       (maskable)
 *   client/public/apple-touch-icon.png                  (maskable, 180, opaque)
 *   packaging/macos/deckd-menubar.png, @2x.png          (menu-bar template)
 *   build/deckd.iconset/*.png                           (for iconutil → .icns)
 *
 * Run via ``just icons``.
 */
const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(__dirname, "..");
const PUBLIC = resolve(__dirname, "public");
// iconutil insists the directory name ends in ``.iconset``.
const ICONSET = resolve(REPO, "build", "deckd.iconset");
const MACOS = resolve(REPO, "packaging", "macos");

const ANY_SVG = resolve(PUBLIC, "icon.svg");
const MASKABLE_SVG = resolve(PUBLIC, "icon-maskable.svg");
// Menu-bar template: monochrome, 18pt canvas, bundled into deckd.app.
const MENUBAR_SVG = resolve(REPO, "assets", "deckd-mark-mono.svg");

// Apple masks the home-screen icon itself and dislikes transparency, so the
// opaque, full-bleed maskable art is the right source here too.
const ANY_TARGETS = [
  [ANY_SVG, "icon-192.png", 192],
  [ANY_SVG, "icon-512.png", 512],
  [MASKABLE_SVG, "icon-maskable-192.png", 192],
  [MASKABLE_SVG, "icon-maskable-512.png", 512],
  [MASKABLE_SVG, "apple-touch-icon.png", 180],
];

// Menu-bar status-item template. AppKit resolves the @2x sibling when the
// 1x file is loaded, so the point size (18) and pixel sizes (18/36) line up.
const MENUBAR_TARGETS = [
  ["deckd-menubar.png", 18],
  ["deckd-menubar@2x.png", 36],
];

// Standard macOS .iconset layout: name → pixel size (the @2x entries repeat
// the size of the next rung, which is why e.g. 32 appears twice).
const ICNS_TARGETS = [
  ["icon_16x16.png", 16],
  ["icon_16x16@2x.png", 32],
  ["icon_32x32.png", 32],
  ["icon_32x32@2x.png", 64],
  ["icon_128x128.png", 128],
  ["icon_128x128@2x.png", 256],
  ["icon_256x256.png", 256],
  ["icon_256x256@2x.png", 512],
  ["icon_512x512.png", 512],
  ["icon_512x512@2x.png", 1024],
];

function htmlFor(svgText) {
  // Fill the viewport exactly; no body margin, no scrollbars.
  return `<!doctype html><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:transparent}
svg{display:block;width:100vw;height:100vh}</style>${svgText}`;
}

async function main() {
  rmSync(ICONSET, { recursive: true, force: true });
  mkdirSync(ICONSET, { recursive: true });

  const chromePath = findChromiumExe();
  const browser = await chromium.launch({ executablePath: chromePath, headless: true });

  try {
    for (const [svgPath, name, size] of ANY_TARGETS) {
      await render(browser, svgPath, resolve(PUBLIC, name), size, name);
    }
    for (const [name, size] of ICNS_TARGETS) {
      await render(browser, ANY_SVG, resolve(ICONSET, name), size, `deckd.iconset/${name}`);
    }
    for (const [name, size] of MENUBAR_TARGETS) {
      await render(browser, MENUBAR_SVG, resolve(MACOS, name), size, `menubar/${name}`);
    }
  } finally {
    await browser.close();
  }

  console.log(`Done — ${PUBLIC}, ${MACOS}, and ${ICONSET}`);
}

async function render(browser, svgPath, outPath, size, label) {
  const page = await browser.newPage({
    viewport: { width: size, height: size },
    deviceScaleFactor: 1,
  });
  await page.setContent(htmlFor(readFileSync(svgPath, "utf8")));
  await page.screenshot({ path: outPath, omitBackground: true });
  await page.close();
  console.log(`  ${label}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
