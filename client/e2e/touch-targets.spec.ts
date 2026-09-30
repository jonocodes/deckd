import { test, expect, type Locator } from "@playwright/test";

/** Browser-level touch-target coverage (issue #61).
 *
 * The ticket's acceptance criteria are geometric, so the strongest
 * check is a real layout engine measuring boxes at a phone-sized
 * viewport — not the CSS-text guard in ``touch-targets.test.ts``.
 * Chromium (the e2e browser) uses the same Blink layout as Chrome on
 * Android, so a 44x44 measurement here is the behaviour a phone gets.
 *
 * The fixture daemon serves a default deck plus a seeded fake MPRIS
 * player (see ``playwright.config.ts``), so every surface under test
 * renders without a real desktop.
 */

const MIN = 44;
/** Allow sub-pixel rounding without letting a genuinely-under control through. */
const EPS = 0.5;

type Box = { x: number; y: number; width: number; height: number };

async function boxes(locator: Locator): Promise<Box[]> {
  const count = await locator.count();
  const out: Box[] = [];
  for (let i = 0; i < count; i++) {
    const box = await locator.nth(i).boundingBox();
    expect(box, `no bounding box for element ${i}`).not.toBeNull();
    out.push(box as Box);
  }
  return out;
}

function expectMinTarget(box: Box, label: string) {
  expect(box.width, `${label} width`).toBeGreaterThanOrEqual(MIN - EPS);
  expect(box.height, `${label} height`).toBeGreaterThanOrEqual(MIN - EPS);
}

/** No two controls may overlap — the "tap never lands on a neighbour"
 *  criterion, checked across every pair regardless of row wrapping. */
function expectNoOverlap(boxesToCheck: Box[], label: string) {
  for (let i = 0; i < boxesToCheck.length; i++) {
    for (let j = i + 1; j < boxesToCheck.length; j++) {
      const a = boxesToCheck[i];
      const b = boxesToCheck[j];
      const separated =
        a.x + a.width <= b.x + EPS ||
        b.x + b.width <= a.x + EPS ||
        a.y + a.height <= b.y + EPS ||
        b.y + b.height <= a.y + EPS;
      expect(separated, `${label}: controls ${i} and ${j} overlap`).toBe(true);
    }
  }
}

test.describe("touch targets (issue #61) at 375x667", () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test("every bottom-chrome button is at least 44x44", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    const buttons = page.locator(".chrome-bottom .chrome-btn");
    const measured = await boxes(buttons);
    expect(measured.length).toBeGreaterThanOrEqual(4);
    measured.forEach((box, i) => expectMinTarget(box, `chrome button ${i}`));
    expectNoOverlap(measured, "chrome buttons");
  });

  test("adjacent bottom-chrome buttons keep at least 8px between them", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    const measured = await boxes(page.locator(".chrome-bottom .chrome-btn"));
    for (let i = 1; i < measured.length; i++) {
      const prev = measured[i - 1];
      const gap = measured[i].x - (prev.x + prev.width);
      expect(gap, `gap between chrome buttons ${i - 1} and ${i}`).toBeGreaterThanOrEqual(8 - EPS);
    }
  });

  test("manual-control keys are 44x44 and laid out 4+4 with the arrows on top", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "manual control" }).click();
    await page.locator(".manual-control").waitFor();
    // The jogstrip stays available for scrolling in this view.
    await expect(page.locator(".chrome-jogstrip")).toHaveCount(1);
    const measured = await boxes(page.locator(".kbd-strip-btn"));
    expect(measured).toHaveLength(8);
    measured.forEach((box, i) => expectMinTarget(box, `key button ${i}`));
    // DOM order is arrows first: 0-3 on the top row, 4-7 on the bottom.
    measured.slice(0, 4).forEach((box, i) =>
      expect(Math.abs(box.y - measured[0].y), `top-row key ${i}`).toBeLessThan(1),
    );
    measured.slice(4).forEach((box, i) =>
      expect(Math.abs(box.y - measured[4].y), `bottom-row key ${i}`).toBeLessThan(1),
    );
    expect(measured[4].y).toBeGreaterThan(measured[0].y + 1);
    expectNoOverlap(measured, "manual-control keys");
  });

  test("settings sliders and toggles expose a 44px tap area", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "settings" }).click();
    await expect(page.getByRole("region", { name: "Settings" })).toBeVisible();

    const sliders = await boxes(page.locator(".settings .slider"));
    expect(sliders.length).toBeGreaterThanOrEqual(5);
    sliders.forEach((box, i) => {
      expect(box.height, `settings slider ${i} height`).toBeGreaterThanOrEqual(MIN - EPS);
      expect(box.width, `settings slider ${i} width`).toBeGreaterThanOrEqual(MIN - EPS);
    });

    const toggles = await boxes(page.locator(".settings .toggle"));
    expect(toggles.length).toBeGreaterThan(0);
    toggles.forEach((box, i) => expectMinTarget(box, `settings toggle ${i}`));
  });

  test("media-browser transport buttons are at least 44x44", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "now playing" }).click();
    const transport = page.locator(".nowplaying-transport button");
    await expect(transport.first()).toBeVisible();
    const measured = await boxes(transport);
    expect(measured).toHaveLength(3);
    measured.forEach((box, i) => expectMinTarget(box, `transport button ${i}`));
    expectNoOverlap(measured, "now-playing transport");
  });
});
