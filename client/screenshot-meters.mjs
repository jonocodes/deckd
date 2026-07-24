import { chromium } from "playwright-core";

const chromePath = "/nix/store/6qv40p5vmxqg9yr55qm2hibrxny7i553-playwright-chromium/chrome-linux64/chrome";
const browser = await chromium.launch({ executablePath: chromePath, headless: true });
const ctx = await browser.newContext({
  viewport: { width: 480, height: 320 },
  deviceScaleFactor: 2,
});
const page = await ctx.newPage();
page.on("pageerror", (err) => console.log("[pageerror]", err.message));
// Meter demo so we don't have to deal with the no-auth + WS issue
await page.goto("http://127.0.0.1:8766/index.html?demo=meter", { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
await page.screenshot({ path: "/tmp/deckd-meters-demo.png", fullPage: false });
console.log("saved meter demo");
await browser.close();
