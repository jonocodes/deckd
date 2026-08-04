# GNOME Shell window enumeration & activation APIs (issue #118)

Research for the running-windows switcher map (#116): what a GNOME Shell
extension can use to (a) enumerate open windows with stable identities,
(b) get open/close/title-change signals, and (c) activate/raise a window —
and how fragile those APIs are across shell versions.

Date: 2026-08-04. Primary sources: gjs-docs.gnome.org (Meta/Shell 17 ≈ GNOME 48-era),
gjs.guide, gnome-shell `js/ui/main.js` on GNOME GitLab, and the Window Calls
extension source (github.com/ickyicky/window-calls).

## (a) Enumeration & identity

Extensions run in-process in the shell (GJS) and get the mutter/shell API
directly via the `global` object.

- **`global.get_window_actors()`** — returns every `Meta.WindowActor`; each has
  `.meta_window` (a `Meta.Window`). This is what Window Calls uses for `List()`.
  There is also `Meta.Display.list_all_windows()` and
  `display.get_tab_list(Meta.TabList.NORMAL, null)` for a pre-filtered,
  MRU-ordered "app windows" list (skips docks/OSDs).
  Source: https://gjs-docs.gnome.org/meta17~17/meta.display
- **Identity on `Meta.Window`** (https://gjs-docs.gnome.org/meta17~17/meta.window):
  - `get_id()` — numeric id, unique for the lifetime of the compositor; the
    stable handle Window Calls keys every D-Bus method on. `get_stable_sequence()`
    is a monotonic creation counter (good for stable ordering).
  - `get_wm_class()` / `get_wm_class_instance()` — WM_CLASS (X11) or the
    Wayland app-id mapped into wm_class by mutter.
  - `get_gtk_application_id()` — set only for GTK apps that register with
    `GApplication` (may be null; deckd's focus extension already treats it as
    nullable).
  - `get_sandboxed_app_id()` — Flatpak/Snap app id; the most reliable identity
    for sandboxed apps where wm_class can be arbitrary.
  - `get_title()`, `get_pid()`, `get_workspace()` (→ `Meta.Workspace`,
    `.index()` for the number).
- **`Shell.WindowTracker.get_default().get_window_app(win)`** — maps a window to
  a `Shell.App`; `app.get_id()` returns the `.desktop` file id, which is the
  best cross-session-stable identity when a desktop file exists. It uses
  heuristics internally — per `src/shell-window-tracker.c` the priority order
  is: sandboxed app id → GTK application id → WM_CLASS (StartupWMClass, then
  desktop files by instance, then class) → PID → startup-notification id →
  X11 window group → synthetic fallback app — so it is strictly better than
  hand-rolling wm_class matching.
  Source: https://gitlab.gnome.org/GNOME/gnome-shell/-/blob/main/src/shell-window-tracker.c
  `Shell.AppSystem.get_default().get_running()` enumerates running `Shell.App`s
  (grouped by app, not by window; each app has `get_windows()`).
  Source: https://gjs-docs.gnome.org/shell17~17/ (Shell.WindowTracker, Shell.AppSystem)

Practical identity tuple for deckd: `{id: get_id(), app: WindowTracker desktop
id, wm_class, sandboxed_app_id, title, workspace_index, pid}` — with `get_id()`
as the raise handle and the desktop-id/wm_class as the display/matching key.

## (b) Signals

- **Open:** `Meta.Display::window-created` (`global.display.connect('window-created',
  (display, win) => …)`). Fires for all window types; filter on
  `win.get_window_type() === Meta.WindowType.NORMAL`. Title/wm_class may still
  be empty at creation time — connect `notify::title` / `notify::wm-class` on
  the new window and (for Wayland xdg-shell) wait for first commit.
- **Close:** `Meta.Window::unmanaging` (early, window still valid) and
  `::unmanaged` (final). Per-window connection made at `window-created` time.
- **Title change:** `Meta.Window::notify::title` (GObject property notify);
  similarly `notify::wm-class`, `::workspace-changed`.
- **Focus:** `Meta.Display::notify::focus-window` — already used by deckd's
  extension (`packaging/gnome-shell/deckd-focus@local/extension.js:32`).
- Coarser alternative: `Shell.WindowTracker::tracked-windows-changed` and
  `Shell.AppSystem::app-state-changed` if only app-level granularity is needed.

Sources: https://gjs-docs.gnome.org/meta17~17/meta.display,
https://gjs-docs.gnome.org/meta17~17/meta.window

## (c) Activation / raising

- **`Main.activateWindow(window, time, workspaceNum)`** (gnome-shell
  `js/ui/main.js`, https://gitlab.gnome.org/GNOME/gnome-shell/-/blob/main/js/ui/main.js)
  is the canonical helper: defaults `time` to `global.get_current_time()`,
  and if the window is on another workspace calls
  `workspace.activate_with_focus(window, time)`, else `window.activate(time)`;
  also hides the overview. This is what a switcher should call.
- Lower level: `Meta.Window.activate(timestamp)`,
  `activate_with_workspace(timestamp, workspace)`, `raise()` (stacking only, no
  focus). Passing timestamp `0` (as Window Calls does via
  `workspace.activate_with_focus(win, 0)`) works because in-process calls
  aren't subject to focus-stealing prevention the way external clients are;
  using `global.get_current_time()` is the documented-correct form.

## Wayland constraints

- On Wayland there is **no external protocol** in GNOME for enumerating or
  activating arbitrary windows: GNOME implements neither wlr-foreign-toplevel
  nor ext-foreign-toplevel-list for third parties, and xdg-activation requires
  a token handed to a specific client. An in-shell extension exporting D-Bus is
  the only sanctioned path — exactly deckd's current architecture.
- **`org.gnome.Shell.Eval` is locked down since GNOME 41**: private shell D-Bus
  APIs are restricted to allowlisted callers unless `unsafe-mode` is enabled
  (mutter MetaContext). So "just Eval JS over D-Bus" is not viable; a real
  extension is required. Sources: https://extensions.gnome.org/review/26639,
  https://github.com/linushdot/unsafe-mode-menu
- **`org.gnome.Shell.Introspect`** (`GetWindows()` + `WindowsChanged` signal;
  added in gnome-shell MR !326) exists but the shell checks the D-Bus sender
  against an allowlist (the XDG desktop portals) or requires unsafe mode, and
  it gives no activation; not usable by deckd without unsafe-mode.
  Sources: https://gitlab.gnome.org/GNOME/gnome-shell/-/merge_requests/326,
  https://gitlab.gnome.org/GNOME/gnome-shell/-/blob/main/data/dbus-interfaces/org.gnome.Shell.Introspect.xml,
  https://discourse.gnome.org/t/unable-to-call-the-remote-getwindows-gnome-method-via-dbus/21201

## Prior art: Window Calls (github.com/ickyicky/window-calls)

Exports `org.gnome.Shell.Extensions.Windows` at
`/org/gnome/Shell/Extensions/Windows` with ~18 methods: `List()` (JSON array of
`{id, wm_class, wm_class_instance, pid, title, frame_type, window_type,
workspace, maximized, focus, geometry…}` from `global.get_window_actors()`),
`Details(winid)`, `Activate(winid)`, `Close`, `Move/Resize/Maximize`,
workspace ops. Windows are addressed by `meta_window.get_id()`; activation is
`workspace.activate_with_focus(win, 0)`. No version branching in the code —
it relies on the Meta API being stable and ships a new `shell-version` list per
release. Forks (window-calls-extended etc.) add title/focus fields but keep the
same shape. This validates the "extension exposes JSON-over-D-Bus keyed by
window id" design for deckd.

## Version fragility (GNOME 40 → 48+)

- **The Meta/Shell APIs above have been stable across 40–48.**
  `get_window_actors`, `Meta.Window` identity getters, `window-created`/
  `unmanaging`, `activate(_with_workspace)`, `Main.activateWindow` are all
  unchanged in this range. (Pre-40 `global.screen` → `global.display`/
  `workspace_manager` was the last big break in this area.)
- **GNOME 45 broke every extension mechanically**: mandatory ESM
  (`import Gio from 'gi://Gio'`), default-export `Extension` subclass with
  `enable()/disable()`. One codebase cannot target both pre- and post-45.
  Source: https://gjs.guide/extensions/upgrading/gnome-shell-45.html
  deckd's extension is already ESM/Extension-class style, so this is behind us.
- **`metadata.json` `shell-version` is an exact-match gate**: extensions are
  disabled on any shell release not listed, so a metadata bump (not code
  change) is needed every GNOME release. deckd currently pins `["50"]`
  (`packaging/gnome-shell/deckd-focus@local/metadata.json`).
- Net assessment: **low API risk, recurring packaging chore.** The risk is
  release-cadence maintenance, not API drift.

## Relation to deckd's current extension

`packaging/gnome-shell/deckd-focus@local/extension.js` already owns a bus name,
exports a D-Bus object with a JSON-string method + change signal, and listens
on `notify::focus-window`. Extending it for #116 is additive:

1. `ListWindows() → s` (JSON array; same field style as `GetActiveWindow`,
   plus `id`, `workspace`, `sandboxed_app_id`) via
   `global.get_window_actors()` or `get_tab_list`.
2. `WindowsChanged` signal driven by `window-created` +
   per-window `unmanaging` / `notify::title`.
3. `ActivateWindow(id)` — look up by `get_id()` over the actor list, call
   `Main.activateWindow(win)` (import from
   `resource:///org/gnome/shell/ui/main.js`).

The `_callOrNull` defensive pattern already in the extension is the right
hedge for the (small) residual Meta.Window API risk.
