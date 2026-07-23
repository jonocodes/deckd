import { test, expect, type Page } from "@playwright/test";
import { unlinkSync } from "node:fs";

import { daemonLogPath, keyLogEntries, readDaemonLog, waitForKeyLog } from "./daemon-log.js";

const KEY_A = 30;
const KEY_B = 48;
const KEY_H = 35;
const KEY_BACKSPACE = 14;
const KEY_ENTER = 28;
const KEY_TAB = 15;
const KEY_ESC = 1;
const KEY_UP = 103;
const KEY_LEFT = 105;

async function enterManualControl(page: Page) {
  await page.locator("button", { hasText: "manual control" }).click();
  await page.locator(".manual-control").waitFor();
}

async function toggleIme(page: Page) {
  await page.locator(".kbd-strip-ime").click();
}

async function raiseIme(page: Page) {
  await enterManualControl(page);
  await toggleIme(page);
  await expect(page.locator(".kbd-input")).toBeFocused();
}

test.describe("manual control (issue #23 merge) — full pipeline against a logging-sink daemon", () => {
  test("manual control chrome button is visible on every client (no touch gate)", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await expect(page.locator("button", { hasText: "manual control" })).toHaveCount(1);
  });

  test("entering manual control shows the strip (6 key buttons + IME toggle) and trackpad", async ({
    page,
  }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await enterManualControl(page);
    await expect(page.locator(".trackpad")).toHaveCount(1);
    await expect(page.locator(".kbd-input")).toHaveCount(1);
    await expect(page.locator(".kbd-strip-btn")).toHaveCount(7);
    // IME is opt-in: the input does NOT auto-focus.
    await expect(page.locator(".kbd-input")).not.toBeFocused();
  });

  test("the IME toggle button raises the soft keyboard and a second tap closes it", async ({
    page,
  }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await enterManualControl(page);
    await toggleIme(page);
    await expect(page.locator(".kbd-input")).toBeFocused();
    await expect(page.locator(".kbd-strip-ime")).toHaveAttribute("aria-pressed", "true");
    await toggleIme(page);
    await expect(page.locator(".kbd-input")).not.toBeFocused();
    await expect(page.locator(".kbd-strip-ime")).toHaveAttribute("aria-pressed", "false");
  });

  test("iOS-style keydown → type message → daemon logs the literal keycode", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    const baseline = readDaemonLog().length;
    await raiseIme(page);
    await page.locator(".kbd-input").evaluate((el) =>
      el.dispatchEvent(
        new KeyboardEvent("keydown", { key: "a", bubbles: true, cancelable: true }),
      ),
    );
    await waitForKeyLog([KEY_A], baseline);
    expect(keyLogEntries(baseline)).toEqual([[KEY_A]]);
  });

  test("Android-style input event → sendDelta diff → daemon logs the inserted keycodes", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    const baseline = readDaemonLog().length;
    await raiseIme(page);
    await page.locator(".kbd-input").evaluate((el) => {
      el.value = "h";
      el.dispatchEvent(
        new InputEvent("input", { bubbles: true, inputType: "insertText", data: "h" }),
      );
    });
    await waitForKeyLog([KEY_H], baseline);
    expect(keyLogEntries(baseline)).toEqual([[KEY_H]]);
  });

  test("beforeinput deleteContentBackward on empty field → daemon logs backspace", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    const baseline = readDaemonLog().length;
    await raiseIme(page);
    await page.locator(".kbd-input").evaluate((el) =>
      el.dispatchEvent(
        new InputEvent("beforeinput", {
          bubbles: true,
          cancelable: true,
          inputType: "deleteContentBackward",
        }),
      ),
    );
    await waitForKeyLog([KEY_BACKSPACE], baseline);
    expect(keyLogEntries(baseline)).toEqual([[KEY_BACKSPACE]]);
  });

  test("beforeinput insertParagraph → daemon logs enter", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    const baseline = readDaemonLog().length;
    await raiseIme(page);
    await page.locator(".kbd-input").evaluate((el) =>
      el.dispatchEvent(
        new InputEvent("beforeinput", {
          bubbles: true,
          cancelable: true,
          inputType: "insertParagraph",
        }),
      ),
    );
    await waitForKeyLog([KEY_ENTER], baseline);
    expect(keyLogEntries(baseline)).toEqual([[KEY_ENTER]]);
  });

  test("caps and shifted symbols ride Shift + base key (US layout)", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    const baseline = readDaemonLog().length;
    await raiseIme(page);
    const input = page.locator(".kbd-input");
    for (const [set, expected] of [
      ["a", [KEY_A]],
      ["B", [42, KEY_B]],
      ["!", [42, 2]],
    ] as const) {
      await input.evaluate(
        (el, v) => {
          el.value = v;
          el.dispatchEvent(
            new InputEvent("input", { bubbles: true, inputType: "insertText", data: v }),
          );
        },
        set,
      );
      await waitForKeyLog(expected, baseline);
    }
    expect(keyLogEntries(baseline)).toEqual([[KEY_A], [42, KEY_B], [42, 2]]);
  });

  test("strip key button click → named combo (esc, tab, up, left) — IME not needed for keys", async ({
    page,
  }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    const baseline = readDaemonLog().length;
    await enterManualControl(page);
    const strip = page.locator(".kbd-strip-btn:not(.kbd-strip-ime)");
    for (const [label, expected] of [
      ["esc", [KEY_ESC]],
      ["tab", [KEY_TAB]],
      ["↑", [KEY_UP]],
      ["←", [KEY_LEFT]],
    ] as const) {
      await strip.filter({ hasText: label }).click();
      await waitForKeyLog(expected, baseline);
    }
    expect(keyLogEntries(baseline)).toEqual([
      [KEY_ESC],
      [KEY_TAB],
      [KEY_UP],
      [KEY_LEFT],
    ]);
  });

  test("input resets to empty after a non-composition insert (ephemeral field)", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    const baseline = readDaemonLog().length;
    await raiseIme(page);
    await page.locator(".kbd-input").evaluate((el) => {
      el.value = "abc";
      el.dispatchEvent(
        new InputEvent("input", { bubbles: true, inputType: "insertText", data: "abc" }),
      );
    });
    await waitForKeyLog([KEY_B], baseline);
    await page.waitForFunction(() => {
      const el = document.querySelector(".kbd-input") as HTMLInputElement | null;
      return !!el && el.value === "";
    });
    expect(await page.locator(".kbd-input").inputValue()).toBe("");
  });

  test("trackpad surface is interactive in the merged view (drag fires no errors)", async ({
    page,
  }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await enterManualControl(page);
    const trackpad = page.locator(".trackpad");
    const box = await trackpad.boundingBox();
    if (!box) throw new Error("no trackpad bounding box");
    // A single-finger drag across the trackpad. We don't have a fake key
    // sink for pad events; this only asserts the merged view's surface
    // exists and accepts pointer input without throwing.
    await page.mouse.move(box.x + 50, box.y + 50);
    await page.mouse.down();
    await page.mouse.move(box.x + 200, box.y + 50, { steps: 10 });
    await page.mouse.up();
    // The IME button should still be reachable after the drag — the
    // trackpad didn't steal focus from the input.
    await toggleIme(page);
    await expect(page.locator(".kbd-input")).toBeFocused();
  });

  test("desktop browser also shows the manual control button (the daemon-side guard prevents self-injection)", async ({
    browser,
  }) => {
    const ctx = await browser.newContext({ viewport: { width: 420, height: 800 } });
    const page = await ctx.newPage();
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await expect(page.locator("button", { hasText: "manual control" })).toHaveCount(1);
    await ctx.close();
  });

  });

test.afterAll(() => {
  try {
    unlinkSync(daemonLogPath);
  } catch {
    /* ignore */
  }
});