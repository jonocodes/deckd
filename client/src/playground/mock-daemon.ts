/* Playground spike (#149): an in-browser stand-in for the Python daemon.
 *
 * The frontend can't tell a real WebSocket-backed daemon from this: it
 * speaks the same wire protocol — emitting real ``ServerMessage``s and
 * accepting real ``ClientMessage``s — through the exact callback surface
 * ``useDeckdSocket`` exposes. Everything downstream (ButtonGrid, MediaCell,
 * the media store) is the real UI, unchanged.
 *
 * This is throwaway spike code to answer one question: does the
 * press→feedback loop feel alive? It deliberately ships one virtual app
 * (a music player). Determinism is kept where it's cheap (fixed tick dt,
 * no wall-clock / RNG) so this can later double as a test fixture — see
 * the epic (#157) foundation issue (#150).
 */
import type {
  ClientMessage,
  MediaState,
  ServerChromeMedia,
  ServerLayout,
} from "../protocol";

/** The one media widget id the playground drives. */
export const PLAYGROUND_MEDIA_ID = "playground-media";

/** The callback surface the daemon emits into — a strict subset of
 * ``useDeckdSocket``'s params, namely the frames this spike produces. */
export type DaemonEmit = {
  onLayout: (m: ServerLayout) => void;
  onMediaState: (m: MediaState) => void;
  onChromeMedia?: (m: ServerChromeMedia) => void;
};

/** Fictional tracks — no real artists/albums, so the public page carries
 * no third-party branding (epic #157, asset-licensing note). */
type Track = { title: string; artist: string; album: string; duration: number };
const TRACKLIST: Track[] = [
  { title: "Neon Meadow", artist: "The Placeholders", album: "Fixtures", duration: 214 },
  { title: "Deterministic Dreams", artist: "Mock Ensemble", album: "Fixtures", duration: 187 },
  { title: "Idle Loop", artist: "Virtual Sons", album: "Fixtures", duration: 245 },
];

/** The playground's single layout: a full-width media cell so the moving
 * progress bar (the "it's alive" signal) is front and centre. ``media_http``
 * is present so the volume control renders as a live slider rather than the
 * action-gated +/- fallback. */
const PLAYGROUND_LAYOUT: ServerLayout = {
  type: "layout",
  app: "Playground",
  display_name: "Playground",
  theme: "#22c55e",
  icon: { source: "lucide", name: "music" },
  jogstrip_enabled: true,
  widgets: [
    {
      id: PLAYGROUND_MEDIA_ID,
      kind: "media",
      label: "Now playing",
      size: [4, 2],
      controls: ["play", "previous", "next", "volume", "position", "speed"],
      media_http: {},
    },
  ],
};

/** A stateful, ticking virtual music player. Holds playback state, advances
 * on a fixed dt, and renders itself as a wire ``MediaState``. */
class VirtualMusicApp {
  private index = 0;
  private position = 42; // start mid-track so the bar is visibly progressing
  private playing = true;
  private volume = 65;
  private rate = 1;

  private get track(): Track {
    return TRACKLIST[this.index];
  }

  /** Advance playback by ``dt`` seconds; wrap to the next track at the end. */
  tick(dt: number): void {
    if (!this.playing) return;
    this.position += dt * this.rate;
    if (this.position >= this.track.duration) {
      this.next();
    }
  }

  playPause(): void {
    this.playing = !this.playing;
  }

  next(): void {
    this.index = (this.index + 1) % TRACKLIST.length;
    this.position = 0;
  }

  previous(): void {
    // Common player idiom: restart the track unless already near the top.
    if (this.position > 3) {
      this.position = 0;
      return;
    }
    this.index = (this.index - 1 + TRACKLIST.length) % TRACKLIST.length;
    this.position = 0;
  }

  seek(seconds: number): void {
    this.position = clamp(seconds, 0, this.track.duration);
  }

  setVolume(value: number): void {
    this.volume = clamp(value, 0, 100);
  }

  setRate(value: number): void {
    this.rate = Math.max(0.25, value);
  }

  isPlaying(): boolean {
    return this.playing;
  }

  /** Render current state as the frame a real daemon would push. */
  snapshot(): MediaState {
    return {
      type: "media_state",
      id: PLAYGROUND_MEDIA_ID,
      available: true,
      stale: false,
      playing: this.playing,
      position: Math.floor(this.position),
      duration: this.track.duration,
      volume: this.volume,
      rate: this.rate,
      title: this.track.title,
      artist: this.track.artist,
      album: this.track.album,
    };
  }
}

const TICK_MS = 250;
const TICK_DT = TICK_MS / 1000;

/** The virtual backend. ``start`` pushes the initial layout + state and
 * begins the clock; ``send`` accepts client messages and reacts; ``stop``
 * tears the clock down. */
export class MockDaemon {
  private app = new VirtualMusicApp();
  private timer: ReturnType<typeof setInterval> | null = null;
  private lastPlaying: boolean;

  constructor(private emit: DaemonEmit) {
    this.lastPlaying = this.app.isPlaying();
  }

  start(): void {
    this.emit.onLayout(PLAYGROUND_LAYOUT);
    this.emit.onMediaState(this.app.snapshot());
    this.emitChromeMedia();
    this.timer = setInterval(() => {
      this.app.tick(TICK_DT);
      this.emit.onMediaState(this.app.snapshot());
      this.emitChromeMediaIfChanged();
    }, TICK_MS);
  }

  stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  send(msg: ClientMessage): void {
    switch (msg.type) {
      case "press":
        if (msg.id === PLAYGROUND_MEDIA_ID) this.app.playPause();
        else if (msg.id === `${PLAYGROUND_MEDIA_ID}:previous`) this.app.previous();
        else if (msg.id === `${PLAYGROUND_MEDIA_ID}:next`) this.app.next();
        else return; // other presses are no-ops in this spike
        break;
      case "media_command":
        if (msg.value == null) return;
        if (msg.command === "seek") this.app.seek(msg.value);
        else if (msg.command === "volume") this.app.setVolume(msg.value);
        else if (msg.command === "rate") this.app.setRate(msg.value);
        else return;
        break;
      default:
        return; // jog/pad/type/key/view frames: not modelled in this spike
    }
    // Echo new state immediately so the press feels instant, not tick-delayed.
    this.emit.onMediaState(this.app.snapshot());
    this.emitChromeMediaIfChanged();
  }

  private emitChromeMedia(): void {
    const playing = this.app.isPlaying();
    this.lastPlaying = playing;
    const frame: ServerChromeMedia = {
      type: "chrome_media",
      available: true,
      playing,
      playing_count: playing ? 1 : 0,
      supported: true,
    };
    this.emit.onChromeMedia?.(frame);
  }

  private emitChromeMediaIfChanged(): void {
    if (this.app.isPlaying() !== this.lastPlaying) this.emitChromeMedia();
  }
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value));
}
