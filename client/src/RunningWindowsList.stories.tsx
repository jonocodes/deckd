import type { Story } from "@ladle/react";
import { RunningWindowsList } from "./RunningWindowsList";
import type { WindowListEntry } from "./protocol";

export default { title: "RunningWindowsList" };

const noop = () => {};

/** A realistic snapshot: branded rows (Firefox, Slack) carry Simple
 * Icons glyphs; the raw-fallback rows (a terminal, an untitled window)
 * carry ``icon: null`` and render no glyph — honest absence, not a
 * decorative generic icon (issue #120, decision 6). */
const WINDOWS: WindowListEntry[] = [
  { window_id: "1", label: "Firefox", icon: { source: "simple-icons", name: "firefox" } },
  { window_id: "2", label: "Spotify", icon: { source: "simple-icons", name: "spotify" } },
  { window_id: "3", label: "foot", icon: null },
  { window_id: "4", label: "Untitled — Text Editor", icon: null },
];

/** The populated list — one row per open window, MRU-ordered by the
 * daemon. Rows are interactive (raise-on-tap, issue #122); tapping logs
 * via the ``onRowTap`` handler. */
export const Default: Story = () => (
  <div style={{ display: "grid", width: 480, height: 360, border: "1px solid #30363d" }}>
    <RunningWindowsList windows={WINDOWS} onRowTap={noop} />
  </div>
);

/** Empty snapshot — a desktop with no open windows, or the first frame
 * the watcher emits. Renders the explicit "no running programs" message
 * so the view reads as alive, not broken. */
export const Empty: Story = () => (
  <div style={{ display: "grid", width: 480, height: 360, border: "1px solid #30363d" }}>
    <RunningWindowsList windows={[]} onRowTap={noop} />
  </div>
);

/** No snapshot yet (``windows === undefined``): a backend that doesn't
 * advertise the ``watch_windows`` capability (KDE/X11/macOS today, or a
 * daemon whose first frame hasn't landed). Renders the
 * "unsupported on this platform" empty state (issue #120, decision 8). */
export const Unsupported: Story = () => (
  <div style={{ display: "grid", width: 480, height: 360, border: "1px solid #30363d" }}>
    <RunningWindowsList windows={undefined} onRowTap={noop} />
  </div>
);

/** Display-only variant — no ``onRowTap`` handler, so rows render
 * non-interactive (no button role, no raise affordance). Mirrors the
 * v1 pre-#122 behaviour and any read-only embedding. */
export const NonInteractive: Story = () => (
  <div style={{ display: "grid", width: 480, height: 360, border: "1px solid #30363d" }}>
    <RunningWindowsList windows={WINDOWS} />
  </div>
);
