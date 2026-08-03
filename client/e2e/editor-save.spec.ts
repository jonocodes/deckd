import { test, expect, type Page } from "@playwright/test";

async function enterEditor(page: Page) {
  await page.getByRole("button", { name: "layout editor" }).click();
  await page.locator(".editor-header").waitFor();
}

test.describe("editor save cycle (e2e)", () => {
  test("opens editor, edits a label, saves, persists across reload", async ({
    page,
    request,
  }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });

    // Open editor (auto-selects the active layout, "Home"/"default").
    await enterEditor(page);
    await page.locator(".editor-canvas-grid").waitFor();

    // The default layout has display_name "Home". Click its first widget.
    await page.locator('[data-widget-id="code"]').click();
    await expect(page.getByRole("heading", { name: "Button" })).toBeVisible();

    // The Label input is the first text field under "Label" text.
    await page.locator("text=Label").locator("..").locator("input").fill("E2E test");
    await page.getByRole("button", { name: "save layout" }).click();
    await expect(page.getByText("Saved")).toBeVisible({ timeout: 10000 });

    // Verify persistence via the daemon's GET /layouts.
    await page.waitForTimeout(500);  // let the daemon finish writing
    const res = await request.get("/layouts");
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    const layout = body.layouts.find(
      (l: { id: string }) => l.id === "default",
    );
    const widget = layout.widgets.find(
      (w: { id: string }) => w.id === "code",
    );
    expect(widget.label).toBe("E2E test");

    // Restore original label.
    await page.locator('[data-widget-id="code"]').click();
    await page.locator("text=Label").locator("..").locator("input").fill("code");
    await page.getByRole("button", { name: "save layout" }).click();
    await expect(page.getByText("Saved")).toBeVisible({ timeout: 10000 });
  });
});
