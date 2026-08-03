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
 *   9. Unsupported widgets (media, mediabrowser) get placeholder badges.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "./Editor";
import type { ClientMessage } from "./protocol";

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
    expect(screen.getByText("Button")).toBeTruthy();
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
    expect(screen.getByText("Button")).toBeTruthy();

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
