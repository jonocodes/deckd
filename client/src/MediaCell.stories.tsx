import type { Story } from "@ladle/react";
import { MediaCell } from "./MediaCell";
import type { MediaReading } from "./media-store";
import type { Widget } from "./protocol";

export default { title: "MediaCell" };

const noop = () => {};

const WIDGET: Widget = {
  id: "vlc-media",
  kind: "media",
  label: "VLC",
  grid: [0, 0, 4, 2],
  controls: ["play", "previous", "next", "volume", "position", "speed"],
};

const PLAYING: MediaReading = {
  id: "vlc-media",
  available: true,
  stale: false,
  playing: true,
  position: 73,
  duration: 225,
  volume: 65,
  rate: 1,
  title: "Midnight City",
  artist: "M83",
  album: "Hurry Up, We're Dreaming",
};

/** The full VLC card (art, metadata, seek, transport, volume, speed). */
export const Full: Story = () => (
  <div style={{ width: 420, height: 560 }}>
    <MediaCell widget={WIDGET} state={PLAYING} onPress={noop} onCommand={noop} />
  </div>
);

/** With real cover art: the art slot fetches ``/media/<id>/art`` (served by
 * the daemon's proxy). Here ``art_token`` is set so the <img> renders. */
export const WithArt: Story = () => (
  <div style={{ width: 420, height: 560 }}>
    <MediaCell
      widget={WIDGET}
      state={{
        ...PLAYING,
        title: "One More Time",
        artist: "Daft Punk",
        album: "Discovery",
        art_token: "id:demo",
      }}
      onPress={noop}
      onCommand={noop}
    />
  </div>
);

/** A wider, shorter slot — matches the default 4x2 grid footprint. */
export const Wide: Story = () => (
  <div style={{ width: 640, height: 360 }}>
    <MediaCell widget={WIDGET} state={PLAYING} onPress={noop} onCommand={noop} />
  </div>
);

/** Nothing playing / VLC unreachable — dashed, dimmed, placeholders. */
export const Unavailable: Story = () => (
  <div style={{ width: 420, height: 560 }}>
    <MediaCell widget={WIDGET} state={null} onPress={noop} onCommand={noop} />
  </div>
);
