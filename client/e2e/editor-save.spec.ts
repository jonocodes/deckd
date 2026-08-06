import { test, expect, type Page } from "@playwright/test";

async function enterEditor(page: Page) {
  await page.getByRole("button", { name: "layout editor" }).click();
  await page.locator(".editor-header").waitFor();
}

interface LayoutEntry {
  id: string;
  widgets: { id: string; label?: string }[];
}

interface LayoutListResponse {
  ok: boolean;
  layouts: LayoutEntry[];
}

test.describe("editor save cycle (e2e)", () => {
  test("opens editor, edits a label, saves, persists across reload", async ({
    page,
    request,
  }) => {
    await page.goto("/index.html", { waitUntil: "networkidle" });

    // Open editor. The e2e daemon only has default.yaml + editor.yaml so
    // the active layout is always "default" regardless of host focus.
    await enterEditor(page);
    await page.locator(".editor-canvas-grid").waitFor();

    // Click the first widget.
    const cell = page.locator(".editor-canvas-cell").first();
    await cell.waitFor();
    const widgetId = (await cell.getAttribute("data-widget-id")) ?? "";
    await cell.click();
    await expect(page.getByRole("heading", { name: "Button" })).toBeVisible();

    // The Label input is the first text field under "Label" text.
    await page.locator("text=Label").locator("..").locator("input").fill("E2E test");
    await page.getByRole("button", { name: "save layout" }).click();
    await expect(page.getByText("Saved")).toBeVisible({ timeout: 10000 });

    // Verify persistence via the daemon's GET /layouts.
    await expect.poll(async () => {
      const res = await request.get("/layouts");
      const body: LayoutListResponse = await res.json();
      const layout = body.layouts.find((l) => l.id === "default");
      return layout?.widgets.find((w) => w.id === widgetId)?.label;
    }).toBe("E2E test");

    // Restore: clear the label (deletion = omission per #89).
    await page.locator(`[data-widget-id="${widgetId}"]`).click();
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

    // Verify via the daemon's GET /layouts that the widget was appended.
    await expect.poll(async () => {
      const res = await request.get("/layouts");
      const body: LayoutListResponse = await res.json();
      const layout = body.layouts.find((l) => l.id === "default");
      return layout?.widgets.find((w) => w.id === "button-1")?.label;
    }).toBe("E2E added");

    // Clean up: delete the widget and save again.
    await page.locator('[data-widget-id="button-1"]').click();
    await page.getByText("Delete widget").click();
    await page.getByRole("button", { name: "save layout" }).click();
    await expect(page.getByText("Saved")).toBeVisible({ timeout: 10000 });

    await expect.poll(async () => {
      const res = await request.get("/layouts");
      const body: LayoutListResponse = await res.json();
      const layout = body.layouts.find((l) => l.id === "default");
      return layout?.widgets.some((w) => w.id === "button-1");
    }).toBe(false);
  });
});
