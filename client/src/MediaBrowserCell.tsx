import { useMemo } from "react";
import { Disc, Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { Icon } from "./Icon";
import type { MediaReading } from "./media-store";
import type {
  MediaBrowserEmptyState,
  MediaBrowserOrdering,
  Widget,
} from "./protocol";

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

function artSlot(reading: MediaReading) {
  // The wire's ``art_token`` carries a daemon-side cache-busting id
  // for the current track's art. The spec scopes image transfer to
  // a follow-up ticket, so v1 doesn't fetch the URL; we still
  // surface its presence in the DOM as a data attribute so a future
  // image-renderer can pick it up without a protocol change.
  if (reading.art_token) {
    return (
      <span
        className="mediabrowser-art-icon"
        data-art-token={reading.art_token}
        aria-hidden
      />
    );
  }
  const entry = reading.desktop_entry ? DESKTOP_ICONS[reading.desktop_entry] : null;
  if (entry) return <Icon icon={entry} className="mediabrowser-art-icon" />;
  return <Disc className="mediabrowser-art-icon" />;
}

/** Group rows by playback for the playing-first ordering.
 *
 * The wire's ``playing`` field is a boolean: ``True`` (Playing),
 * ``False`` (Paused or Stopped, conflated), or ``null`` (unknown).
 * The spec mentions three buckets — Playing / Paused / Stopped —
 * but the daemon's relay collapses the latter two into a single
 * ``False`` per ``_playback_to_playing`` in ``daemon/deckd/mpris.py``.
 * Two buckets are what the wire can express today; a future wire
 * extension (e.g. relaying ``PlaybackStatus`` as a string) would let
 * the order match the spec verbatim. */
function bucketFor(playing: boolean | null | undefined): 0 | 1 {
  return playing === true ? 0 : 1;
}

function orderRows(rows: Row[], ordering: MediaBrowserOrdering): Row[] {
  if (ordering === "stable") {
    // First-seen bus-name order is the natural insertion order of the
    // ``Record``; the media store rebuilds its cache with object
    // spread (``{...previous, [state.id]: state}``) which preserves
    // that order across updates.
    return rows;
  }
  // playing_first: stable order within each bucket, sorted by row id
  // so the test (and a real run that re-sorts on every state change)
  // gets a deterministic result.
  return [...rows].sort((a, b) => {
    const diff = bucketFor(a.reading.playing) - bucketFor(b.reading.playing);
    if (diff !== 0) return diff;
    return a.id.localeCompare(b.id);
  });
}

export function MediaBrowserCell({ widget, states, onCommand }: Props) {
  const ordering: MediaBrowserOrdering = widget.ordering ?? "playing_first";
  const emptyState: MediaBrowserEmptyState = widget.empty_state ?? "show";

  // Filter the parent store down to MPRIS rows. The store is keyed by
  // widget id, so a row whose id starts with ``mpris.`` belongs to
  // this widget; the VLC media widget's ids don't, so they're not
  // shown here.
  const rows = useMemo<Row[]>(() => {
    const result: Row[] = [];
    for (const [id, reading] of Object.entries(states)) {
      if (!id.startsWith("mpris.")) continue;
      result.push({ id, reading });
    }
    return orderRows(result, ordering);
  }, [states, ordering]);

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
            {artSlot(reading)}
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
