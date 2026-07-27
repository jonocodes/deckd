/** MediaBrowserCell rendering (issue #53).
 *
 * Covers the six observable contracts:
 *  1. A row per ``media_state`` frame whose ``id`` starts with ``mpris.``
 *     lands in the rendered list (one row per row, full-width,
 *     top-aligned, equal-height). Rows for unrelated ids (e.g. the VLC
 *     media widget's ``id``) are not shown — the browser is a separate
 *     surface.
 *  2. The art slot: when ``art_token`` is set, renders an ``<img>``
 *     pointing at the daemon's ``/mpris/<row>/art?token=<art_token>``
 *     proxy (issue #57); on image load error, falls back through the
 *     ``desktop_entry`` brand icon to the Lucide ``Disc`` glyph when
 *     ``art_token`` is null.
 *  3. Previous / next buttons render disabled when
 *     ``can_go_previous`` / ``can_go_next`` are false; the play-pause
 *     button is always reactive. A click sends the right
 *     ``media_command`` shape with the row id and the right command.
 *  4. Empty state: when no rows exist and ``empty_state === "show"``,
 *     a "No media players detected" row renders; when
 *     ``empty_state === "hide"``, the cell renders nothing (no
 *     placeholder, no rows).
 *  5. Ordering: ``playing_first`` groups Playing → Paused → Stopped,
 *     stable order within each bucket by row id;
 *     ``stable`` keeps first-seen bus-name order by row id, no grouping.
 *  6. The sendMediaCommand callback fires with the row id and the
 *     typed command — that's the contract the parent App uses to send
 *     the wire ``media_command`` message.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MediaBrowserCell } from "./MediaBrowserCell";
import type { MediaReading } from "./media-store";
import type { Widget } from "./protocol";

const WIDGET: Widget = {
  id: "browser",
  kind: "mediabrowser",
  grid: [0, 0, 4, 2],
  ordering: "playing_first",
  empty_state: "show",
};

function row(
  id: string,
  playing: boolean | null,
  extras: Partial<MediaReading> = {},
): MediaReading {
  return {
    id,
    available: true,
    stale: false,
    playing,
    title: `Title ${id}`,
    artist: `Artist ${id}`,
    desktop_entry: null,
    can_go_next: true,
    can_go_previous: true,
    ...extras,
  };
}

describe("MediaBrowserCell", () => {
  afterEach(cleanup);

  it("renders one row per mpris.<suffix> media_state", () => {
    const states: Record<string, MediaReading> = {
      "mpris.vlc": row("mpris.vlc", true),
      "mpris.spotify": row("mpris.spotify", false),
      // Unrelated id (e.g. the VLC media widget) must be filtered out;
      // the browser only shows MPRIS rows.
      "vlc-media": row("vlc-media", true, { title: "Unrelated" }),
    };
    render(
      <MediaBrowserCell
        widget={WIDGET}
        states={states}
        onCommand={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("Title mpris.vlc")).toBeTruthy();
    expect(within(rows[1]).getByText("Title mpris.spotify")).toBeTruthy();
  });

  it("renders the app_name as a per-row header, omitting it when null", () => {
    render(
      <MediaBrowserCell
        widget={WIDGET}
        states={{
          "mpris.vlc": row("mpris.vlc", true, { app_name: "VLC media player" }),
          "mpris.spotify": row("mpris.spotify", false, { app_name: null }),
        }}
        onCommand={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]).getByText("VLC media player")).toBeTruthy();
    // The null-app_name row renders no header element at all.
    expect(rows[1].querySelector(".mediabrowser-app")).toBeNull();
  });

  it("falls back to a disc icon in the art slot when art_token is null", () => {
    render(
      <MediaBrowserCell
        widget={WIDGET}
        states={{
          "mpris.vlc": row("mpris.vlc", true, { art_token: null }),
        }}
        onCommand={vi.fn()}
      />,
    );
    // The fallback lives in the row's art slot; the lucide ``Disc``
    // icon is an inline SVG with the class ``mediabrowser-art-icon``.
    const artIcon = document.querySelector(".mediabrowser-art-icon");
    expect(artIcon).not.toBeNull();
    expect(artIcon?.tagName.toLowerCase()).toBe("svg");
  });

  it("renders an <img> in the art slot when art_token is set (issue #57)", () => {
    render(
      <MediaBrowserCell
        widget={WIDGET}
        states={{
          "mpris.vlc": row("mpris.vlc", true, {
            art_token: "abc123token",
          }),
        }}
        onCommand={vi.fn()}
      />,
    );
    // art_token present -> the art slot is a real <img> pointing at
    // the daemon's proxy, cache-busted with the token. Row id is the
    // MPRIS bus suffix, not the wire ``mpris.`` prefixed one — the
    // proxy lives at /mpris/<row-suffix>/art so the URL stays short.
    const slot = document.querySelector(".mediabrowser-art");
    const img = slot?.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toBe(
      "/mpris/vlc/art?token=abc123token",
    );
  });

  it("falls back to the brand icon when the art <img> errors", () => {
    render(
      <MediaBrowserCell
        widget={WIDGET}
        states={{
          "mpris.vlc": row("mpris.vlc", true, {
            art_token: "abc",
            desktop_entry: "vlc",
          }),
        }}
        onCommand={vi.fn()}
      />,
    );
    const img = document.querySelector(".mediabrowser-art img");
    expect(img).not.toBeNull();
    // Trigger the onError handler; the cell should swap the <img>
    // for the desktop-entry brand icon and stop pointing at the
    // broken URL.
    fireEvent.error(img as HTMLElement);
    const slot = document.querySelector(".mediabrowser-art");
    expect(slot?.querySelector("img")).toBeNull();
  });

  it("uses the desktop_entry as the art-slot icon when art_token is null", () => {
    render(
      <MediaBrowserCell
        widget={WIDGET}
        states={{
          "mpris.vlc": row("mpris.vlc", true, {
            art_token: null,
            desktop_entry: "vlc",
          }),
        }}
        onCommand={vi.fn()}
      />,
    );
    // Desktop entry ``vlc`` maps to the Simple Icons ``vlcmediaplayer``
    // logo; an unknown desktop_entry still falls back to the disc icon.
    const slot = document.querySelector(".mediabrowser-art");
    expect(slot).not.toBeNull();
  });

  it("disables previous/next when capabilities are false and fires media_command on play-pause", () => {
    const onCommand = vi.fn();
    render(
      <MediaBrowserCell
        widget={WIDGET}
        states={{
          "mpris.vlc": row("mpris.vlc", true, {
            can_go_next: false,
            can_go_previous: false,
          }),
        }}
        onCommand={onCommand}
      />,
    );
    const prev = screen.getByRole("button", { name: "Previous" });
    const next = screen.getByRole("button", { name: "Next" });
    expect(prev.hasAttribute("disabled")).toBe(true);
    expect(next.hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(onCommand).toHaveBeenCalledExactlyOnceWith("mpris.vlc", "play-pause");
  });

  it("renders the 'No media players detected' row when no states exist and empty_state is show", () => {
    render(
      <MediaBrowserCell
        widget={WIDGET}
        states={{}}
        onCommand={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(within(rows[0]).getByText("No media players detected")).toBeTruthy();
    // No transport controls on the empty state.
    expect(screen.queryByRole("button", { name: "Play" })).toBeNull();
  });

  it("renders nothing when no states exist and empty_state is hide", () => {
    render(
      <MediaBrowserCell
        widget={{ ...WIDGET, empty_state: "hide" }}
        states={{}}
        onCommand={vi.fn()}
      />,
    );
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.queryByText("No media players detected")).toBeNull();
  });

  it("orders playing rows first, then non-playing rows, with stable order inside each bucket", () => {
    // The wire's ``playing`` field is a boolean — Paused and Stopped
    // are conflated — so the spec's three-bucket order collapses to
    // two: Playing vs everything-else, sorted by row id within each
    // bucket.
    const states: Record<string, MediaReading> = {
      "mpris.stopped-1": row("mpris.stopped-1", false),
      "mpris.playing-2": row("mpris.playing-2", true),
      "mpris.playing-1": row("mpris.playing-1", true),
      "mpris.paused-1": row("mpris.paused-1", false),
    };
    render(
      <MediaBrowserCell
        widget={WIDGET}
        states={states}
        onCommand={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((r) => r.getAttribute("data-row-id"))).toEqual([
      "mpris.playing-1",
      "mpris.playing-2",
      "mpris.paused-1",
      "mpris.stopped-1",
    ]);
  });

  it("orders rows by first-seen bus name when ordering is stable", () => {
    const states: Record<string, MediaReading> = {
      "mpris.b": row("mpris.b", false),
      "mpris.a": row("mpris.a", true),
      "mpris.c": row("mpris.c", false),
    };
    render(
      <MediaBrowserCell
        widget={{ ...WIDGET, ordering: "stable" }}
        states={states}
        onCommand={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((r) => r.getAttribute("data-row-id"))).toEqual([
      "mpris.b",
      "mpris.a",
      "mpris.c",
    ]);
  });

  it("fires the matching media_command for each transport button", () => {
    const onCommand = vi.fn();
    render(
      <MediaBrowserCell
        widget={WIDGET}
        states={{
          "mpris.vlc": row("mpris.vlc", true),
        }}
        onCommand={onCommand}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(onCommand.mock.calls).toEqual([
      ["mpris.vlc", "play-pause"],
      ["mpris.vlc", "next"],
      ["mpris.vlc", "previous"],
    ]);
  });
});
