/** Layout editor chrome view (issue #100).
 *
 * Covers the Editor component in isolation with mock layout data:
 *  1. Three-pane layout (palette · canvas · properties) renders.
 *  2. Layout picker lists the mock entries, opens/closes, and
 *     selects a layout.
 *  3. Canvas pane shows the selected layout's details.
 *  4. Exit button fires onExit + sends clear_view.
 *  5. Save button is wired.
 *  6. The editor layout entry is styled as a "chrome view".
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "./Editor";
import type { ClientMessage } from "./protocol";

const send = vi.fn<(msg: ClientMessage | { type: "select_view"; view: string } | { type: "clear_view" }) => void>();
const onExit = vi.fn();

const MOCK_LAYOUTS = [
  {
    id: "firefox",
    match: ["firefox", "Firefox"],
    display_name: "Firefox",
    widgets: [
      { id: "new-tab", kind: "button" as const, label: "New tab" },
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
    ],
  },
];

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
    expect(screen.getByText("Properties")).toBeTruthy();
  });

  it("pre-selects the first non-editor layout", () => {
    render(<Editor layout={null} send={send} onExit={onExit} mockLayouts={MOCK_LAYOUTS} />);
    // The picker trigger should show "Firefox" (first non-editor entry).
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
    // All 4 mock entries should appear.
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(4);
    // Click again — closes the picker.
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
    // Canvas should show the selected layout's details — "YouTube" also
    // appears in the picker trigger, so use getAllByText.
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
    // The editor option's parent <li> should have the view class.
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
    // No mockLayouts + no daemon → fetch fails, renders with empty picker.
    render(<Editor layout={null} send={send} onExit={onExit} />);
    // The picker should show a fallback label.
    const trigger = screen.getByRole("button", { name: "select layout to edit" });
    expect(trigger.textContent).toContain("Select layout");
    // Canvas shows "No layout selected".
    expect(screen.getByText("No layout selected")).toBeTruthy();
  });
});
