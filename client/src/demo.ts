import type { MediaState, ServerLayout } from "./protocol";

/** Backend-free demo fixtures. Activated with a ``?demo=<name>`` URL param
 * (e.g. ``/?demo=firefox``): the app renders the fixture layout and skips the
 * WebSocket entirely, so the client can be viewed / screenshotted / iterated
 * on without a running daemon. Dev-only affordance; adds no runtime cost when
 * the param is absent. */

const FIREFOX: ServerLayout = {
  type: "layout",
  app: "Firefox (demo)",
  display_name: "Firefox",
  theme: "#ff7139",
  icon: { source: "simple-icons", name: "firefox" },
  jogstrip_enabled: true,
  widgets: [
    { id: "new-tab", kind: "button", label: "New tab", icon: { source: "lucide", name: "plus" }, grid: [0, 0, 1, 1] },
    { id: "new-window", kind: "button", label: "New window", icon: { source: "lucide", name: "app-window" }, grid: [1, 0, 1, 1] },
    { id: "back", kind: "button", label: "Back", icon: { source: "lucide", name: "arrow-left" }, color: "#1e3a8a", grid: [2, 0, 1, 1] },
    { id: "forward", kind: "button", label: "Forward", icon: { source: "lucide", name: "arrow-right" }, color: "#1e3a8a", grid: [3, 0, 1, 1] },
    { id: "reload", kind: "button", label: "Reload", icon: { source: "lucide", name: "refresh-cw" }, grid: [0, 1, 1, 1] },
    { id: "focus-url", kind: "button", label: "URL bar", icon: { source: "lucide", name: "link" }, grid: [1, 1, 1, 1] },
    { id: "find", kind: "button", label: "Find", icon: { source: "lucide", name: "search" }, grid: [2, 1, 1, 1] },
    { id: "close-tab", kind: "button", label: "Close tab", icon: { source: "lucide", name: "x" }, grid: [3, 1, 1, 1] },
  ],
};

const DEFAULT: ServerLayout = {
  type: "layout",
  app: "default (demo)",
  jogstrip_enabled: true,
  widgets: [
    { id: "open-url", kind: "button", label: "Open example.com", icon: { source: "lucide", name: "globe" }, grid: [0, 0, 1, 1] },
    { id: "audio-toggle", kind: "button", label: "VLC Play/Pause", icon: { source: "lucide", name: "play" }, grid: [1, 0, 1, 1] },
    { id: "xterm", kind: "button", label: "xterm", icon: { source: "lucide", name: "terminal" }, grid: [2, 0, 1, 1] },
    { id: "send-key", kind: "button", label: "Send Ctrl+T", icon: { source: "lucide", name: "keyboard" }, grid: [3, 0, 1, 1] },
  ],
};

// Exercises both renderers and edge cases in one view: Lucide glyphs, a
// per-button colour, brand logos via the lazily-loaded Simple Icons set, and
// an intentionally-unknown icon to show the missing-placeholder.
const SHOWCASE: ServerLayout = {
  type: "layout",
  app: "showcase (demo)",
  display_name: "Showcase",
  // A non-brand theme colour so the chrome badge reads themed even without
  // a brand logo, exercising the no-icon themed-badge path.
  theme: "#6d28d9",
  jogstrip_enabled: true,
  widgets: [
    { id: "firefox", kind: "button", label: "Firefox", icon: { source: "simple-icons", name: "firefox" }, color: "#b5651d", grid: [0, 0, 1, 1] },
    { id: "vscode", kind: "button", label: "VS Code", icon: { source: "simple-icons", name: "vscodium" }, color: "#1e3a8a", grid: [1, 0, 1, 1] },
    { id: "signal", kind: "button", label: "Signal", icon: { source: "simple-icons", name: "signal" }, grid: [2, 0, 1, 1] },
    { id: "search", kind: "button", label: "Search", icon: { source: "lucide", name: "search" }, grid: [3, 0, 1, 1] },
    { id: "plain", kind: "button", label: "No icon", grid: [0, 1, 1, 1] },
    { id: "colored", kind: "button", label: "Accent", icon: { source: "lucide", name: "sparkles" }, color: "#6d28d9", grid: [1, 1, 1, 1] },
    { id: "danger", kind: "button", label: "Danger", icon: { source: "lucide", name: "trash-2" }, color: "#7f1d1d", grid: [2, 1, 1, 1] },
    { id: "missing", kind: "button", label: "Missing", icon: { source: "lucide", name: "not-a-real-icon" }, grid: [3, 1, 1, 1] },
  ],
};

// Backend-free meter demo (issue #40). Mirrors what the daemon would
// push for a real CPU%/MEM% source — a couple of realistic values so
// the bar's color-graded fill renders across the spectrum. Wired via
// the meter store's localStorage hydration on mount, so opening
// ``/?demo=meter`` lands in a "fresh layout, pre-populated values"
// state without needing the daemon at all.
const METER: ServerLayout = {
  type: "layout",
  app: "meter (demo)",
  display_name: "Meter demo",
  theme: "#1d4ed8",
  jogstrip_enabled: true,
  widgets: [
    {
      id: "cpu_percent",
      kind: "meter",
      label: "CPU",
      icon: { source: "lucide", name: "cpu" },
      source: "cpu_percent",
      min: 0,
      max: 100,
      grid: [0, 0, 2, 1],
    },
    {
      id: "mem_percent",
      kind: "meter",
      label: "MEM",
      icon: { source: "lucide", name: "memory-stick" },
      source: "mem_percent",
      min: 0,
      max: 100,
      grid: [0, 1, 2, 1],
    },
    { id: "open-url", kind: "button", label: "example.com", icon: { source: "simple-icons", name: "firefox" }, grid: [2, 0, 1, 1] },
    { id: "tilix", kind: "button", label: "Tilix", icon: { source: "lucide", name: "square-terminal" }, grid: [3, 0, 1, 1] },
    { id: "audio-toggle", kind: "button", label: "VLC", icon: { source: "lucide", name: "play" }, grid: [2, 1, 1, 1] },
    // Combined stats cell — reads the same cpu_percent/mem_percent seeds as
    // the bar meters above (readings are keyed by source), so it renders
    // without its own seed entry.
    {
      id: "system",
      kind: "stats",
      label: "System",
      grid: [3, 1, 1, 1],
      metrics: [
        { source: "cpu_percent", label: "CPU" },
        { source: "mem_percent", label: "MEM" },
      ],
    },
  ],
};

// Seed values for the meter demo so the bar renders with realistic
// values on first paint (localStorage hydration, see meter-store.ts).
// These are written into localStorage by the app on first mount when
// the meter demo is selected, and cleared when the user navigates
// away to a non-meter demo. Keeping the seeds in the same file as the
// fixture means a designer iterating on the meter layout doesn't have
// to remember to update two places.
export const METER_DEMO_SEEDS: Record<string, { value: number; unit: string }> = {
  cpu_percent: { value: 58, unit: "%" },
  mem_percent: { value: 41, unit: "%" },
};

// Backend-free VLC media demo. A single full-width media cell, matching the
// shipping ``layouts/vlc.yaml`` footprint, so ``/?demo=vlc`` shows the player
// card in the real app chrome. Its playback state is seeded from
// MEDIA_DEMO_STATES below (App pushes it into the media store on mount).
const VLC: ServerLayout = {
  type: "layout",
  app: "VLC (demo)",
  display_name: "VLC",
  theme: "#ff8c00",
  icon: { source: "simple-icons", name: "vlcmediaplayer" },
  jogstrip_enabled: true,
  widgets: [
    {
      id: "vlc-media",
      kind: "media",
      label: "VLC",
      grid: [0, 0, 4, 2],
      controls: ["play", "previous", "next", "volume", "position", "speed"],
    },
  ],
};

/** Seed readings for the VLC demo, keyed by widget id via ``id``. App pushes
 * these into the media store on mount when a demo layout is active, so the
 * card renders populated (art, metadata, live seek/volume) without a daemon. */
export const MEDIA_DEMO_STATES: MediaState[] = [
  {
    type: "media_state",
    id: "vlc-media",
    available: true,
    stale: false,
    playing: true,
    position: 73,
    duration: 225,
    volume: 65,
    rate: 1,
    title: "One More Time",
    artist: "Daft Punk",
    album: "Discovery",
    art_token: "id:demo",
  },
];

const DEMOS: Record<string, ServerLayout> = {
  firefox: FIREFOX,
  default: DEFAULT,
  showcase: SHOWCASE,
  meter: METER,
  vlc: VLC,
};

type DemoView = "layout" | "trackpad" | "settings";

// Demo names that open a chrome *view* (settings / trackpad) rather than a
// bare layout. They render over a base fixture so the socket stays disabled
// and the app chrome (badge, status) has real context behind the panel.
const DEMO_VIEWS: Record<string, DemoView> = {
  settings: "settings",
  trackpad: "trackpad",
};
const VIEW_DEMO_BASE = VLC;

/** The demo fixtures, keyed by name — for the gallery and Ladle stories. */
export const DEMO_LAYOUTS = DEMOS;

/** Names of the available demo pages, for the demo gallery selector — the
 * layout fixtures plus the settings / trackpad view demos. */
export const DEMO_NAMES = [...Object.keys(DEMOS), ...Object.keys(DEMO_VIEWS)];

/** Returns the demo layout named by the ``?demo=`` URL param, or ``null``
 * when the param is absent/unknown (normal daemon-backed operation). A view
 * demo (``settings`` / ``trackpad``) renders over a shared base fixture. */
export function getDemoLayout(): ServerLayout | null {
  if (typeof window === "undefined") return null;
  const name = new URLSearchParams(window.location.search).get("demo");
  if (!name) return null;
  if (name in DEMO_VIEWS) return VIEW_DEMO_BASE;
  return DEMOS[name] ?? null;
}

/** The initial chrome view for the current ``?demo=`` param — ``settings`` or
 * ``trackpad`` for the view demos, otherwise ``layout``. */
export function getDemoView(): DemoView {
  if (typeof window === "undefined") return "layout";
  const name = new URLSearchParams(window.location.search).get("demo");
  return (name && DEMO_VIEWS[name]) || "layout";
}
