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
    await expect.poll(async () => {
      const res = await request.get("/layouts");
      const body = await res.json();
      const layout = body.layouts.find(
        (l: { id: string }) => l.id === "default",
      );
      return layout?.widgets.find(
        (w: { id: string }) => w.id === "code",
      )?.label;
    }).toBe("E2E test");

    // Restore: the original `code` widget has no label, so clear it
    // (deletion = omission per #89) rather than fill "code".
    await page.locator('[data-widget-id="code"]').click();
    const labelInput = page.locator("text=Label").locator("..").locator("input");
    await labelInput.fill("");
    await page.getByRole("button", { name: "save layout" }).click();
    await expect(page.getByText("Saved")).toBeVisible({ timeout: 10000 });
  });

  test("palette insert mints an id, saves, and deletes cleanly", async ({
    page,
    request,
  }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });
    await enterEditor(page);
    await page.locator(".editor-canvas-grid").waitFor();

    // Palette click appends a minted widget and selects it.
    await page.getByRole("button", { name: "add button" }).click();
    await page.locator('[data-widget-id="button-1"]').waitFor();
    await expect(page.locator(".prop-field-input").first()).toHaveValue("button-1");

    // Give it a label, then save.
    await page.locator("text=Label").locator("..").locator("input").fill("E2E added");
    await page.getByRole("button", { name: "save layout" }).click();
    await expect(page.getByText("Saved")).toBeVisible({ timeout: 10000 });

    // The daemon's YAML reconcile appended the new widget.
    await expect.poll(async () => {
      const res = await request.get("/layouts");
      const body = await res.json();
      const layout = body.layouts.find((l: { id: string }) => l.id === "default");
      return layout?.widgets.find((w: { id: string }) => w.id === "button-1")?.label;
    }).toBe("E2E added");

    // Clean up: delete the widget and save again.
    await page.locator('[data-widget-id="button-1"]').click();
    await page.getByText("Delete widget").click();
    await page.getByRole("button", { name: "save layout" }).click();
    await expect(page.getByText("Saved")).toBeVisible({ timeout: 10000 });

    await expect.poll(async () => {
      const res = await request.get("/layouts");
      const body = await res.json();
      const layout = body.layouts.find((l: { id: string }) => l.id === "default");
      return layout?.widgets.some((w: { id: string }) => w.id === "button-1");
    }).toBe(false);
  });
});
