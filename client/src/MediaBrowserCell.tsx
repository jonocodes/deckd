import { useMemo, useState } from "react";
import { Disc, Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { Icon } from "./Icon";
import type { MediaReading } from "./media-store";
import type { MediaBrowserEmptyState, Widget } from "./protocol";

type Props = {
  widget: Widget;
  /** Live ``media_state`` cache, keyed by id. The browser filters to ids
   * starting with ``mpris.`` — every other id belongs to a different
   * widget (e.g. the VLC media card) and is not shown here. */
  states: Record<string, MediaReading>;
  onCommand: (id: string, command: "play-pause" | "next" | "previous") => void;
};

type Row = {
  id: string;
  reading: MediaReading;
};

/** MPRIS bus suffixes that have a client-side icon mapping (issue #53).
 * Add entries here as new players are tested; an unknown ``desktop_entry``
 * falls back to the Lucide ``Disc`` glyph so the row still reads as "a
 * media player". The mapping is the desktop file basename → the Simple
 * Icons slug the client can render. Empty / unknown entries fall through. */
const DESKTOP_ICONS: Record<string, { source: "simple-icons"; name: string }> = {
  vlc: { source: "simple-icons", name: "vlcmediaplayer" },
  spotify: { source: "simple-icons", name: "spotify" },
  firefox: { source: "simple-icons", name: "firefox" },
  mpv: { source: "simple-icons", name: "mpv" },
  rhythmbox: { source: "simple-icons", name: "rhythmbox" },
  audacity: { source: "simple-icons", name: "audacity" },
};

/** The art slot for a single row. When the daemon reported an
 * ``art_token`` we render a real ``<img>`` pointing at the daemon's
 * ``/mpris/<row-suffix>/art?token=<art_token>`` proxy (issue #57);
 * the token is the cache-buster so the browser only refetches on
 * track change. A network / 404 error falls back through the
 * ``desktop_entry`` brand icon to the Lucide ``Disc`` glyph so the
 * row never reads as broken. */
function ArtSlot({ id, reading }: { id: string; reading: MediaReading }) {
  const [failedToken, setFailedToken] = useState<string | null>(null);
  const rowSuffix = id.startsWith("mpris.") ? id.slice("mpris.".length) : id;
  if (reading.art_token && failedToken !== reading.art_token) {
    return (
      <img
        className="mediabrowser-art-img"
        alt=""
        src={`/mpris/${encodeURIComponent(rowSuffix)}/art?token=${encodeURIComponent(reading.art_token)}`}
        onError={() => setFailedToken(reading.art_token ?? null)}
      />
    );
  }
  const entry = reading.desktop_entry ? DESKTOP_ICONS[reading.desktop_entry] : null;
  if (entry) return <Icon icon={entry} className="mediabrowser-art-icon" />;
  return <Disc className="mediabrowser-art-icon" />;
}

export function MediaBrowserCell({ widget, states, onCommand }: Props) {
  const emptyState: MediaBrowserEmptyState = widget.empty_state ?? "show";

  // Filter the parent store down to MPRIS rows. The store is keyed by
  // widget id, so a row whose id starts with ``mpris.`` belongs to
  // this widget; the VLC media widget's ids don't, so they're not
  // shown here. Rows are emitted in the daemon's ``row_ids`` order
  // (session bus ``ListNames`` reply — matching GNOME Shell, issue
  // #58). The store rebuilds its cache with object spread so insertion
  // order is preserved across updates.
  const rows = useMemo<Row[]>(() => {
    const result: Row[] = [];
    for (const [id, reading] of Object.entries(states)) {
      if (!id.startsWith("mpris.")) continue;
      result.push({ id, reading });
    }
    return result;
  }, [states]);

  if (rows.length === 0) {
    if (emptyState === "hide") return null;
    return (
      <ul className="mediabrowser-list" role="list">
        <li className="mediabrowser-row mediabrowser-row-empty" role="listitem">
          No media players detected
        </li>
      </ul>
    );
  }

  return (
    <ul className="mediabrowser-list" role="list">
      {rows.map(({ id, reading }) => (
        <li
          key={id}
          data-row-id={id}
          className="mediabrowser-row"
          role="listitem"
        >
          {reading.app_name ? (
            <div className="mediabrowser-app">{reading.app_name}</div>
          ) : null}
          <div className="mediabrowser-art" aria-hidden>
            <ArtSlot id={id} reading={reading} />
          </div>
          <div className="mediabrowser-text">
            <div className="mediabrowser-title">{reading.title ?? "—"}</div>
            <div className="mediabrowser-subtitle">{reading.artist ?? "—"}</div>
          </div>
          <div className="mediabrowser-transport">
            <button
              type="button"
              className="mediabrowser-skip"
              aria-label="Previous"
              disabled={reading.can_go_previous === false}
              onClick={() => onCommand(id, "previous")}
            >
              <SkipBack fill="currentColor" />
            </button>
            <button
              type="button"
              className="mediabrowser-play"
              aria-label={reading.playing ? "Pause" : "Play"}
              aria-pressed={Boolean(reading.playing)}
              onClick={() => onCommand(id, "play-pause")}
            >
              {reading.playing ? <Pause fill="currentColor" /> : <Play fill="currentColor" />}
            </button>
            <button
              type="button"
              className="mediabrowser-skip"
              aria-label="Next"
              disabled={reading.can_go_next === false}
              onClick={() => onCommand(id, "next")}
            >
              <SkipForward fill="currentColor" />
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
