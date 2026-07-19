import type { ServerLayout } from "./protocol";

/** Backend-free demo fixtures. Activated with a ``?demo=<name>`` URL param
 * (e.g. ``/?demo=firefox``): the app renders the fixture layout and skips the
 * WebSocket entirely, so the client can be viewed / screenshotted / iterated
 * on without a running daemon. Dev-only affordance; adds no runtime cost when
 * the param is absent. */

const FIREFOX: ServerLayout = {
  type: "layout",
  app: "Firefox (demo)",
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

const DEMOS: Record<string, ServerLayout> = {
  firefox: FIREFOX,
  default: DEFAULT,
  showcase: SHOWCASE,
};

/** The demo fixtures, keyed by name — for the gallery and Ladle stories. */
export const DEMO_LAYOUTS = DEMOS;

/** Names of the available demo fixtures, for the demo gallery selector. */
export const DEMO_NAMES = Object.keys(DEMOS);

/** Returns the demo layout named by the ``?demo=`` URL param, or ``null``
 * when the param is absent/unknown (normal daemon-backed operation). */
export function getDemoLayout(): ServerLayout | null {
  if (typeof window === "undefined") return null;
  const name = new URLSearchParams(window.location.search).get("demo");
  if (!name) return null;
  return DEMOS[name] ?? null;
}
