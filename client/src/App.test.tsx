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
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
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
      status: "open",
      send,
      authenticate: vi.fn(),
      deauthenticate: vi.fn(),
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
    expect(screen.getByRole("button", { name: "media browser" })).toBeTruthy();
  });

  it("sends select_view on first click and applies the active class", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "media browser" });
    expect(button.className).not.toContain("chrome-btn-active");
    fireEvent.pointerDown(button);
    expect(send).toHaveBeenCalledWith({ type: "select_view", view: "mpris" });
    expect(button.className).toContain("chrome-btn-active");
  });

  it("sends clear_view on a second click and removes the active class", () => {
    render(<App />);
    const button = screen.getByRole("button", { name: "media browser" });
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
    const button = screen.getByRole("button", { name: "media browser" });
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
    const button = screen.getByRole("button", { name: "media browser" });
    // Default outlined state: no playing-class, regardless of any other
    // chrome-btn classes the icon might carry (active when the view
    // is open is the orthogonal concern).
    expect(button.className).not.toContain("chrome-btn-playing");
  });

  it("tints the icon when a chrome_media frame reports playing=true", () => {
    render(<App />);
    pushChromeMedia({ available: true, playing: true, playing_count: 1 });
    const button = screen.getByRole("button", { name: "media browser" });
    expect(button.className).toContain("chrome-btn-playing");
  });

  it("removes the tint when playing flips back to false", () => {
    render(<App />);
    pushChromeMedia({ available: true, playing: true, playing_count: 1 });
    pushChromeMedia({ available: true, playing: false, playing_count: 0 });
    const button = screen.getByRole("button", { name: "media browser" });
    expect(button.className).not.toContain("chrome-btn-playing");
  });

  it("stays outlined when players are available but none are playing", () => {
    render(<App />);
    pushChromeMedia({ available: true, playing: false, playing_count: 0 });
    const button = screen.getByRole("button", { name: "media browser" });
    expect(button.className).not.toContain("chrome-btn-playing");
  });
});