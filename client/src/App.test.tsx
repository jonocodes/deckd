/** Chrome media icon + nowplaying view (issue #51).
 *
 * Covers the three observable contracts:
 *  1. The icon renders in the bottom chrome strip next to settings.
 *  2. A first click opens the view (active class + ``select_view: "mpris"``
 *     on the wire); a second click closes it (active class gone +
 *     ``clear_view`` on the wire). Mirrors the settings button exactly.
 *  3. While the view is open, the surface renders the browser area with
 *     the "Nothing playing" placeholder instead of the
 *     focused-app layout. The placeholder is unconditional for v1
 *     (real rows arrive via the NowPlayingCell ticket #53).
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
    expect(screen.getByRole("button", { name: /now playing/i })).toBeTruthy();
  });

  it("sends select_view on first click and applies the active class", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: /now playing/i });
    expect(button.className).not.toContain("chrome-btn-active");
    fireEvent.pointerDown(button);
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "mpris" });
    expect(button.className).toContain("chrome-btn-active");
    expect(window.location.pathname).toBe("/now-playing");
  });

  it("sends clear_view on a second click and removes the active class", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: /now playing/i });
    fireEvent.pointerDown(button); // open
    fireEvent.pointerDown(button); // close
    expect(send.mock.calls.map((c) => c[0])).toEqual([
      { type: "select_view", view: "mpris" },
      { type: "clear_view" },
    ]);
    expect(button.className).not.toContain("chrome-btn-active");
    expect(window.location.pathname).toBe("/");
  });

  it("opens a view from its URL and responds to browser history", () => {
    window.history.replaceState(null, "", "/settings?demo=default");
    render(<App />);
    expect(screen.getByRole("heading", { name: /settings/i })).toBeTruthy();

    window.history.pushState(null, "", "/trackpad?demo=default");
    act(() => window.dispatchEvent(new PopStateEvent("popstate")));
    expect(screen.getByRole("heading", { name: /manual control/i })).toBeTruthy();
  });

  it("renders the editor button in the bottom chrome", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "layout editor" })).toBeTruthy();
  });

  it("sends select_view on editor button click and applies the active class", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "layout editor" });
    expect(button.className).not.toContain("chrome-btn-active");
    fireEvent.pointerDown(button);
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "editor" });
    expect(button.className).toContain("chrome-btn-active");
  });

  it("sends clear_view on a second editor button click and removes the active class", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "layout editor" });
    fireEvent.pointerDown(button); // open
    fireEvent.pointerDown(button); // close
    expect(send.mock.calls.map((c) => c[0])).toEqual([
      { type: "select_view", view: "editor" },
      { type: "clear_view" },
    ]);
    expect(button.className).not.toContain("chrome-btn-active");
  });

  it("renders the browser placeholder in place of the focused-app layout while open", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: /now playing/i });
    fireEvent.pointerDown(button);
    // The default demo has no nowplaying widget, so the chrome view
    // falls back to the "no players" placeholder (issue #51; #53 added
    // the real per-row cell that takes over once a nowplaying
    // widget is in the active layout).
    expect(screen.getByText("Nothing playing")).toBeTruthy();
  });
});

/** Chrome media icon + nowplaying view with the per-row cell (issue #53).
 *
 * The mpris demo seeds the active nowplaying widget with four MPRIS
 * rows, so opening the chrome view renders the real per-row cell
 * (not the placeholder). Clicks on the per-row transport buttons
 * fire the wire ``media_command`` with the row's ``mpris.<suffix>``
 * id and the right command — that's the bridge to the server-side
 * dispatch in #54.
 */
describe("App — nowplaying per-row cell", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    window.history.replaceState(null, "", "/?demo=mpris");
  });

  it("renders the per-row browser with seeded MPRIS rows", () => {
    render(<App />);
    // ``?demo=mpris`` opens straight into the nowplaying view, so
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
    const button = screen.getByRole("button", { name: /now playing/i });
    // Default outlined state: no playing-class, regardless of any other
    // chrome-btn classes the icon might carry (active when the view
    // is open is the orthogonal concern).
    expect(button.className).not.toContain("chrome-btn-playing");
  });

  it("tints the icon when a chrome_media frame reports playing=true", () => {
    render(<App />);
    pushChromeMedia({ available: true, playing: true, playing_count: 1 });
    const button = screen.getByRole("button", { name: /now playing/i });
    expect(button.className).toContain("chrome-btn-playing");
  });

  it("removes the tint when playing flips back to false", () => {
    render(<App />);
    pushChromeMedia({ available: true, playing: true, playing_count: 1 });
    pushChromeMedia({ available: true, playing: false, playing_count: 0 });
    const button = screen.getByRole("button", { name: /now playing/i });
    expect(button.className).not.toContain("chrome-btn-playing");
  });

  it("stays outlined when players are available but none are playing", () => {
    render(<App />);
    pushChromeMedia({ available: true, playing: false, playing_count: 0 });
    const button = screen.getByRole("button", { name: /now playing/i });
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
      { name: /now playing/i, tipId: "now playing" },
      { name: "layout editor", tipId: "layout editor" },
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
      screen.getByRole("button", { name: /now playing/i }),
      screen.getByRole("button", { name: "layout editor" }),
      screen.getByRole("button", { name: "settings" }),
    ];
    for (const b of iconOnly) {
      // The tooltip wrapper only adds aria-describedby when the
      // tooltip is open; absent focus, the attribute is omitted.
      expect(b.getAttribute("aria-describedby")).toBeNull();
      // The now-playing button now also carries a screen-reader-only
      // state label ("now playing" / "idle", issue #62, AC #3). The
      // clipped text is still empty in the rendered tree (the clip
      // path hides it visually) — assert it isn't visible by
      // checking the element exists with the expected class.
      if (b.getAttribute("aria-label")?.startsWith("now playing")) {
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

  it("Enter activates the now-playing button and sends select_view", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: /now playing/i });
    fireEvent.keyDown(button, { key: "Enter" });
    expect(button.className).toContain("chrome-btn-active");
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "mpris" });
  });

  it("Enter activates the editor button and sends select_view", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "layout editor" });
    fireEvent.keyDown(button, { key: "Enter" });
    expect(button.className).toContain("chrome-btn-active");
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "editor" });
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
    const media = screen.getByRole("button", { name: /now playing/i });
    const editor = screen.getByRole("button", { name: "layout editor" });
    expect(manual.getAttribute("aria-pressed")).toBe("false");
    expect(settings.getAttribute("aria-pressed")).toBe("false");
    expect(media.getAttribute("aria-pressed")).toBe("false");
    expect(editor.getAttribute("aria-pressed")).toBe("false");
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

  it("pressing 2 opens the now-playing view and sends select_view", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "2" });
    expect(screen.getByRole("button", { name: /now playing/i }).className).toContain("chrome-btn-active");
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "mpris" });
  });

  it("pressing 3 opens the settings view", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "3" });
    expect(screen.getByRole("button", { name: "settings" }).className).toContain("chrome-btn-active");
  });

  it("pressing 4 opens the editor view and sends select_view", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "4" });
    expect(screen.getByRole("button", { name: "layout editor" }).className).toContain("chrome-btn-active");
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "editor" });
  });

  it("Escape returns to the layout view and clears the now-playing view", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "2" });
    expect(screen.getByRole("button", { name: /now playing/i }).className).toContain("chrome-btn-active");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: /now playing/i }).className).not.toContain("chrome-btn-active");
    expect(send.mock.calls.map((c) => c[0])).toContainEqual({ type: "clear_view" });
  });

  it("Escape clears the editor view and sends clear_view", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "4" });
    expect(screen.getByRole("button", { name: "layout editor" }).className).toContain("chrome-btn-active");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: "layout editor" }).className).not.toContain("chrome-btn-active");
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

  it("returns focus to the editor button after closing the editor view", async () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "4" });
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    await new Promise((r) => setTimeout(r, 100));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "layout editor" }));
  });
});

/* ---------------------------------------------------------------------
   Screen-reader headings (issue #63, AC #2).

   Every surface must have a single top-level heading so screen reader
   users can jump by heading. The h1 lives inside <main> and changes
   content per active view. Only one surface is rendered at a time,
   so there is always exactly one h1 in the DOM.
   --------------------------------------------------------------------- */

describe("App — screen-reader headings", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    window.history.replaceState(null, "", "/?demo=default");
  });

  it("renders an h1 at the top of the main landmark", () => {
    render(<App />);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).not.toBeNull();
    expect(heading.closest("main")).not.toBeNull();
  });

  it("shows the app name as the heading in layout view", () => {
    render(<App />);
    // "demo=default" layout has app: "default (demo)" with no display_name,
    // so the heading falls back to the raw app token.
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "default (demo)",
    );
  });

  it("shows display_name as the heading when the layout has one", () => {
    window.history.replaceState(null, "", "/?demo=firefox");
    render(<App />);
    // Firefox demo has display_name: "Firefox".
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Firefox",
    );
  });

  it("heading changes to Settings when the settings view opens", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "3" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Settings",
    );
  });

  it("heading changes to Manual control when the trackpad view opens", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "1" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Manual control",
    );
  });

  it("heading changes to Now playing when the media view opens", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "2" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Now playing",
    );
  });

  it("heading changes to Layout editor when the editor view opens", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "4" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Layout editor",
    );
  });

  it("heading returns to the app name when returning to the layout", () => {
    render(<App />);
    fireEvent.keyDown(window, { key: "3" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Settings",
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "default (demo)",
    );
  });
});

/* ---------------------------------------------------------------------
   Stage 1 fallback header (issue #123).

   When the daemon reports ``is_default: true`` on a layout push, the
   client appends the live program's identity (``wm_class || app_id``)
   to the layout name in both the screen-reader heading and the visible
   chrome badge. Suppressed on identity/title matches, pinned views,
   and when the daemon sends ``focused_app: null``.

   The wire is the source of truth here; tests push synthetic frames
   through the mocked socket hook rather than going through the daemon.
   --------------------------------------------------------------------- */

describe("App — stage 1 fallback header suffix", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    onLayout.mockReset();
    mockStatus = "open";
    window.history.replaceState(null, "", "/?demo=default");
  });

  it("appends (wm_class) to the heading when is_default is true", () => {
    render(<App />);
    act(() => {
      onLayout({
        type: "layout",
        app: "default",
        display_name: "Home",
        jogstrip_enabled: true,
        widgets: [],
        focused_app: {
          app_id: "org.xfce.Terminal",
          wm_class: "xterm",
          title: "xterm",
          is_browser: false,
        },
        is_default: true,
      });
    });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Home (xterm)",
    );
  });

  it("appends (app_id) to the heading when wm_class is null", () => {
    render(<App />);
    act(() => {
      onLayout({
        type: "layout",
        app: "default",
        display_name: "Home",
        jogstrip_enabled: true,
        widgets: [],
        focused_app: {
          app_id: "org.kde.dolphin",
          wm_class: null,
          title: null,
          is_browser: false,
        },
        is_default: true,
      });
    });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Home (org.kde.dolphin)",
    );
  });

  it("does not append a suffix when is_default is false", () => {
    render(<App />);
    act(() => {
      onLayout({
        type: "layout",
        app: "firefox",
        display_name: "Firefox",
        jogstrip_enabled: true,
        widgets: [],
        focused_app: {
          app_id: "firefox",
          wm_class: "firefox",
          title: "Mozilla",
          is_browser: true,
        },
        is_default: false,
      });
    });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Firefox",
    );
  });

  it("does not append a suffix when focused_app is null", () => {
    render(<App />);
    act(() => {
      onLayout({
        type: "layout",
        app: "default",
        display_name: "Home",
        jogstrip_enabled: true,
        widgets: [],
        focused_app: null,
        is_default: true,
      });
    });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Home",
    );
  });

  it("appends the suffix to the aria-live layout announcement", () => {
    render(<App />);
    act(() => {
      onLayout({
        type: "layout",
        app: "default",
        display_name: "Home",
        jogstrip_enabled: true,
        widgets: [],
        focused_app: {
          app_id: "xterm",
          wm_class: "xterm",
          title: "xterm",
          is_browser: false,
        },
        is_default: true,
      });
    });
    expect(screen.getByRole("status").textContent).toBe(
      "Layout: Home (xterm)",
    );
  });

  it("appends the suffix to the visible chrome badge", () => {
    const { container } = render(<App />);
    act(() => {
      onLayout({
        type: "layout",
        app: "default",
        display_name: "Home",
        jogstrip_enabled: true,
        widgets: [],
        focused_app: {
          app_id: "xterm",
          wm_class: "xterm",
          title: "xterm",
          is_browser: false,
        },
        is_default: true,
      });
    });
    expect(
      container.querySelector(".app-badge-name")?.textContent,
    ).toBe("Home (xterm)");
  });
});

/* ---------------------------------------------------------------------
   aria-live announcements (issue #63, AC #4).

   Connection state, locked state, and layout switches must be
   announced via live regions so the user hears what changed without
   losing context. A hidden <span role="status"> in the bottom chrome
   carries the announcement text.
   --------------------------------------------------------------------- */

describe("App — aria-live announcements", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
    onLayout.mockReset();
    mockStatus = "open";
    window.history.replaceState(null, "", "/?demo=default");
  });

  it("renders a role=status live region in the chrome", () => {
    render(<App />);
    const status = screen.getByRole("status");
    expect(status).not.toBeNull();
  });

  it("announces a connection status change from open to closed", () => {
    const { rerender } = render(<App />);
    mockStatus = "closed";
    rerender(<App />);
    expect(screen.getByRole("status").textContent).toBe("Disconnected");
  });

  it("announces a connection status change to reconnecting", () => {
    const { rerender } = render(<App />);
    mockStatus = "connecting";
    rerender(<App />);
    expect(screen.getByRole("status").textContent).toBe("Reconnecting");
  });

  it("announces a locked status change", () => {
    const { rerender } = render(<App />);
    mockStatus = "unauthorized";
    rerender(<App />);
    expect(screen.getByRole("status").textContent).toBe("Locked");
  });

  it("announces connected when returning from closed", () => {
    mockStatus = "closed";
    const { rerender } = render(<App />);
    mockStatus = "open";
    rerender(<App />);
    expect(screen.getByRole("status").textContent).toBe("Connected");
  });

  it("announces a layout switch", () => {
    const { rerender } = render(<App />);
    act(() => {
      onLayout({
        type: "layout",
        app: "test-app",
        display_name: "Test App",
        jogstrip_enabled: true,
        widgets: [],
      });
    });
    rerender(<App />);
    expect(screen.getByRole("status").textContent).toBe("Layout: Test App");
  });

  it("falls back to the raw app token when the layout has no display_name", () => {
    render(<App />);
    act(() => {
      onLayout({
        type: "layout",
        app: "generic-app",
        jogstrip_enabled: true,
        widgets: [],
      });
    });
    expect(screen.getByRole("status").textContent).toBe("Layout: generic-app");
  });

  it("does not announce on the initial render", () => {
    render(<App />);
    expect(screen.getByRole("status").textContent).toBe("");
  });
});

/* ---------------------------------------------------------------------
   Accessibility CSS classes (issue #65).

   When the larger-controls, high-contrast, or reduce-motion toggles
   are on, the root .app element carries a corresponding CSS class
   so the stylesheet can apply the visual treatment independent of
   the OS-level media queries.
   --------------------------------------------------------------------- */

describe("App — accessibility CSS classes", () => {
  afterEach(cleanup);
  beforeEach(() => {
    send.mockReset();
  });

  it("applies a11y-larger-controls class when larger controls is on", () => {
    window.history.replaceState(null, "", "/?demo=default&largerControls=1");
    render(<App />);
    const app = document.querySelector(".app");
    expect(app?.classList.contains("a11y-larger-controls")).toBe(true);
  });

  it("applies a11y-high-contrast class when high contrast is on", () => {
    window.history.replaceState(null, "", "/?demo=default&highContrast=1");
    render(<App />);
    const app = document.querySelector(".app");
    expect(app?.classList.contains("a11y-high-contrast")).toBe(true);
  });

  it("applies a11y-reduce-motion class when reduce motion is on", () => {
    window.history.replaceState(null, "", "/?demo=default&reduceMotion=1");
    render(<App />);
    const app = document.querySelector(".app");
    expect(app?.classList.contains("a11y-reduce-motion")).toBe(true);
  });

  it("does not apply a11y classes when toggles are off", () => {
    window.history.replaceState(null, "", "/?demo=default");
    render(<App />);
    const app = document.querySelector(".app");
    expect(app?.classList.contains("a11y-larger-controls")).toBe(false);
    expect(app?.classList.contains("a11y-high-contrast")).toBe(false);
    expect(app?.classList.contains("a11y-reduce-motion")).toBe(false);
  });

  it("applies all three classes when all toggles are on", () => {
    window.history.replaceState(null, "", "/?demo=default&largerControls=1&highContrast=1&reduceMotion=1");
    render(<App />);
    const app = document.querySelector(".app");
    expect(app?.classList.contains("a11y-larger-controls")).toBe(true);
    expect(app?.classList.contains("a11y-high-contrast")).toBe(true);
    expect(app?.classList.contains("a11y-reduce-motion")).toBe(true);
  });
});
