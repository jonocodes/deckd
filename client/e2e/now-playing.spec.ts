import { test, expect } from "@playwright/test";

// Hermetic now-playing e2e (issue #47 / #50–#54). The daemon is booted
// by playwright.config.ts with DECKD_FAKE_MPRIS pointing at
// e2e/fixtures/mpris-seed.json — a single VLC row, playing, with title
// + artist. No session bus, no real MPRIS player: the seeded
// FakeMprisBackend replays its state to every fresh session via the
// daemon's connect-time snapshot pushes (push_chrome_media_snapshot /
// push_media_snapshot). This is the browser-level coverage the media
// path lacked; live-bus pickup is a separate, out-of-CI smoke test.

const SEED_TITLE = "Parity Test Track";
const SEED_ARTIST = "The Drift Guards";

test.describe("now playing (seeded fake MPRIS)", () => {
  test("chrome media indicator lights 'playing' from the connect snapshot", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    // The media chrome button gains ``chrome-btn-playing`` when the
    // daemon's chrome_media snapshot reports a playing player. The dot
    // must light from the snapshot alone — no user interaction, no live
    // transition — which is exactly the "player already playing when I
    // connect" case that had no coverage before.
    const mediaBtn = page.getByRole("button", { name: "now playing" });
    await expect(mediaBtn).toHaveClass(/chrome-btn-playing/);
  });

  test("opening the now-playing view shows the seeded player and playing transport", async ({ page }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });

    await page.getByRole("button", { name: "now playing" }).click();

    const region = page.getByRole("region", { name: "now playing" });
    await expect(region).toBeVisible();

    // The seeded row's metadata renders in the cell.
    await expect(region.locator(".nowplaying-title")).toHaveText(SEED_TITLE);
    await expect(region.locator(".nowplaying-subtitle")).toHaveText(SEED_ARTIST);
    await expect(region.locator(".nowplaying-app")).toHaveText("VLC media player");

    // A playing row shows a Pause control (the button's accessible name
    // flips to "Pause" while playing); prev/next are enabled because the
    // seed sets can_go_previous / can_go_next.
    await expect(region.getByRole("button", { name: "Pause" })).toBeVisible();
    await expect(region.getByRole("button", { name: "Previous" })).toBeEnabled();
    await expect(region.getByRole("button", { name: "Next" })).toBeEnabled();
  });
});
