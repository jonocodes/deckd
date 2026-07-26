import type { Story } from "@ladle/react";
import { MediaBrowserCell } from "./MediaBrowserCell";
import type { MediaReading } from "./media-store";
import type { Widget } from "./protocol";

export default { title: "MediaBrowserCell" };

const noop = () => {};

const WIDGET: Widget = {
  id: "browser",
  kind: "mediabrowser",
  grid: [0, 0, 4, 2],
};

/** A playing-VLC / paused-Spotify / stopped-mystery trio. The
 * ``desktop_entry`` mapping (vlc → Simple Icons vlcmediaplayer) and
 * the unknown entry's disc-icon fallback both show in this view. The
 * ``app_name`` header (from the MPRIS root ``Identity``) shows on the
 * first two rows; the mystery row leaves it null to exercise the
 * omitted-header path. */
const MIXED: Record<string, MediaReading> = {
  "mpris.vlc": {
    id: "mpris.vlc",
    available: true,
    stale: false,
    playing: true,
    title: "One More Time",
    artist: "Daft Punk",
    app_name: "VLC media player",
    desktop_entry: "vlc",
    can_go_next: true,
    can_go_previous: true,
  },
  "mpris.spotify": {
    id: "mpris.spotify",
    available: true,
    stale: false,
    playing: false,
    title: "Intro",
    artist: "The xx",
    app_name: "Spotify",
    desktop_entry: "spotify",
    can_go_next: true,
    can_go_previous: false,
  },
  "mpris.mystery": {
    id: "mpris.mystery",
    available: true,
    stale: false,
    playing: false,
    title: "Unknown player",
    artist: "No DesktopEntry reported",
    desktop_entry: null,
    can_go_next: false,
    can_go_previous: false,
  },
};

export const PlayingFirst: Story = () => (
  <div style={{ display: "grid", width: 480, height: 360 }}>
    <MediaBrowserCell
      widget={WIDGET}
      states={MIXED}
      onCommand={noop}
    />
  </div>
);

export const Stable: Story = () => (
  <div style={{ display: "grid", width: 480, height: 360 }}>
    <MediaBrowserCell
      widget={{ ...WIDGET, ordering: "stable" }}
      states={MIXED}
      onCommand={noop}
    />
  </div>
);

export const Empty: Story = () => (
  <div style={{ display: "grid", width: 480, height: 360 }}>
    <MediaBrowserCell widget={WIDGET} states={{}} onCommand={noop} />
  </div>
);

export const EmptyHidden: Story = () => (
  <div style={{ display: "grid", width: 480, height: 360 }}>
    <MediaBrowserCell
      widget={{ ...WIDGET, empty_state: "hide" }}
      states={{}}
      onCommand={noop}
    />
  </div>
);
