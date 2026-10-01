/** Playground app-switcher strip (#152).
 *
 * A browser has no OS focus, so the Playground needs its own trigger to
 * say "this app is frontmost now" — the one affordance with no
 * real-world analog. This is that trigger: one chip per app in the
 * MockDaemon's roster (the ``running_windows`` frame), the focused one
 * pressed. A tap reports the window id up; App echoes it as a real
 * ``raise_window`` and the mock — like the daemon's focus watcher —
 * resolves that app and pushes its deck, so the grid, badge, theme and
 * icon all update with no special-casing.
 *
 * The roster is MRU-ordered (protocol ``running_windows`` contract), so
 * the front entry is the focused app — no separate focused-id prop.
 */
import type { ServerWindowListEntry } from "../protocol";
import { Icon } from "../Icon";

export type PlaygroundAppSwitcherProps = {
  /** The mock's app roster, MRU-ordered (front = focused). */
  apps: ServerWindowListEntry[];
  /** Report the tapped app's window id upward. */
  onSelect: (windowId: string) => void;
};

export function PlaygroundAppSwitcher({ apps, onSelect }: PlaygroundAppSwitcherProps) {
  if (apps.length === 0) return null;
  const focusedId = apps[0].window_id;
  return (
    <div className="playground-switcher" role="group" aria-label="switch app">
      {apps.map((app) => {
        const active = app.window_id === focusedId;
        return (
          <button
            key={app.window_id}
            type="button"
            className={`playground-switcher-chip${active ? " playground-switcher-chip-active" : ""}`}
            data-app-id={app.window_id}
            aria-pressed={active}
            onClick={() => onSelect(app.window_id)}
          >
            {app.icon ? <Icon icon={app.icon} className="playground-switcher-icon" /> : null}
            <span className="playground-switcher-label">{app.label}</span>
          </button>
        );
      })}
    </div>
  );
}
