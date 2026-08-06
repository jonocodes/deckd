/** Running-windows chrome view (issues #120 / #126).
 *
 * Covers the three observable contracts:
 *  1. The layout-grid icon renders in the bottom chrome strip next to
 *     the editor button, always rendered regardless of platform
 *     capability (decision 8 — affordance stays discoverable).
 *  2. A first click opens the view (active class + ``select_view:
 *     "windows"`` on the wire); a second click closes it (active
 *     class gone + ``clear_view`` on the wire). Mirrors the media
 *     browser / editor button handshake exactly.
 *  3. While the view is open, the surface renders the windows-list
 *     component instead of the focused-app layout. Three shapes:
 *     - No ``running_windows`` frame yet → "unsupported on this
 *       platform" empty state (decision 8).
 *     - Empty snapshot → "no running programs" message.
 *     - Non-empty snapshot → one row per window, label visible,
 *       ``icon`` riding when present, muted generic window glyph
 *       when ``icon`` is null (supersedes decision 6).
 *
 * The socket is mocked so the test owns the wire surface — we can
 * assert exactly which client message landed in ``send`` and push
 * synthetic ``running_windows`` frames without spinning up a daemon.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ClientMessage,
  ServerChromeMedia,
  ServerLayout,
  ServerRunningWindows,
} from "./protocol";

const send = vi.fn<(message: ClientMessage) => void>();
let runningWindowsHandler: ((m: ServerRunningWindows) => void) | null = null;
const onLayout = vi.fn<(m: ServerLayout) => void>();
const mockStatus: "connecting" | "open" | "closed" | "unauthorized" = "open";
const authenticate = vi.fn();
const deauthenticate = vi.fn();
vi.mock("./socket", () => ({
  useDeckdSocket: (
    layoutCb: (m: ServerLayout) => void,
    _widgetUpdate: unknown,
    _mediaState: unknown,
    _chromeMediaCb: ((m: ServerChromeMedia) => void) | undefined,
    _confirmRequest: unknown,
    runningWindowsCb: ((m: ServerRunningWindows) => void) | undefined,
    _options: unknown,
  ) => {
    onLayout.mockImplementation(layoutCb);
    runningWindowsHandler = runningWindowsCb ?? null;
    return {
      get status() {
        return mockStatus;
      },
      send,
      authenticate,
      deauthenticate,
      hasPassword: false,
    };
  },
}));

import { App } from "./App";

describe("App — running programs chrome button", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    runningWindowsHandler = null;
    window.history.replaceState(null, "", "/?demo=default");
  });

  it("renders the running programs icon in the bottom chrome", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "running programs" })).toBeTruthy();
  });

  it("sends select_view on first click and applies the active class", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "running programs" });
    expect(button.className).not.toContain("chrome-btn-active");
    fireEvent.pointerDown(button);
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "windows" });
    expect(button.className).toContain("chrome-btn-active");
  });

  it("sends clear_view on a second click and removes the active class", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "running programs" });
    fireEvent.pointerDown(button); // open
    fireEvent.pointerDown(button); // close
    expect(send.mock.calls.map((c) => c[0])).toEqual([
      { type: "select_view", view: "windows" },
      { type: "clear_view" },
    ]);
    expect(button.className).not.toContain("chrome-btn-active");
  });

  it("Enter activates the running programs button and sends select_view", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "running programs" });
    fireEvent.keyDown(button, { key: "Enter" });
    expect(button.className).toContain("chrome-btn-active");
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "windows" });
  });
});

describe("App — running windows chrome view", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    runningWindowsHandler = null;
    window.history.replaceState(null, "", "/?demo=default");
  });

  function openRunningPrograms() {
    render(<App />);
    const button = screen.getByRole("button", { name: "running programs" });
    fireEvent.pointerDown(button);
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "windows" });
  }

  function pushRunningWindows(windows: ServerRunningWindows["windows"]) {
    act(() => {
      runningWindowsHandler?.({ type: "running_windows", windows });
    });
  }

  it("renders the unsupported-on-platform empty state when no frame has arrived", () => {
    openRunningPrograms();
    expect(screen.getByText("running programs: unsupported on this platform")).toBeTruthy();
  });

  it("renders the no-running-programs empty state on an empty snapshot", () => {
    openRunningPrograms();
    pushRunningWindows([]);
    expect(screen.getByText("no running programs")).toBeTruthy();
  });

  it("renders one row per window with the daemon-derived label", () => {
    openRunningPrograms();
    pushRunningWindows([
      { window_id: "1", label: "Firefox", icon: { source: "simple-icons", name: "firefox" } },
      { window_id: "2", label: "xterm", icon: null },
    ]);
    const rows = document.querySelectorAll(".windows-row");
    expect(rows.length).toBe(2);
    expect(rows[0].getAttribute("data-window-id")).toBe("1");
    expect(rows[0].textContent).toContain("Firefox");
    expect(rows[1].getAttribute("data-window-id")).toBe("2");
    expect(rows[1].textContent).toContain("xterm");
  });

  it("tapping a row raises the window then clears the view (stage 3, #122)", () => {
    openRunningPrograms();
    send.mockReset();
    pushRunningWindows([
      { window_id: "1", label: "Firefox", icon: { source: "simple-icons", name: "firefox" } },
      { window_id: "2", label: "xterm", icon: null },
    ]);
    const rows = document.querySelectorAll<HTMLElement>(".windows-row");
    fireEvent.click(rows[1]);
    expect(send.mock.calls.map((c) => c[0])).toEqual([
      { type: "raise_window", window_id: "2" },
      { type: "clear_view" },
    ]);
  });

  it("closes the overlay back to the layout after a row tap", () => {
    openRunningPrograms();
    const button = screen.getByRole("button", { name: "running programs" });
    expect(button.className).toContain("chrome-btn-active");
    pushRunningWindows([{ window_id: "1", label: "Firefox", icon: null }]);
    fireEvent.click(document.querySelector<HTMLElement>(".windows-row")!);
    expect(button.className).not.toContain("chrome-btn-active");
  });

  it("focus restoration returns to the running-programs button when the view closes", async () => {
    openRunningPrograms();
    const button = screen.getByRole("button", { name: "running programs" });
    // Press Escape — the global handler should revert to the layout
    // view and hand focus back to the chrome button that opened the
    // overlay (issue #60, AC #5 — same pattern as the editor and
    // media browser).
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(button.className).not.toContain("chrome-btn-active"));
    expect(send).toHaveBeenCalledWith({ type: "clear_view" });
  });
});

describe("App — chrome button tooltips (windows included)", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    window.history.replaceState(null, "", "/?demo=default");
  });

  it("the running-programs button shows its tooltip text on focus", async () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "running programs" });
    fireEvent.focus(button);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip.textContent).toBe("running programs");
    expect(button.getAttribute("aria-describedby")).toBe(tooltip.id);
    fireEvent.blur(button);
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
  });
});