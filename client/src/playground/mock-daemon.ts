/* Playground (#149/#151/#152): an in-browser stand-in for the Python daemon.
 *
 * The frontend can't tell a real WebSocket-backed daemon from this: it
 * speaks the same wire protocol — emitting real ``ServerMessage``s and
 * accepting real ``ClientMessage``s — through the exact callback surface
 * ``useDeckdSocket`` exposes. Everything downstream (ButtonGrid, MediaCell,
 * the running-windows list, the meter / media stores) is the real UI.
 *
 * Several virtual apps run at once, each ticking on one clock. Switching
 * between them reuses the *production* affordance: the running-programs
 * chrome list. Tapping a row sends ``raise_window`` (as a real client does),
 * and the mock — like the daemon's focus watcher — resolves the newly
 * focused app and pushes its layout. Background apps keep ticking, so the
 * music plays on (and the chrome media dot stays lit) while you're on
 * another deck.
 *
 * Determinism is kept where it's cheap (fixed tick dt, no wall-clock / RNG)
 * so this can later double as a test fixture (epic #157, foundation #150).
 */
import type {
  ClientMessage,
  Icon,
  MediaState,
  ServerChromeMedia,
  ServerLayout,
  ServerRunningWindows,
  ServerWidgetUpdate,
} from "../protocol";

/** The frames a virtual app can push. A strict subset of ``ServerMessage``,
 * discriminated by ``type`` so the daemon can route each to its callback. */
type AppFrame = ServerLayout | MediaState | ServerWidgetUpdate | ServerChromeMedia;

/** The callback surface the daemon emits into — the frames this Playground
 * produces, mapped onto ``useDeckdSocket``'s handlers. */
export type DaemonEmit = {
  onLayout: (m: ServerLayout) => void;
  onMediaState: (m: MediaState) => void;
  onWidgetUpdate: (m: ServerWidgetUpdate) => void;
  onChromeMedia?: (m: ServerChromeMedia) => void;
  onRunningWindows?: (m: ServerRunningWindows) => void;
};

/** A running virtual app: it owns a layout, holds state, ticks on the clock,
 * and reacts to client messages by returning frames to emit. */
interface VirtualApp {
  readonly id: string;
  readonly windowLabel: string;
  readonly icon: Icon | null;
  /** The deck this app shows when focused. */
  layout(): ServerLayout;
  /** Frames to (re)establish this app's state — emitted at start and on focus. */
  initialFrames(): AppFrame[];
  /** Advance ``dt`` seconds; return any frames produced (deterministic). */
  tick(dt: number): AppFrame[];
  /** React to a client message addressed to this app; return frames. */
  handle(msg: ClientMessage): AppFrame[];
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, value));
}

// -- Music: a media-cell app that keeps playing in the background ----------

const MUSIC_MEDIA_ID = "music-media";

type Track = { title: string; artist: string; album: string; duration: number };
const TRACKLIST: Track[] = [
  { title: "Neon Meadow", artist: "The Placeholders", album: "Fixtures", duration: 214 },
  { title: "Deterministic Dreams", artist: "Mock Ensemble", album: "Fixtures", duration: 187 },
  { title: "Idle Loop", artist: "Virtual Sons", album: "Fixtures", duration: 245 },
];

class MusicApp implements VirtualApp {
  readonly id = "music";
  readonly windowLabel = "Music";
  readonly icon: Icon = { source: "lucide", name: "music" };

  private index = 0;
  private position = 42; // start mid-track so the bar is visibly progressing
  private playing = true;
  private volume = 65;
  private rate = 1;
  private lastPlaying = true;

  private get track(): Track {
    return TRACKLIST[this.index];
  }

  layout(): ServerLayout {
    return {
      type: "layout",
      app: "Music",
      display_name: "Music",
      theme: "#22c55e",
      icon: this.icon,
      jogstrip_enabled: true,
      widgets: [
        {
          id: MUSIC_MEDIA_ID,
          kind: "media",
          label: "Now playing",
          size: [4, 2],
          controls: ["play", "previous", "next", "volume", "position", "speed"],
          media_http: {},
        },
      ],
    };
  }

  initialFrames(): AppFrame[] {
    this.lastPlaying = this.playing;
    return [this.mediaFrame(), this.chromeFrame()];
  }

  tick(dt: number): AppFrame[] {
    if (!this.playing) return [];
    this.position += dt * this.rate;
    if (this.position >= this.track.duration) this.next();
    return [this.mediaFrame()];
  }

  handle(msg: ClientMessage): AppFrame[] {
    if (msg.type === "press") {
      if (msg.id === MUSIC_MEDIA_ID) return this.togglePlay();
      if (msg.id === `${MUSIC_MEDIA_ID}:previous`) return this.previous();
      if (msg.id === `${MUSIC_MEDIA_ID}:next`) { this.next(); return [this.mediaFrame()]; }
      return [];
    }
    if (msg.type === "media_command") {
      if (msg.value == null) return [];
      if (msg.command === "seek") this.position = clamp(msg.value, 0, this.track.duration);
      else if (msg.command === "volume") this.volume = clamp(msg.value, 0, 100);
      else if (msg.command === "rate") this.rate = Math.max(0.25, msg.value);
      else return [];
      return [this.mediaFrame()];
    }
    return [];
  }

  private togglePlay(): AppFrame[] {
    this.playing = !this.playing;
    const frames: AppFrame[] = [this.mediaFrame()];
    if (this.playing !== this.lastPlaying) {
      this.lastPlaying = this.playing;
      frames.push(this.chromeFrame());
    }
    return frames;
  }

  private previous(): AppFrame[] {
    if (this.position > 3) this.position = 0;
    else {
      this.index = (this.index - 1 + TRACKLIST.length) % TRACKLIST.length;
      this.position = 0;
    }
    return [this.mediaFrame()];
  }

  private next(): void {
    this.index = (this.index + 1) % TRACKLIST.length;
    this.position = 0;
  }

  private mediaFrame(): MediaState {
    return {
      type: "media_state",
      id: MUSIC_MEDIA_ID,
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

  private chromeFrame(): ServerChromeMedia {
    return {
      type: "chrome_media",
      available: true,
      playing: this.playing,
      playing_count: this.playing ? 1 : 0,
      supported: true,
    };
  }
}

// -- Lights: buttons that drive a live meter (visible press feedback) ------

class LightsApp implements VirtualApp {
  readonly id = "lights";
  readonly windowLabel = "Lights";
  readonly icon: Icon = { source: "lucide", name: "lightbulb" };

  private brightness = 60;

  layout(): ServerLayout {
    return {
      type: "layout",
      app: "Lights",
      display_name: "Lights",
      theme: "#f59e0b",
      icon: this.icon,
      jogstrip_enabled: true,
      widgets: [
        { id: "brightness", kind: "meter", label: "Brightness", icon: { source: "lucide", name: "sun" }, source: "brightness", min: 0, max: 100, size: [4, 1] },
        { id: "brighter", kind: "button", label: "Brighter", icon: { source: "lucide", name: "plus" } },
        { id: "dimmer", kind: "button", label: "Dimmer", icon: { source: "lucide", name: "minus" } },
        { id: "warm", kind: "button", label: "Warm", icon: { source: "lucide", name: "flame" }, color: "#b45309" },
        { id: "cool", kind: "button", label: "Cool", icon: { source: "lucide", name: "snowflake" }, color: "#1e3a8a" },
        { id: "off", kind: "button", label: "Off", icon: { source: "lucide", name: "power" }, color: "#7f1d1d" },
      ],
    };
  }

  initialFrames(): AppFrame[] {
    return [this.frame()];
  }

  tick(): AppFrame[] {
    return [];
  }

  handle(msg: ClientMessage): AppFrame[] {
    if (msg.type !== "press") return [];
    if (msg.id === "brighter") this.brightness = clamp(this.brightness + 10, 0, 100);
    else if (msg.id === "dimmer") this.brightness = clamp(this.brightness - 10, 0, 100);
    else if (msg.id === "off") this.brightness = 0;
    else return []; // warm / cool: colour presets, no brightness change
    return [this.frame()];
  }

  private frame(): ServerWidgetUpdate {
    return { type: "widget_update", id: "brightness", source: "brightness", value: this.brightness, unit: "%" };
  }
}

// -- Browser: a button-only app (breadth: a plain key-sending deck) ---------

class BrowserApp implements VirtualApp {
  readonly id = "browser";
  readonly windowLabel = "Firefox";
  readonly icon: Icon = { source: "simple-icons", name: "firefox" };

  layout(): ServerLayout {
    return {
      type: "layout",
      app: "Firefox",
      display_name: "Firefox",
      theme: "#ff7139",
      icon: this.icon,
      jogstrip_enabled: true,
      widgets: [
        { id: "new-tab", kind: "button", label: "New tab", icon: { source: "lucide", name: "plus" }, action: { key: "ctrl+t" } },
        { id: "back", kind: "button", label: "Back", icon: { source: "lucide", name: "arrow-left" }, color: "#1e3a8a", action: { key: "alt+left" } },
        { id: "forward", kind: "button", label: "Forward", icon: { source: "lucide", name: "arrow-right" }, color: "#1e3a8a", action: { key: "alt+right" } },
        { id: "reload", kind: "button", label: "Reload", icon: { source: "lucide", name: "refresh-cw" }, action: { key: "ctrl+r" } },
        { id: "find", kind: "button", label: "Find", icon: { source: "lucide", name: "search" }, action: { key: "ctrl+f" } },
        { id: "close-tab", kind: "button", label: "Close tab", icon: { source: "lucide", name: "x" }, action: { key: "ctrl+w" } },
      ],
    };
  }

  initialFrames(): AppFrame[] {
    return [];
  }

  tick(): AppFrame[] {
    return [];
  }

  handle(): AppFrame[] {
    return [];
  }
}

const TICK_MS = 250;
const TICK_DT = TICK_MS / 1000;

/** The virtual backend. ``start`` pushes the focused app's layout + every
 * app's initial state and begins the clock; ``send`` accepts client messages
 * (presses, media commands, and ``raise_window`` app-switches); ``stop``
 * tears the clock down. */
export class MockDaemon {
  private apps: VirtualApp[];
  // MRU order; the front element is the focused app (matches the daemon's
  // most-recently-used running-windows ordering).
  private order: string[];
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(private emit: DaemonEmit) {
    this.apps = [new MusicApp(), new LightsApp(), new BrowserApp()];
    this.order = this.apps.map((a) => a.id);
  }

  private get current(): VirtualApp {
    return this.byId(this.order[0]);
  }

  private byId(id: string): VirtualApp {
    const app = this.apps.find((a) => a.id === id);
    if (!app) throw new Error(`unknown virtual app: ${id}`);
    return app;
  }

  start(): void {
    this.emitFrame(this.current.layout());
    this.emitRunningWindows();
    // Seed every app's state, not just the focused one, so a background app
    // (the music player) is already live the moment you switch to it.
    for (const app of this.apps) app.initialFrames().forEach((f) => this.emitFrame(f));
    this.timer = setInterval(() => {
      for (const app of this.apps) app.tick(TICK_DT).forEach((f) => this.emitFrame(f));
    }, TICK_MS);
  }

  stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  send(msg: ClientMessage): void {
    // Tapping a running-programs row raises that window; the daemon reacts to
    // the focus change by pushing the newly focused app's layout.
    if (msg.type === "raise_window") {
      this.focus(msg.window_id);
      return;
    }
    // A view close (Escape / clear) re-pushes the focused-app layout.
    if (msg.type === "clear_view") {
      this.emitFrame(this.current.layout());
      return;
    }
    // Chrome views (windows / nowplaying / editor) are client-local in the
    // Playground — the client owns that routing; nothing to push here.
    if (msg.type === "select_view") return;
    // Everything else (press, media_command, …) goes to the focused app.
    this.current.handle(msg).forEach((f) => this.emitFrame(f));
  }

  private focus(id: string): void {
    if (!this.apps.some((a) => a.id === id)) return;
    this.order = [id, ...this.order.filter((x) => x !== id)];
    this.emitFrame(this.current.layout());
    this.current.initialFrames().forEach((f) => this.emitFrame(f));
    this.emitRunningWindows();
  }

  private emitRunningWindows(): void {
    const windows = this.order.map((id) => {
      const app = this.byId(id);
      return { window_id: app.id, label: app.windowLabel, icon: app.icon };
    });
    this.emit.onRunningWindows?.({ type: "running_windows", windows });
  }

  private emitFrame(frame: AppFrame): void {
    switch (frame.type) {
      case "layout":
        this.emit.onLayout(frame);
        break;
      case "media_state":
        this.emit.onMediaState(frame);
        break;
      case "widget_update":
        this.emit.onWidgetUpdate(frame);
        break;
      case "chrome_media":
        this.emit.onChromeMedia?.(frame);
        break;
    }
  }
}
