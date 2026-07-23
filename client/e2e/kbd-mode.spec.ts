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

async function enterKbdMode(page: Page) {
  await page.locator("button", { hasText: "keyboard" }).click();
  await page.locator(".kbd-input").waitFor();
}

test.describe("kbd mode (issue #23) — full pipeline against a logging-sink daemon", () => {
  test("kbd chrome button is visible on every client (no touch gate)", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await expect(page.locator("button", { hasText: "keyboard" })).toHaveCount(1);
  });

  test("entering kbd mode focuses the hidden input and shows six strip buttons", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await enterKbdMode(page);
    await expect(page.locator(".kbd-input")).toBeFocused();
    await expect(page.locator(".kbd-strip-btn")).toHaveCount(6);
  });

  test("iOS-style keydown → type message → daemon logs the literal keycode", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    const baseline = readDaemonLog().length;
    await enterKbdMode(page);
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
    await enterKbdMode(page);
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
    await enterKbdMode(page);
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
    await enterKbdMode(page);
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
    await enterKbdMode(page);
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

  test("strip button click → named combo (esc, tab, up, left)", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    const baseline = readDaemonLog().length;
    await enterKbdMode(page);
    const strip = page.locator(".kbd-strip-btn");
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
    await enterKbdMode(page);
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

  test("desktop browser also shows the kbd button (the daemon-side guard prevents self-injection)", async ({
    browser,
  }) => {
    const ctx = await browser.newContext({ viewport: { width: 420, height: 800 } });
    const page = await ctx.newPage();
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await expect(page.locator("button", { hasText: "keyboard" })).toHaveCount(1);
    await ctx.close();
  });

  test("kbmode shows a same-machine warning when the client origin is localhost", async ({
    page,
  }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await enterKbdMode(page);
    await expect(page.getByRole("status")).toContainText(/Same machine/i);
    await expect(page.locator(".kbd-hint")).toHaveCount(0);
  });
});

test.afterAll(() => {
  try {
    unlinkSync(daemonLogPath);
  } catch {
    /* ignore */
  }
});