/** Running-windows chrome list (issues #116 / #120 / #126).
 *
 * Renders one row per currently-open window, label + optional icon.
 * The list lives in its own chrome view (``WINDOWS_VIEW_ID``) — a new
 * tap target in the persistent chrome strip, parallel to the media
 * browser and layout editor views. Display only in v1: tapping a row
 * does not yet raise the window; that's stage 3 (#122), wired as a
 * no-op placeholder here so the round-trip stays observable when the
 * daemon-side raise message lands.
 *
 * Three observable shapes:
 *  1. ``windows`` is undefined — the daemon hasn't pushed a snapshot
 *     yet. The list renders an "unsupported on this platform" empty
 *     state (mirrors the now-playing surface's "Nothing playing"
 *     placeholder,
 *     issue #120 decision 8).
 *  2. ``windows`` is an empty list — a desktop with no open windows
 *     or the very first frame the watcher emits. The list renders an
 *     explicit "no running programs" message so the user knows the
 *     view is alive, not broken.
 *  3. ``windows`` is non-empty — one row per window. The label is the
 *     daemon-derived display string (matched layout's display_name,
 *     else a raw identity fallback); the icon, when present, rides
 *     alongside the label as a 28px glyph. Default-fallback rows
 *     (icon=null on the wire) render a muted generic window glyph as a
 *     placeholder — this supersedes issue #120's decision 6 ("render
 *     nothing"), whose empty icon slot both truncated the label (it
 *     fell into the 32px icon grid column) and left unbranded programs
 *     with no visual anchor.
 */
import type { ServerWindowListEntry } from "./protocol";
import { Icon } from "./Icon";

export type RunningWindowsListProps = {
  /** The current windows snapshot, or ``undefined`` while the daemon's
   *  first ``running_windows`` frame is in flight. */
  windows: ServerWindowListEntry[] | undefined;
  /** Per-row tap handler — wired but ignored in v1; stage 3 (#122)
   *  will replace this with a real raise message. */
  onRowTap?: (windowId: string) => void;
};

export function RunningWindowsList({ windows, onRowTap }: RunningWindowsListProps) {
  if (windows === undefined) {
    return (
      <div className="windows" role="region" aria-label="running programs">
        <div className="windows-empty">running programs: unsupported on this platform</div>
      </div>
    );
  }
  if (windows.length === 0) {
    return (
      <div className="windows" role="region" aria-label="running programs">
        <div className="windows-empty">no running programs</div>
      </div>
    );
  }
  return (
    <div className="windows" role="region" aria-label="running programs">
      <ul className="windows-list">
        {windows.map((entry) => (
          <RunningWindowRow
            key={entry.window_id}
            entry={entry}
            onTap={onRowTap ? () => onRowTap(entry.window_id) : undefined}
          />
        ))}
      </ul>
    </div>
  );
}

function RunningWindowRow({
  entry,
  onTap,
}: {
  entry: ServerWindowListEntry;
  onTap?: () => void;
}) {
  const icon = entry.icon ?? undefined;
  const interactive = Boolean(onTap);
  return (
    <li
      className={`windows-row${interactive ? " windows-row-interactive" : ""}`}
      data-window-id={entry.window_id}
      onClick={onTap}
      onKeyDown={
        onTap
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onTap();
              }
            }
          : undefined
      }
      tabIndex={interactive ? 0 : undefined}
      role={interactive ? "button" : undefined}
      aria-label={interactive ? `raise ${entry.label}` : undefined}
    >
      {icon ? (
        <Icon icon={icon} className="windows-row-icon" />
      ) : (
        // Default-fallback rows (``icon: null`` on the wire) get a
        // neutral placeholder glyph in the icon slot. This supersedes
        // the original "render nothing" choice (issue #120 decision 6):
        // an empty icon slot left the label as the first grid child, so
        // it landed in the 32px icon column and got truncated to a few
        // characters. A muted generic window glyph keeps every row's
        // label aligned in the wide column and gives unbranded programs
        // a visual anchor — it reads as "a program we couldn't brand",
        // not a claim that all such windows are the same app.
        <Icon
          icon={{ source: "lucide", name: "app-window" }}
          className="windows-row-icon windows-row-icon-fallback"
        />
      )}
      <span className="windows-row-label">{entry.label}</span>
    </li>
  );
}