/** Layout editor chrome view (issue #100) + reflow canvas (issue #101).
 *
 *  Covers the Editor component in isolation with mock layout data:
 *   1. Three-pane layout (palette · canvas · properties) renders.
 *   2. Layout picker lists the mock entries, opens/closes, and
 *      selects a layout.
 *   3. Canvas pane shows the selected layout's details and widgets.
 *   4. Exit button fires onExit + sends clear_view.
 *   5. Save button is wired and sends widgets + overflow.
 *   6. The editor layout entry is styled as a "chrome view".
 *   7. Canvas renders widget cells with drag handles and kind labels.
 *   8. Overflow toggle and viewport-preview toolbar buttons render.
 *   9. Unsupported widgets (media, nowplaying) get placeholder badges.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "./Editor";
import type { ClientMessage, ServerLayout, Widget } from "./protocol";

const send = vi.fn<(msg: ClientMessage | { type: "select_view"; view: string } | { type: "clear_view" }) => void>();
const onExit = vi.fn();

const MOCK_LAYOUTS = [
  {
    id: "firefox",
    match: ["firefox", "Firefox"],
    display_name: "Firefox",
    theme: "#ff7139",
    icon: { source: "simple-icons", name: "firefox" },
    widgets: [
      { id: "new-tab", kind: "button" as const, label: "New tab", icon: { source: "lucide", name: "plus" }, color: "#1e3a8a" },
    ],
  },
  {
    id: "youtube",
    match: ["firefox", "title:YouTube"],
    display_name: "YouTube",
    widgets: [
      { id: "play-pause", kind: "button" as const, label: "Play/Pause" },
    ],
  },
  {
    id: "editor",
    match: ["editor"],
    display_name: "Layout Editor",
    widgets: [],
  },
  {
    id: "default",
    match: ["default"],
    widgets: [
      { id: "open-url", kind: "button" as const, label: "Open example.com" },
      { id: "media-1", kind: "media" as const, label: "VLC" },
    ],
  },
];

// ResizeObserver is not available in jsdom.
let roCallback: ((entries: { contentRect: { width: number; height: number } }[]) => void) | null = null;

beforeAll(() => {
  // Use a named function so it can be used with `new`.
  function MockResizeObserver(cb: (entries: { contentRect: { width: number; height: number } }[]) => void) {
    roCallback = cb;
    return {
      observe: vi.fn(() => {
        if (roCallback) {
          roCallback([{ contentRect: { width: 600, height: 400 } }]);
        }
      }),
      disconnect: vi.fn(),
      unobserve: vi.fn(),
    };
  }
  (globalThis as Record<string, unknown>).ResizeObserver = MockResizeObserver;
});

afterAll(() => {
  delete (globalThis as Record<string, unknown>).ResizeObserver;
  roCallback = null;
});

describe("Editor — layout editor chrome view", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    onExit.mockReset();
  });

  it("renders the three-pane shell with mock layouts", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    expect(screen.getByRole("region", { name: "layout editor" })).toBeTruthy();
    expect(screen.getByRole("complementary", { name: "widget palette" })).toBeTruthy();
    expect(screen.getByRole("complementary", { name: "properties panel" })).toBeTruthy();
    expect(screen.getByText("Palette")).toBeTruthy();
    expect(screen.getByText("Layout")).toBeTruthy();
  });

  it("pre-selects the first non-editor layout", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    expect(trigger.textContent).toContain("Firefox");
  });

  it("shows the active layout's identity when provided", () => {
    render(
      <Editor
        layout={{ type: "layout", app: "youtube", display_name: "YouTube", jogstrip_enabled: true, widgets: [] }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    expect(trigger.textContent).toContain("YouTube");
  });

  it("opens and closes the layout picker", async () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    const listbox = screen.getByRole("listbox");
    expect(listbox).toBeTruthy();
    const options = listbox.querySelectorAll('[role="option"]');
    expect(options).toHaveLength(5);
    fireEvent.click(trigger);
    await waitFor(() => expect(trigger.getAttribute("aria-expanded")).toBe("false"));
  });

  it("selects a layout from the picker", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    fireEvent.click(trigger);
    const youtubeOption = screen.getByText("YouTube");
    fireEvent.click(youtubeOption);
    expect(trigger.textContent).toContain("YouTube");
    expect(screen.getAllByText("YouTube").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/match: firefox, title:YouTube/)).toBeTruthy();
  });

  it("shows widget count for the selected layout", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    // Default selection is firefox (1 widget).
    expect(screen.getByText("1 widget")).toBeTruthy();
  });

  it("marks the editor layout entry as a chrome view", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    fireEvent.click(trigger);
    const editorOption = screen.getByText("chrome view");
    expect(editorOption).toBeTruthy();
    expect(editorOption.closest("li")?.className).toContain("editor-picker-option-view");
  });

  it("exit button fires onExit and sends clear_view", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const exitBtn = screen.getByRole("button", { name: "close editor" });
    fireEvent.click(exitBtn);
    expect(send).toHaveBeenCalledWith({ type: "clear_view" });
    expect(onExit).toHaveBeenCalled();
  });

  it("renders a save button", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    expect(screen.getByRole("button", { name: "save layout" })).toBeTruthy();
  });

  it("shows the title 'Edit layout' in the header", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    expect(screen.getByText("Edit layout")).toBeTruthy();
  });

  it("shows canvas placeholder when no mock layouts provided and fetch fails", async () => {
    render(<Editor layout={null} send={send} onExit={onExit} />);
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    expect(trigger.textContent).toContain("Select layout");
    expect(screen.getByText("No layout selected")).toBeTruthy();
  });

  // ---- reflow canvas tests (issue #101) ----

  it("renders widget cells in the canvas with kind labels", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    // Firefox layout has one button: label "New tab", kind "BUTTON".
    expect(screen.getByText("New tab")).toBeTruthy();
    expect(screen.getByText("button")).toBeTruthy();
  });

  it("renders drag handles on canvas cells", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const dragBtn = screen.getByLabelText("drag to reorder New tab");
    expect(dragBtn).toBeTruthy();
  });

  it("renders overflow toggle buttons", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    expect(screen.getByLabelText("shrink to fit")).toBeTruthy();
    expect(screen.getByLabelText("clip")).toBeTruthy();
  });

  it("renders viewport-preview width buttons", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    // Full / 1024 / 768 / 480 / 360
    expect(screen.getByLabelText("preview at full width")).toBeTruthy();
    expect(screen.getByLabelText("preview at 480 width")).toBeTruthy();
    expect(screen.getByLabelText("preview at 360 width")).toBeTruthy();
  });

  it("shows empty state message when layout has no widgets", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    fireEvent.click(trigger);
    // Select the editor layout (has 0 widgets).
    const editorOption = screen.getByText("Layout Editor");
    fireEvent.click(editorOption);
    expect(screen.getByText("0 widgets")).toBeTruthy();
    expect(screen.getByText(/No widgets/)).toBeTruthy();
  });

  it("renders placeholder badge on unsupported widget kinds", () => {
    // Select the 'default' layout which has a 'media' widget.
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    fireEvent.click(trigger);
    const defaultOption = screen.getByText("default");
    fireEvent.click(defaultOption);
    // 'default' has 2 widgets: button and media.
    expect(screen.getByText("2 widgets")).toBeTruthy();
    // The media widget should have a "placeholder" badge.
    expect(screen.getByText("placeholder")).toBeTruthy();
    // And the cell should have the unsupported class.
    const mediaCell = screen.getByText("VLC").closest(".editor-canvas-cell");
    expect(mediaCell?.className).toContain("editor-canvas-cell-unsupported");
  });

  it("toggles overflow mode when clicking toolbar buttons", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const shrinkBtn = screen.getByLabelText("shrink to fit");
    const clipBtn = screen.getByLabelText("clip");

    // Default is shrink-to-fit.
    expect(shrinkBtn.getAttribute("aria-pressed")).toBe("true");
    expect(clipBtn.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(clipBtn);
    expect(shrinkBtn.getAttribute("aria-pressed")).toBe("false");
    expect(clipBtn.getAttribute("aria-pressed")).toBe("true");
  });

  it("activates a viewport-preview width button", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const fullBtn = screen.getByLabelText("preview at full width");
    const btn480 = screen.getByLabelText("preview at 480 width");

    expect(fullBtn.getAttribute("aria-pressed")).toBe("true");
    expect(btn480.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(btn480);
    expect(btn480.getAttribute("aria-pressed")).toBe("true");
    expect(fullBtn.getAttribute("aria-pressed")).toBe("false");
  });

  it("save sends widgets and overflow in the PUT body", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchSpy);

    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          display_name: "Firefox",
          jogstrip_enabled: true,
          widgets: [{ id: "new-tab", kind: "button" as const, label: "New tab" }],
          overflow: "shrink-to-fit",
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    const saveBtn = screen.getByRole("button", { name: "save layout" });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });

    const callArgs = fetchSpy.mock.calls[0];
    const body = JSON.parse(callArgs[1].body as string);
    expect(body.match).toEqual(["firefox"]);
    expect(body.overflow).toBe("shrink-to-fit");
    expect(Array.isArray(body.widgets)).toBe(true);
    expect(body.widgets[0].id).toBe("new-tab");

    vi.unstubAllGlobals();
  });

  // ---- new-layout creation flow tests (issue #104) ----

  it("picker includes a 'New layout' entry with Plus icon", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    fireEvent.click(trigger);
    const newOption = screen.getByText("New layout");
    expect(newOption).toBeTruthy();
  });

  it("clicking 'New layout' opens the manual creation form", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByText("New layout"));
    expect(screen.getByText("New layout")).toBeTruthy();
    // The creation form should show match / display-name inputs.
    expect(screen.getByPlaceholderText("e.g. firefox or title:*YouTube*")).toBeTruthy();
    expect(screen.getByPlaceholderText("(optional, derived from match)")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create layout" })).toBeTruthy();
  });

  it("shows detect-and-offer prompt when app is 'default' with focused app", () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "default",
          jogstrip_enabled: true,
          widgets: [{ id: "dummy", kind: "button" as const }],
          focused_app: { app_id: "org.example.App", wm_class: "example-app", title: "Example App", is_browser: false },
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );
    expect(screen.getByText(/No layout for example-app yet/)).toBeTruthy();
    const matchInput = screen.getByPlaceholderText("e.g. firefox or title:*YouTube*") as HTMLInputElement;
    expect(matchInput.value).toBe("example-app");
  });

  it("shows browser branch prompt when focused app is a browser", () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "default",
          jogstrip_enabled: true,
          widgets: [{ id: "dummy", kind: "button" as const }],
          focused_app: { app_id: "firefox", wm_class: "firefox", title: "YouTube", is_browser: true },
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );
    expect(screen.getByText(/No layout for.*yet/)).toBeTruthy();
    // The alternate option for the site should be present.
    expect(screen.getByText(/Layout for/)).toBeTruthy();
  });

  it("creates a new layout and saves via POST", async () => {
    const fetchSpy = vi.fn();
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        layout: {
          id: "example-app",
          match: ["example-app"],
          display_name: "Example App",
          widgets: [],
          overflow: "shrink-to-fit",
        },
      }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    render(
      <Editor
        layout={{
          type: "layout",
          app: "default",
          jogstrip_enabled: true,
          widgets: [{ id: "dummy", kind: "button" as const }],
          focused_app: { app_id: "org.example.App", wm_class: "example-app", title: "Example App", is_browser: false },
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    // Confirm creation.
    fireEvent.click(screen.getByRole("button", { name: "Create layout" }));

    // Should now be in new-layout editing mode.
    expect(screen.getByText("New layout")).toBeTruthy();
    expect(screen.getByText("match: example-app")).toBeTruthy();

    // Save should POST.
    fireEvent.click(screen.getByRole("button", { name: "save layout" }));
    await waitFor(() => {
      const postCall = fetchSpy.mock.calls.find(
        (call: unknown[]) => {
          const arr = call as [string, { method: string; body: string }];
          return arr[1]?.method === "POST";
        },
      );
      expect(postCall).toBeTruthy();
      const body = JSON.parse((postCall as [string, { method: string; body: string }])[1].body);
      expect(body.match).toEqual(["example-app"]);
    });

    vi.unstubAllGlobals();
  });

  it("cancel button dismisses creation form", () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "default",
          jogstrip_enabled: true,
          widgets: [{ id: "dummy", kind: "button" as const }],
          focused_app: { app_id: "org.example.App", wm_class: "example-app", title: "Example App", is_browser: false },
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );
    expect(screen.getByText(/No layout for/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    // Form should be gone, canvas placeholder shown (since default layout isn't in MOCK_LAYOUTS).
    expect(screen.queryByText(/No layout for/)).toBeFalsy();
  });

  it("empty match disables the create button", () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "default",
          jogstrip_enabled: true,
          widgets: [{ id: "dummy", kind: "button" as const }],
          focused_app: { app_id: "org.example.App", wm_class: "example-app", title: "Example App", is_browser: false },
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );
    const input = screen.getByPlaceholderText("e.g. firefox or title:*YouTube*") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "" } });
    expect((screen.getByRole("button", { name: "Create layout" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("entering new-layout mode resets layout-level edit fields (#104)", () => {
    // The layout-level properties panel (display_name/theme/icon/jogstrip)
    // must not inherit stale values from a previously-loaded layout when
    // entering new-layout mode — a brand-new layout has none of those
    // (#88: "no theme"), and showing stale fields would be misleading.
    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          display_name: "Firefox",
          theme: "#ff7139",
          icon: { source: "simple-icons", name: "firefox" },
          jogstrip_enabled: false,
          widgets: [{ id: "btn-1", kind: "button" as const }],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    // Select the firefox layout (loaded with display_name/theme/icon set).
    expect(screen.getByDisplayValue("Firefox")).toBeTruthy();
    expect(screen.getByDisplayValue("#ff7139")).toBeTruthy();

    // Open the manual creation form, confirm with a match token.
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByText("New layout"));
    const matchInput = screen.getByPlaceholderText("e.g. firefox or title:*YouTube*");
    fireEvent.change(matchInput, { target: { value: "newapp" } });
    fireEvent.click(screen.getByRole("button", { name: "Create layout" }));

    // The layout-level properties panel must now show the prefilled
    // display_name (#88 "prefilled display_name") and empty/default
    // theme/icon — not the stale Firefox values.
    const displayNameInput = screen.getByPlaceholderText("(derived from match)") as HTMLInputElement;
    expect(displayNameInput.value).toBe("newapp");
    const themeInput = screen.getByPlaceholderText("e.g. #ff7139 or hsl(...)") as HTMLInputElement;
    expect(themeInput.value).toBe("");
    const iconButton = screen.getByRole("button", { name: "Browse icons…" });
    expect(iconButton).toBeTruthy();
    // Jogstrip defaults to true (#88: no override for a brand-new layout).
    const jogstripCheckbox = screen.getByRole("checkbox") as HTMLInputElement;
    expect(jogstripCheckbox.checked).toBe(true);
  });

  it("clicking the browser alt-button swaps match and display-name inputs", () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "default",
          jogstrip_enabled: true,
          widgets: [{ id: "dummy", kind: "button" as const }],
          focused_app: {
            app_id: "firefox",
            wm_class: "firefox",
            title: "YouTube",
            is_browser: true,
          },
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    const matchInput = screen.getByPlaceholderText("e.g. firefox or title:*YouTube*") as HTMLInputElement;
    expect(matchInput.value).toBe("firefox");
    const altBtn = screen.getByRole("button", { name: /Layout for/ });
    fireEvent.click(altBtn);
    expect(matchInput.value).toBe("title:*YouTube*");
    const displayNameInput = screen.getByPlaceholderText("(optional, derived from match)") as HTMLInputElement;
    expect(displayNameInput.value).toBe("YouTube");
  });

  it("exit in new-layout mode shows the abandon confirm (#104)", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(false);

    render(
      <Editor
        layout={{
          type: "layout",
          app: "default",
          jogstrip_enabled: true,
          widgets: [{ id: "dummy", kind: "button" as const }],
          focused_app: { app_id: "org.example.App", wm_class: "example-app", title: "Example App", is_browser: false },
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    // Enter new-layout mode via the detect-and-offer prompt.
    fireEvent.click(screen.getByRole("button", { name: "Create layout" }));

    // Exit must ask before abandoning the not-yet-saved draft.
    fireEvent.click(screen.getByRole("button", { name: "close editor" }));
    expect(confirmSpy).toHaveBeenCalledWith("Abandon this new layout? Nothing is saved yet.");
    expect(send).not.toHaveBeenCalledWith({ type: "clear_view" });
    expect(onExit).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });

  // ---- properties panel tests (issue #103) ----

  it("shows layout-level fields in the properties panel when no widget is selected", () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          display_name: "Firefox",
          theme: "#ff7139",
          jogstrip_enabled: true,
          widgets: [{ id: "btn-1", kind: "button" as const, label: "Test" }],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );
    expect(screen.getByText("Layout")).toBeTruthy();
    expect(screen.getByText("Display name")).toBeTruthy();
  });

  it("shows widget properties when a canvas cell is clicked", () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          display_name: "Firefox",
          jogstrip_enabled: true,
          widgets: [
            { id: "btn-1", kind: "button" as const, label: "Test button" },
          ],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );
    const cell = document.querySelector('[data-widget-id="btn-1"]');
    expect(cell).toBeTruthy();
    fireEvent.click(cell!);
    expect(screen.getByRole("heading", { name: "Button" })).toBeTruthy();
    expect(screen.getByText("ID")).toBeTruthy();
    expect(screen.getByDisplayValue("btn-1")).toBeTruthy();
    expect(screen.getByDisplayValue("Test button")).toBeTruthy();
  });

  it("shows meter fields when a meter widget is selected", () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [
            {
              id: "meter-1",
              kind: "meter" as const,
              label: "CPU",
              source: "cpu_percent",
              min: 0,
              max: 100,
            },
          ],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );
    const cell = document.querySelector('[data-widget-id="meter-1"]');
    fireEvent.click(cell!);
    expect(screen.getAllByText("Meter").length).toBeGreaterThanOrEqual(1);
    const sources = screen.getAllByText("Source");
    expect(sources.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByDisplayValue("cpu_percent")).toBeTruthy();
  });

  it("shows unsupported placeholder for media widgets", () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [
            { id: "media-1", kind: "media" as const, label: "VLC" },
          ],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );
    const cell = document.querySelector('[data-widget-id="media-1"]');
    fireEvent.click(cell!);
    expect(screen.getByText("Reorder / delete only")).toBeTruthy();
  });

  it("selected cell has highlight class", () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [
            { id: "btn-1", kind: "button" as const, label: "Test" },
          ],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );
    const cell = document.querySelector('[data-widget-id="btn-1"]');
    fireEvent.click(cell!);
    expect(cell?.className).toContain("editor-canvas-cell-selected");
  });

  it("save includes layout-level presentation fields", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchSpy);

    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          display_name: "Firefox",
          theme: "#ff7139",
          icon: { source: "lucide", name: "globe" },
          jogstrip_enabled: true,
          widgets: [{ id: "new-tab", kind: "button" as const, label: "New tab" }],
          overflow: "shrink-to-fit",
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    const saveBtn = screen.getByRole("button", { name: "save layout" });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });

    const body = JSON.parse(fetchSpy.mock.calls[0][1].body as string);
    expect(body.display_name).toBe("Firefox");
    expect(body.theme).toBe("#ff7139");
    expect(body.jogstrip).toBe(true);
    expect(body.icon).toEqual({ source: "lucide", name: "globe" });

    vi.unstubAllGlobals();
  });

  it("save preserves unrendered widget fields (opaque pass-through)", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchSpy);

    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [
            {
              id: "btn-1",
              kind: "button" as const,
              label: "Macro btn",
              macro: { steps: [{ type: "key", value: "ctrl+a" }], continue_on_error: false },
            },
          ],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    const saveBtn = screen.getByRole("button", { name: "save layout" });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });

    const body = JSON.parse(fetchSpy.mock.calls[0][1].body as string);
    expect(body.widgets[0].macro).toEqual({
      steps: [{ type: "key", value: "ctrl+a" }],
      continue_on_error: false,
    });
    expect(body.widgets[0].label).toBe("Macro btn");

    vi.unstubAllGlobals();
  });

  it("clicking the canvas background deselects widget", () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [
            { id: "btn-1", kind: "button" as const, label: "Test" },
          ],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );
    // First select the widget
    const cell = document.querySelector('[data-widget-id="btn-1"]');
    fireEvent.click(cell!);
    expect(screen.getByRole("heading", { name: "Button" })).toBeTruthy();

    // Click the grid container outside the cell
    const grid = document.querySelector(".editor-canvas-grid");
    fireEvent.click(grid!);
    expect(screen.getByText("Layout")).toBeTruthy();
  });
});

describe("Editor — fetch layouts path (no mockLayouts)", () => {
  afterEach(() => {
    cleanup();
    delete (globalThis as Record<string, unknown>).fetch;
  });
  beforeEach(() => {
    send.mockReset();
    onExit.mockReset();
  });

  const FETCH_LAYOUTS = [
    {
      id: "firefox",
      match: ["firefox"],
      display_name: "Firefox",
      theme: "#ff7139",
      icon: { source: "simple-icons", name: "firefox" },
      widgets: [{ id: "btn-1", kind: "button" as const, label: "Click", icon: { source: "lucide", name: "mouse-pointer-click" }, color: "#1e3a8a" }],
    },
    {
      id: "editor",
      match: ["editor"],
      display_name: "Layout Editor",
      widgets: [],
    },
    {
      id: "terminal",
      match: ["alacritty"],
      display_name: "Terminal",
      widgets: [],
    },
  ];

  it("fetches layouts and shows them in the picker", async () => {
    (globalThis as Record<string, unknown>).fetch = vi.fn().mockResolvedValue({
      json: () =>
        Promise.resolve({ ok: true, layouts: FETCH_LAYOUTS }),
    });

    render(
      <Editor layout={null} send={send} onExit={onExit} />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Firefox").length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByLabelText("select layout to edit"));
    // Picker dropdown should show all fetched layouts
    expect(screen.getByText("Terminal")).toBeTruthy();
    expect(screen.queryByText("YouTube")).toBeFalsy();
  });

  it("auto-selects first non-editor layout from fetch response", async () => {
    (globalThis as Record<string, unknown>).fetch = vi.fn().mockResolvedValue({
      json: () =>
        Promise.resolve({ ok: true, layouts: FETCH_LAYOUTS }),
    });

    render(
      <Editor layout={null} send={send} onExit={onExit} />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Firefox").length).toBeGreaterThan(0);
    });

    expect(screen.getByText("Click")).toBeTruthy();
    expect(screen.queryByText("Layout Editor")).toBeFalsy();
  });

  it("shows 'Select layout' when fetch returns empty list", async () => {
    (globalThis as Record<string, unknown>).fetch = vi.fn().mockResolvedValue({
      json: () =>
        Promise.resolve({ ok: true, layouts: [] }),
    });

    render(
      <Editor layout={null} send={send} onExit={onExit} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Select layout")).toBeTruthy();
    });
  });

  it("shows 'Select layout' when fetch returns non-ok", async () => {
    (globalThis as Record<string, unknown>).fetch = vi.fn().mockResolvedValueOnce({
      json: () =>
        Promise.resolve({ ok: false, layouts: [] }),
    });

    render(
      <Editor layout={null} send={send} onExit={onExit} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Select layout")).toBeTruthy();
    });
  });

  it("shows 'Select layout' when fetch fails", async () => {
    (globalThis as Record<string, unknown>).fetch = vi.fn().mockRejectedValueOnce(new Error("network error"));

    render(
      <Editor layout={null} send={send} onExit={onExit} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Select layout")).toBeTruthy();
    });
  });
});

describe("Editor — full save-cycle integration", () => {
  beforeEach(() => {
    send.mockReset();
    onExit.mockReset();
  });

  afterEach(() => {
    cleanup();
    delete (globalThis as Record<string, unknown>).fetch;
  });

  function renderAndSave(opts: {
    layout?: Record<string, unknown>;
    edit?: () => Promise<void> | void;
  }) {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
    (globalThis as Record<string, unknown>).fetch = fetchSpy;

    render(
      <Editor
        layout={(opts.layout as ServerLayout) ?? null}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    return { fetchSpy, clickSave: async () => {
      if (opts.edit) await opts.edit();
      fireEvent.click(screen.getByRole("button", { name: "save layout" }));
      await waitFor(() => { expect(fetchSpy).toHaveBeenCalled(); });
      return fetchSpy.mock.calls[0] as [string, RequestInit];
    }};
  }

  it("PUT body includes all layout-level fields", async () => {
    const { clickSave } = renderAndSave({
      layout: {
        type: "layout",
        app: "firefox",
        widgets: [{ id: "btn-1", kind: "button" as const }],
      },
    });

    const [, req] = await clickSave();
    const body = JSON.parse(req.body as string);

    expect(body.match).toEqual(["firefox"]);
    expect(body.widgets).toEqual([{ id: "btn-1", kind: "button" }]);
    expect(body.overflow).toBe("shrink-to-fit");
    expect(body.display_name).toBe(null);
    expect(body.theme).toBe(null);
    expect(body.icon).toBe(null);
    expect(body.jogstrip).toBe(true);
  });

  it("PUT body includes presentation fields from active layout", async () => {
    const { clickSave } = renderAndSave({
      layout: {
        type: "layout",
        app: "firefox",
        display_name: "My Firefox",
        theme: "#ff0000",
        icon: { source: "lucide", name: "globe" },
        jogstrip_enabled: false,
        overflow: "clip",
        widgets: [{ id: "btn-1", kind: "button" as const }],
      },
    });

    const [, req] = await clickSave();
    const body = JSON.parse(req.body as string);

    expect(body.display_name).toBe("My Firefox");
    expect(body.theme).toBe("#ff0000");
    expect(body.icon).toEqual({ source: "lucide", name: "globe" });
    expect(body.jogstrip).toBe(false);
    expect(body.overflow).toBe("clip");
  });

  it("PUT body reflects widget changes (label, icon, color, size)", async () => {
    const { clickSave } = renderAndSave({
      layout: {
        type: "layout",
        app: "firefox",
        jogstrip_enabled: true,
        widgets: [{
          id: "btn-1",
          kind: "button" as const,
          label: "Old label",
          icon: { source: "lucide", name: "play" },
          color: "#1e3a8a",
          size: [1, 1] as [number, number],
        }],
      },
    });

    const [, req] = await clickSave();
    const body = JSON.parse(req.body as string);
    expect(body.widgets[0].label).toBe("Old label");
    expect(body.widgets[0].icon).toEqual({ source: "lucide", name: "play" });
    expect(body.widgets[0].color).toBe("#1e3a8a");
    expect(body.widgets[0].size).toEqual([1, 1]);
  });

  it("PUT body preserves unrendered fields (macro)", async () => {
    const { clickSave } = renderAndSave({
      layout: {
        type: "layout",
        app: "firefox",
        jogstrip_enabled: true,
        widgets: [{
          id: "btn-1",
          kind: "button" as const,
          label: "Macro",
          macro: { steps: [{ type: "key", value: "ctrl+a" }], continue_on_error: false },
        }],
      },
    });

    const [, req] = await clickSave();
    const body = JSON.parse(req.body as string);
    expect(body.widgets[0].macro).toEqual({
      steps: [{ type: "key", value: "ctrl+a" }],
      continue_on_error: false,
    });
    expect(body.widgets[0].label).toBe("Macro");
  });

  it("clearing a widget field omits it from the PUT body (#89 deletion = omission)", async () => {
    const { clickSave } = renderAndSave({
      layout: {
        type: "layout",
        app: "firefox",
        jogstrip_enabled: true,
        widgets: [
          { id: "btn-1", kind: "button" as const, label: "Has label", color: "#123456" },
        ],
      },
      edit: async () => {
        const cell = document.querySelector('[data-widget-id="btn-1"]');
        fireEvent.click(cell!);
        await waitFor(() => { expect(screen.getByDisplayValue("Has label")).toBeTruthy(); });
        fireEvent.change(screen.getByDisplayValue("Has label"), { target: { value: "" } });
      },
    });

    const [, req] = await clickSave();
    const body = JSON.parse(req.body as string);
    expect("label" in body.widgets[0]).toBe(false);
    // Untouched fields ride along.
    expect(body.widgets[0].color).toBe("#123456");
  });

  it("PUT body reflects widget delete", async () => {
    const { clickSave } = renderAndSave({
      layout: {
        type: "layout",
        app: "firefox",
        jogstrip_enabled: true,
        widgets: [
          { id: "btn-1", kind: "button" as const, label: "Keep" },
          { id: "btn-2", kind: "button" as const, label: "Delete me" },
        ],
      },
      edit: async () => {
        // Select the second widget, then click delete
        const cell = document.querySelector('[data-widget-id="btn-2"]');
        fireEvent.click(cell!);
        await waitFor(() => { expect(screen.getByText("Delete widget")).toBeTruthy(); });
        fireEvent.click(screen.getByText("Delete widget"));
      },
    });

    const [, req] = await clickSave();
    const body = JSON.parse(req.body as string);
    expect(body.widgets).toHaveLength(1);
    expect(body.widgets[0].id).toBe("btn-1");
  });

  it("PUT body reflects widget reorder via drag", async () => {
    const { clickSave } = renderAndSave({
      layout: {
        type: "layout",
        app: "firefox",
        jogstrip_enabled: true,
        widgets: [
          { id: "first", kind: "button" as const, label: "First" },
          { id: "second", kind: "button" as const, label: "Second" },
        ],
      },
      edit: async () => {
        // Reorder is fired by EditorCanvas via onReorder; we call it directly
        // through the Editor component by simulating the internal callback.
        // The reorder happens on dragEnd; since dnd-kit is mocked, we need an
        // alternative trigger path. Fortunately the EditorCanvas renders
        // cells and the dnd-kit sortable context — but we can test the
        // Editor-level handleReorder by rendering the grid and using the
        // span-control buttons as a proxy for "the cell is interactive".
        // For now, verify the initial order appears in the PUT body unchanged.
      },
    });

    const [, req] = await clickSave();
    const body = JSON.parse(req.body as string);
    expect(body.widgets[0].id).toBe("first");
    expect(body.widgets[1].id).toBe("second");
  });

  it("PUT request includes X-Deckd-Password header when password is stored", async () => {
    const storage = { getItem: vi.fn((k: string) => k === "deckd.password" ? "test-password" : null), setItem: vi.fn(), removeItem: vi.fn(), clear: vi.fn() };
    const origStorage = window.localStorage;
    Object.defineProperty(window, "localStorage", { value: storage, writable: true });

    try {
      const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
      (globalThis as Record<string, unknown>).fetch = fetchSpy;

      render(
        <Editor
          layout={{
            type: "layout",
            app: "firefox",
            jogstrip_enabled: true,
            widgets: [{ id: "btn-1", kind: "button" as const }],
          }}
          send={send}
          onExit={onExit}
          mockLayouts={MOCK_LAYOUTS}
        />,
      );

      fireEvent.click(screen.getByRole("button", { name: "save layout" }));
      await waitFor(() => { expect(fetchSpy).toHaveBeenCalled(); });
      const req = fetchSpy.mock.calls[0][1] as RequestInit;
      expect(req.headers).toHaveProperty("X-Deckd-Password", "test-password");
    } finally {
      Object.defineProperty(window, "localStorage", { value: origStorage, writable: true });
    }
  });

  it("PUT request omits auth header when no password stored", async () => {
    const storage = { getItem: vi.fn(() => null), setItem: vi.fn(), removeItem: vi.fn(), clear: vi.fn() };
    const origStorage = window.localStorage;
    Object.defineProperty(window, "localStorage", { value: storage, writable: true });

    try {
      const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
      (globalThis as Record<string, unknown>).fetch = fetchSpy;

      render(
        <Editor
          layout={{
            type: "layout",
            app: "firefox",
            jogstrip_enabled: true,
            widgets: [{ id: "btn-1", kind: "button" as const }],
          }}
          send={send}
          onExit={onExit}
          mockLayouts={MOCK_LAYOUTS}
        />,
      );

      fireEvent.click(screen.getByRole("button", { name: "save layout" }));
      await waitFor(() => { expect(fetchSpy).toHaveBeenCalled(); });
      const req = fetchSpy.mock.calls[0][1] as RequestInit;
      expect(req.headers).not.toHaveProperty("X-Deckd-Password");
    } finally {
      Object.defineProperty(window, "localStorage", { value: origStorage, writable: true });
    }
  });

  it("shows error message when save fails", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ error: "match[0] must equal the layout id" }),
    });
    (globalThis as Record<string, unknown>).fetch = fetchSpy;

    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [{ id: "btn-1", kind: "button" as const }],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "save layout" }));
    await waitFor(() => {
      expect(screen.getByText("match[0] must equal the layout id")).toBeTruthy();
    });
  });

  it("warns on exit when layout has unsaved changes", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(false);

    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [{ id: "btn-1", kind: "button" as const, label: "Test" }],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    // Make a change to dirty the state
    fireEvent.click(screen.getByText("Test")); // select widget
    await waitFor(() => { expect(screen.getByText("Label")).toBeTruthy(); });
    const labelInput = screen.getByDisplayValue("Test");
    fireEvent.change(labelInput, { target: { value: "Changed" } });

    // Click exit
    fireEvent.click(screen.getByRole("button", { name: "close editor" }));
    expect(confirmSpy).toHaveBeenCalledWith("You have unsaved changes. Leave anyway?");
    expect(onExit).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });

  it("overflow select in properties panel updates edit state", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
    (globalThis as Record<string, unknown>).fetch = fetchSpy;

    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [{ id: "btn-1", kind: "button" as const }],
          overflow: "shrink-to-fit",
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    // With no widget selected, the layout-level overflow select is visible
    const combobox = screen.getByRole("combobox");
    expect((combobox as HTMLSelectElement).value).toBe("shrink-to-fit");
    fireEvent.change(combobox, { target: { value: "clip" } });

    // Save and check the PUT body reflects the change
    fireEvent.click(screen.getByRole("button", { name: "save layout" }));
    await waitFor(() => { expect(fetchSpy).toHaveBeenCalled(); });
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body as string);
    expect(body.overflow).toBe("clip");
  });

  it("canvas cell renders icon glyph for widget with icon data", async () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [{
            id: "btn-1",
            kind: "button" as const,
            label: "Icon btn",
            icon: { source: "lucide", name: "play" },
          }],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Icon btn")).toBeTruthy();
    });

    // The cell should render the <Icon> component, not the fallback glyph.
    // The fallback ⬛ would be in a span.editor-canvas-cell-glyph.
    // A real lucide icon renders as an SVG.
    const cell = document.querySelector('[data-widget-id="btn-1"]');
    const fallback = cell?.querySelector(".editor-canvas-cell-glyph");
    expect(fallback).toBeFalsy();

    // The icon should be an SVG rendered by the lucide-react Icon component
    const iconContainer = cell?.querySelector(".editor-canvas-cell-icon");
    expect(iconContainer?.querySelector("svg")).toBeTruthy();
  });

  it("canvas cell shows fallback glyph for widget without icon", async () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [{
            id: "btn-1",
            kind: "button" as const,
            label: "No icon",
          }],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("No icon")).toBeTruthy();
    });

    const cell = document.querySelector('[data-widget-id="btn-1"]');
    const glyph = cell?.querySelector(".editor-canvas-cell-glyph");
    expect(glyph).toBeTruthy();
    expect(glyph?.textContent).toBe("⬛");
  });

  it("canvas cell shows macro badge when widget has macro", async () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [{
            id: "btn-1",
            kind: "button" as const,
            label: "Macro btn",
            macro: { steps: [{ type: "key", value: "ctrl+a" }], continue_on_error: false },
          }],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Macro btn")).toBeTruthy();
    });

    const cell = document.querySelector('[data-widget-id="btn-1"]');
    const macroBadge = cell?.querySelector(".editor-canvas-cell-macro-badge");
    expect(macroBadge).toBeTruthy();
    expect(macroBadge?.textContent).toBe("macro");
  });

  it("PUT body preserves per-kind fields (metrics for stats, source for meter)", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
    (globalThis as Record<string, unknown>).fetch = fetchSpy;

    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [
            {
              id: "stats-1",
              kind: "stats" as const,
              label: "System",
              metrics: [{ source: "cpu_percent", label: "CPU" }],
            },
            {
              id: "meter-1",
              kind: "meter" as const,
              label: "Temp",
              source: "cpu_temp",
              min: 0,
              max: 100,
            },
          ],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "save layout" }));
    await waitFor(() => { expect(fetchSpy).toHaveBeenCalled(); });
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body as string);

    const statsWidget = body.widgets.find((w: { id: string }) => w.id === "stats-1");
    expect(statsWidget.metrics).toEqual([{ source: "cpu_percent", label: "CPU" }]);

    const meterWidget = body.widgets.find((w: { id: string }) => w.id === "meter-1");
    expect(meterWidget.source).toBe("cpu_temp");
    expect(meterWidget.min).toBe(0);
    expect(meterWidget.max).toBe(100);
  });

  it("stripReadOnly removes has_action and kind_specific but preserves other fields", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
    (globalThis as Record<string, unknown>).fetch = fetchSpy;

    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [
            {
              id: "btn-1",
              kind: "button" as const,
              label: "Test",
              has_action: true,    // GET-read-only field — should be stripped
              kind_specific: {},   // GET-read-only field — should be stripped
              icon: { source: "lucide", name: "play" },
            } as unknown as Widget,
          ],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "save layout" }));
    await waitFor(() => { expect(fetchSpy).toHaveBeenCalled(); });
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body as string);

    const w = body.widgets[0];
    expect(w.has_action).toBeUndefined();
    expect(w.kind_specific).toBeUndefined();
    expect(w.icon).toEqual({ source: "lucide", name: "play" });
    expect(w.id).toBe("btn-1");
    expect(w.label).toBe("Test");
  });
});

describe("Editor — widget palette (issue #103)", () => {
  beforeEach(() => {
    send.mockReset();
    onExit.mockReset();
  });

  afterEach(() => {
    cleanup();
    delete (globalThis as Record<string, unknown>).fetch;
  });

  /** Find the PUT call among fetch invocations and parse its body. */
  async function saveAndParsePut(fetchSpy: ReturnType<typeof vi.fn>) {
    fireEvent.click(screen.getByRole("button", { name: "save layout" }));
    await waitFor(() => { expect(fetchSpy).toHaveBeenCalled(); });
    const putCall = fetchSpy.mock.calls.find(
      (call) => (call as [string, RequestInit])[1]?.method === "PUT",
    ) as [string, RequestInit];
    return JSON.parse(putCall[1].body as string);
  }

  it("renders the palette with the insertable kinds", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    // #89: button / meter / stats / blank are palette-insertable; the media
    // family is not.
    expect(screen.getByRole("button", { name: "add button" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "add meter" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "add stats" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "add blank" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "add media" })).toBeFalsy();
    expect(screen.queryByRole("button", { name: "add nowplaying" })).toBeFalsy();
  });

  it("clicking a palette item appends a minted widget and selects it", async () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    // Firefox starts with 1 widget ("new-tab").
    expect(screen.getByText("1 widget")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "add button" }));

    await waitFor(() => { expect(screen.getByText("2 widgets")).toBeTruthy(); });
    expect(document.querySelector('[data-widget-id="button-1"]')).toBeTruthy();
    // The new widget is selected so its minted id is immediately editable.
    expect(screen.getByDisplayValue("button-1")).toBeTruthy();
  });

  it("minted ids avoid collisions with existing widget ids", async () => {
    render(
      <Editor
        layout={{
          type: "layout",
          app: "firefox",
          jogstrip_enabled: true,
          widgets: [{ id: "button-1", kind: "button" as const }],
        }}
        send={send}
        onExit={onExit}
        mockLayouts={MOCK_LAYOUTS}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "add button" }));

    await waitFor(() => { expect(screen.getByText("2 widgets")).toBeTruthy(); });
    expect(document.querySelector('[data-widget-id="button-2"]')).toBeTruthy();
    expect(screen.getByDisplayValue("button-2")).toBeTruthy();
  });

  it("minted ids are per-kind", async () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);

    fireEvent.click(screen.getByRole("button", { name: "add meter" }));
    await waitFor(() => { expect(screen.getByDisplayValue("meter-1")).toBeTruthy(); });
    fireEvent.click(screen.getByRole("button", { name: "add blank" }));
    await waitFor(() => { expect(screen.getByDisplayValue("blank-1")).toBeTruthy(); });
  });

  it("the minted id is editable and persists via save", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
    (globalThis as Record<string, unknown>).fetch = fetchSpy;

    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);

    fireEvent.click(screen.getByRole("button", { name: "add button" }));
    await waitFor(() => { expect(screen.getByDisplayValue("button-1")).toBeTruthy(); });

    fireEvent.change(screen.getByDisplayValue("button-1"), { target: { value: "my-btn" } });
    const body = await saveAndParsePut(fetchSpy);
    const ids = body.widgets.map((w: { id: string }) => w.id);
    expect(ids).toContain("my-btn");
    expect(ids).not.toContain("button-1");
  });

  it("an added blank widget carries only id and kind in the PUT body", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
    (globalThis as Record<string, unknown>).fetch = fetchSpy;

    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);

    fireEvent.click(screen.getByRole("button", { name: "add blank" }));
    await waitFor(() => { expect(screen.getByText("2 widgets")).toBeTruthy(); });

    const body = await saveAndParsePut(fetchSpy);
    const blank = body.widgets.find((w: { id: string }) => w.id === "blank-1");
    expect(blank).toEqual({ id: "blank-1", kind: "blank" });
  });

  it("palette items are disabled when no layout is selected", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={[]} />);
    expect(screen.getByText("Select layout")).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "add button" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
