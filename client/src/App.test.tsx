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
import type { ClientMessage } from "./protocol";

/** Replace the real socket hook with a controllable fake. The chrome
 * icon's job is to call ``send`` with the right message; the test
 * asserts on what was sent, not on daemon-side behaviour. */
const send = vi.fn<(message: ClientMessage) => void>();
vi.mock("./socket", () => ({
  useDeckdSocket: () => ({
    status: "open",
    send,
    authenticate: vi.fn(),
    deauthenticate: vi.fn(),
    hasPassword: false,
  }),
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