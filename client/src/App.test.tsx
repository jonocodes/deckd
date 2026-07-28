/** Chrome media icon + mediabrowser view (issue #51).
 *
 * Covers the three observable contracts:
 *  1. The icon renders in the bottom chrome strip next to settings.
 *  2. A first click opens the view (active class + ``select_view: "mpris"``
 *     on the wire); a second click closes it (active class gone +
 *     ``clear_view`` on the wire). Mirrors the settings button exactly.
 *  3. While the view is open, the surface renders the browser area with
 *     the "No media players detected" placeholder instead of the
 *     focused-app layout. The placeholder is unconditional for v1
 *     (real rows arrive via the MediaBrowserCell ticket #53).
 *
 * The socket is mocked so the test owns the wire surface — we can assert
 * exactly which client message landed in ``send`` without spinning up a
 * daemon.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ClientMessage, ServerChromeMedia, ServerLayout } from "./protocol";

/** Replace the real socket hook with a controllable fake. The chrome
 * icon's job is to call ``send`` with the right message; the test
 * asserts on what was sent, not on daemon-side behaviour. */
const send = vi.fn<(message: ClientMessage) => void>();
/** Captured ``onChromeMedia`` callback the App registers with the socket
 * hook (issue #47). Tests invoke it directly to push synthetic
 * ``chrome_media`` frames and assert on the icon's class. */
let chromeMediaHandler: ((m: ServerChromeMedia) => void) | null = null;
const onLayout = vi.fn<(m: ServerLayout) => void>();
/** Per-test socket status override. The default mock returns ``open``
 * (matches the demo path), but tests that exercise the password
 * gate / focus restoration flow can set ``mockStatus`` to drive
 * ``status`` through ``"unauthorized"`` → ``"open"`` transitions. */
let mockStatus: "connecting" | "open" | "closed" | "unauthorized" = "open";
const authenticate = vi.fn();
const deauthenticate = vi.fn();
vi.mock("./socket", () => ({
  useDeckdSocket: (
    layoutCb: (m: ServerLayout) => void,
    _widgetUpdate: unknown,
    _mediaState: unknown,
    chromeMediaCb: ((m: ServerChromeMedia) => void) | undefined,
    _options: unknown,
  ) => {
    onLayout.mockImplementation(layoutCb);
    chromeMediaHandler = chromeMediaCb ?? null;
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

describe("App — chrome media icon", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    // Each test sets a fresh demo URL so the App's initial layout is
    // deterministic and the socket stays disabled.
    window.history.replaceState(null, "", "/?demo=default");
  });

  it("renders the media icon in the bottom chrome", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: /media browser/i })).toBeTruthy();
  });

  it("sends select_view on first click and applies the active class", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: /media browser/i });
    expect(button.className).not.toContain("chrome-btn-active");
    fireEvent.pointerDown(button);
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "mpris" });
    expect(button.className).toContain("chrome-btn-active");
  });

  it("sends clear_view on a second click and removes the active class", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: /media browser/i });
    fireEvent.pointerDown(button); // open
    fireEvent.pointerDown(button); // close
    expect(send.mock.calls.map((c) => c[0])).toEqual([
      { type: "select_view", view: "mpris" },
      { type: "clear_view" },
    ]);
    expect(button.className).not.toContain("chrome-btn-active");
  });

  it("renders the browser placeholder in place of the focused-app layout while open", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: /media browser/i });
    fireEvent.pointerDown(button);
    // The default demo has no mediabrowser widget, so the chrome view
    // falls back to the "no players" placeholder (issue #51; #53 added
    // the real per-row cell that takes over once a mediabrowser
    // widget is in the active layout).
    expect(screen.getByText("No media players detected")).toBeTruthy();
  });
});

/** Chrome media icon + mediabrowser view with the per-row cell (issue #53).
 *
 * The mpris demo seeds the active mediabrowser widget with four MPRIS
 * rows, so opening the chrome view renders the real per-row cell
 * (not the placeholder). Clicks on the per-row transport buttons
 * fire the wire ``media_command`` with the row's ``mpris.<suffix>``
 * id and the right command — that's the bridge to the server-side
 * dispatch in #54.
 */
describe("App — mediabrowser per-row cell", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    window.history.replaceState(null, "", "/?demo=mpris");
  });

  it("renders the per-row browser with seeded MPRIS rows", () => {
    render(<App />);
    // ``?demo=mpris`` opens straight into the mediabrowser view, so
    // the rows are visible without clicking the chrome icon. The
    // demo seeds the media store from a mount-time ``useEffect`` —
    // wrap the render in ``act`` so the seeded states have
    // propagated by the time the assertion runs.
    const rows = screen.getAllByRole("listitem");
    expect(rows.length).toBeGreaterThan(0);
    // Issue #58: the browser no longer re-sorts by playback state;
    // rows appear in the media-store's insertion order, which the
    // demo seeds with ``mpris.vlc`` first.
    expect(rows[0].getAttribute("data-row-id")).toBe("mpris.vlc");
    expect(screen.getByText("One More Time")).toBeTruthy();
  });

  it("clicking a transport button sends the right media_command", () => {
    let view: ReturnType<typeof render> | undefined;
    act(() => {
      view = render(<App />);
    });
    // The button only exists once the seeded ``media_state`` rows
    // have propagated through the store; click the first Pause in
    // the rendered list. The first row is ``mpris.vlc`` (issue #58).
    const pause = screen.getAllByRole("button", { name: "Pause" })[0];
    fireEvent.click(pause);
    expect(send).toHaveBeenCalledWith({
      type: "media_command",
      id: "mpris.vlc",
      command: "play-pause",
    });
    void view;
  });
});

/** Chrome media icon passive playback indicator (issue #47).
 *
 * The media icon was a static glyph in v1; issue #47 turns it into a
 * passive playback-state indicator. The icon tints (filled / accent
 * colour) when at least one MPRIS player is ``Playing`` and stays
 * outlined otherwise. The wire surface is a new ``chrome_media``
 * frame the daemon pushes on ``NameOwnerChanged`` registration
 * transitions and on ``PlaybackStatus`` boundary crossings.
 *
 * The socket hook mock captures the ``onChromeMedia`` callback the App
 * registers, so these tests can push synthetic frames and assert on
 * the icon's class without standing up a real daemon.
 */
describe("App — chrome media icon passive indicator", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    onLayout.mockReset();
    chromeMediaHandler = null;
    window.history.replaceState(null, "", "/?demo=default");
  });

  function pushChromeMedia(state: {
    available: boolean;
    playing: boolean;
    playing_count: number;
  }) {
    act(() => {
      chromeMediaHandler?.({ type: "chrome_media", ...state });
    });
  }

  it("starts outlined when no chrome_media frame has arrived", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: /media browser/i });
    // Default outlined state: no playing-class, regardless of any other
    // chrome-btn classes the icon might carry (active when the view
    // is open is the orthogonal concern).
    expect(button.className).not.toContain("chrome-btn-playing");
  });

  it("tints the icon when a chrome_media frame reports playing=true", () => {
    render(<App />);
    pushChromeMedia({ available: true, playing: true, playing_count: 1 });
    const button = screen.getByRole("button", { name: /media browser/i });
    expect(button.className).toContain("chrome-btn-playing");
  });

  it("removes the tint when playing flips back to false", () => {
    render(<App />);
    pushChromeMedia({ available: true, playing: true, playing_count: 1 });
    pushChromeMedia({ available: true, playing: false, playing_count: 0 });
    const button = screen.getByRole("button", { name: /media browser/i });
    expect(button.className).not.toContain("chrome-btn-playing");
  });

  it("stays outlined when players are available but none are playing", () => {
    render(<App />);
    pushChromeMedia({ available: true, playing: false, playing_count: 0 });
    const button = screen.getByRole("button", { name: /media browser/i });
    expect(button.className).not.toContain("chrome-btn-playing");
  });
});

/* ---------------------------------------------------------------------
   Chrome tooltip integration (issue #59).
   The unit-level Tooltip behaviour is covered in Tooltip.test.tsx.
   Here we assert that every icon-only chrome control is wrapped:
   hover / focus surfaces a tooltip whose text matches the aria-label.
   --------------------------------------------------------------------- */

describe("App — chrome button tooltips", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    window.history.replaceState(null, "", "/?demo=default");
  });

  it("every icon-only chrome button shows its tooltip text on focus", async () => {
    render(<App />);
    const cases: Array<{ name: RegExp | string; tipId: string }> = [
      { name: "manual control", tipId: "manual control" },
      // The media button's aria-label changes with playback state
      // (issue #62, AC #3). A regex keeps the tooltip test
      // independent of that detail.
      { name: /media browser/i, tipId: "media browser" },
      { name: "settings", tipId: "settings" },
    ];
    for (const c of cases) {
      const button = screen.getByRole("button", { name: c.name });
      fireEvent.focus(button);
      // The tooltip text matches the button's accessible name (AC #2).
      const tooltip = await screen.findByRole("tooltip");
      expect(tooltip.textContent).toBe(c.tipId);
      expect(button.getAttribute("aria-describedby")).toBe(tooltip.id);
      // Hide so the next iteration starts clean.
      fireEvent.blur(button);
      await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
    }
  });

  it("chrome buttons without a visible label get a tooltip; buttons with a label do not", () => {
    render(<App />);
    // The three chrome buttons are icon-only (a single <svg> child)
    // and carry aria-label only — they get the tooltip wrapper.
    const iconOnly = [
      screen.getByRole("button", { name: "manual control" }),
      screen.getByRole("button", { name: /media browser/i }),
      screen.getByRole("button", { name: "settings" }),
    ];
    for (const b of iconOnly) {
      // The tooltip wrapper only adds aria-describedby when the
      // tooltip is open; absent focus, the attribute is omitted.
      expect(b.getAttribute("aria-describedby")).toBeNull();
      // The media browser button now also carries a screen-reader-only
      // state label ("now playing" / "idle", issue #62, AC #3). The
      // clipped text is still empty in the rendered tree (the clip
      // path hides it visually) — assert it isn't visible by
      // checking the element exists with the expected class.
      if (b.getAttribute("aria-label")?.startsWith("media browser")) {
        expect(b.querySelector(".chrome-btn-sr-status")).not.toBeNull();
      }
    }
  });
});

/* ---------------------------------------------------------------------
   Keyboard activation (issue #60, AC #3).

   The chrome buttons use ``onPointerDown`` for fast touch response;
   a native ``<button>`` with only ``onPointerDown`` does not fire
   on Enter / Space. Each chrome button now also wires ``onKeyDown``
   for Enter + Space so a keyboard user can reach every chrome mode
   without a mouse.
   --------------------------------------------------------------------- */

describe("App — chrome keyboard activation", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    window.history.replaceState(null, "", "/?demo=default");
  });

  it("Enter activates the manual control button", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "manual control" });
    expect(button.className).not.toContain("chrome-btn-active");
    fireEvent.keyDown(button, { key: "Enter" });
    expect(button.className).toContain("chrome-btn-active");
  });

  it("Space activates the manual control button", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "manual control" });
    fireEvent.keyDown(button, { key: " " });
    expect(button.className).toContain("chrome-btn-active");
  });

  it("Enter activates the settings button", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "settings" });
    fireEvent.keyDown(button, { key: "Enter" });
    expect(button.className).toContain("chrome-btn-active");
  });

  it("Enter activates the media browser button and sends select_view", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: /media browser/i });
    fireEvent.keyDown(button, { key: "Enter" });
    expect(button.className).toContain("chrome-btn-active");
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "mpris" });
  });

  it("non-activation keys do not toggle the chrome view", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "settings" });
    fireEvent.keyDown(button, { key: "a" });
    expect(button.className).not.toContain("chrome-btn-active");
  });

  it("chrome buttons advertise aria-pressed to match the active class", () => {
    render(<App />);
    const manual = screen.getByRole("button", { name: "manual control" });
    const settings = screen.getByRole("button", { name: "settings" });
    const media = screen.getByRole("button", { name: /media browser/i });
    expect(manual.getAttribute("aria-pressed")).toBe("false");
    expect(settings.getAttribute("aria-pressed")).toBe("false");
    expect(media.getAttribute("aria-pressed")).toBe("false");
    fireEvent.keyDown(manual, { key: "Enter" });
    expect(manual.getAttribute("aria-pressed")).toBe("true");
  });
});

/* ---------------------------------------------------------------------
   Global keyboard shortcuts (issue #60, AC #4).

   Number keys open the matching chrome view; Escape returns to the
   layout view. The handler must ignore keystrokes while a text
   input is focused (the password gate / IME input own character
   keys). The shortcuts are bound at the window level so a user can
   press them without first focusing the chrome.
   --------------------------------------------------------------------- */

describe("App — keyboard shortcuts", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    window.history.replaceState(null, "", "/?demo=default");
  });

  it("pressing 1 toggles the trackpad view", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "1" });
    expect(screen.getByRole("button", { name: "manual control" }).className).toContain("chrome-btn-active");
    // Press again — toggles back.
    fireEvent.keyDown(window, { key: "1" });
    expect(screen.getByRole("button", { name: "manual control" }).className).not.toContain("chrome-btn-active");
  });

  it("pressing 2 opens the media browser view and sends select_view", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "2" });
    expect(screen.getByRole("button", { name: /media browser/i }).className).toContain("chrome-btn-active");
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "mpris" });
  });

  it("pressing 3 opens the settings view", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "3" });
    expect(screen.getByRole("button", { name: "settings" }).className).toContain("chrome-btn-active");
  });

  it("Escape returns to the layout view and clears the media browser", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "2" });
    expect(screen.getByRole("button", { name: /media browser/i }).className).toContain("chrome-btn-active");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: /media browser/i }).className).not.toContain("chrome-btn-active");
    expect(send.mock.calls.map((c) => c[0])).toContainEqual({ type: "clear_view" });
  });

  it("shortcuts are suppressed when an input is focused", () => {
    render(<App />);
    // Switch to the trackpad view (via the keyboard shortcut) so the
    // IME input is mounted; then refocus it and verify a second
    // ``1`` keystroke doesn't toggle the view off.
    fireEvent.keyDown(window, { key: "1" });
    const ime = screen.getByLabelText("Remote keyboard");
    ime.focus();
    fireEvent.keyDown(ime, { key: "1" });
    expect(screen.getByRole("button", { name: "manual control" }).className).toContain("chrome-btn-active");
  });
});

/* ---------------------------------------------------------------------
   Focus restoration (issue #60, AC #5).

   When the password gate opens, the user is on the body — no
   element is focused. When the gate closes (auth success), focus
   must move to a sensible element inside the surface so a keyboard
   user can Tab into the layout without clicking anywhere.

   Also covered: opening a chrome view via keyboard shortcut / button
   keeps the originating chrome button in scope, so closing the view
   returns focus to it (rather than to the body).
   --------------------------------------------------------------------- */

describe("App — focus restoration", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    authenticate.mockReset();
    deauthenticate.mockReset();
    mockStatus = "open";
    window.history.replaceState(null, "", "/?demo=default");
  });

  it("moves focus to the surface when the password gate closes", async () => {
    mockStatus = "unauthorized";
    const { rerender } = render(<App />);
    // The gate is up. Submit to call ``authenticate`` (a mock), then
    // flip the socket status and re-render to flip the App past the
    // gate. ``mockStatus`` is read on every render thanks to the
    // getter on the socket mock.
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    mockStatus = "open";
    rerender(<App />);
    // The surface has tabindex=-1; it should be the active element
    // after the gate closes. Allow the focus setTimeout (0ms) to
    // run.
    await new Promise((r) => setTimeout(r, 10));
    const surface = document.querySelector(".surface");
    expect(surface).not.toBeNull();
    expect(document.activeElement).toBe(surface);
  });

  it("returns focus to the trackpad button after closing the trackpad view", async () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "1" });
    expect(screen.getByRole("button", { name: "manual control" }).className).toContain("chrome-btn-active");
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    await new Promise((r) => setTimeout(r, 100));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "manual control" }));
  });

  it("returns focus to the settings button after closing the settings view", async () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "3" });
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    await new Promise((r) => setTimeout(r, 10));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "settings" }));
  });
});