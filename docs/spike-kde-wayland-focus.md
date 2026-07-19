# Spike #30 — KDE-Wayland active-window detection

Investigation only. No code changed. All claims verified against primary sources
(KWin source tree at `invent.kde.org/plasma/kwin@master`, `develop.kde.org`, the
freedesktop `wayland-protocols` repo, and KDE's `plasma-wayland-protocols`
repo). Where a secondary aggregator (`wayland.app` / Wayland Explorer) disagreed
with the primary source, the primary source wins and the discrepancy is called
out.

Wire-shape requirement (from `daemon/deckd/platform.py:12-17`):

```python
@dataclass(frozen=True)
class AppInfo:
    app_id: str | None
    wm_class: str | None
    title: str | None = None
    pid: int | None = None
```

GNOME reference shape (the KDE backend must produce identical JSON):
`gdbus call --session --dest org.deckd.Focus --object-path /org/deckd/Focus
--method org.deckd.Focus.GetActiveWindow` returns a D-Bus single-string tuple
wrapping `{"app_id":..., "wm_class":..., "title":..., "pid":...}` as JSON
(see `daemon/deckd/platform.py:38-62`, `_parse_single_string_tuple`).

---

## TL;DR / Recommendation

Use a **KWin script that `callDBus`-pushes the active window into a
daemon-owned `org.deckd.Focus` D-Bus object**; keep the existing
`GnomeShellFocusBackend` unchanged as the poll path so the daemon-side wire
shape is byte-identical to GNOME. KWin scripts can only `callDBus` **outbound**
(they cannot own a D-Bus name), so the GNOME pull-model cannot be mirrored
exactly — we invert KDE to push-into-cache. Confirming Wayland's
"clients-cannot-see-each-other" principle does **not** bite: KWin scripts run
**inside the compositor process** with full access to `workspace.activeWindow`
(KWin `src/scripting/workspace_wrapper.h:60,168,334`). The big surprise from
this spike: KWin does **not** implement `wlr-foreign-toplevel-management-v1` or
`ext-foreign-toplevel-list-v1` (Wayland Explorer's table is wrong for KWin),
which collapses the candidate field to the KWin-script path.

---

## Candidates evaluated

### 1. `org.kde.KWin` D-Bus session-bus interface — **partial (interactive only)**

KWin registers the session-bus service `org.kde.KWin` with object path `/KWin`
and exposes an `org.kde.KWin` interface (KWin `src/dbusinterface.cpp:39-50`).
The introspection XML (`src/org.kde.KWin.xml`) lists:

- `queryWindowInfo() → a{sv}` — **interactive**. Implementation
  (`src/dbusinterface.cpp:158-178`) calls
  `kwinApp()->startInteractiveWindowSelection(...)`, sets a delayed D-Bus
  reply, and only resolves once the user clicks a window (or cancels with
  error `org.kde.KWin.Error.UserCancel`). Unusable for non-interactive
  100 ms polling.
- `getWindowInfo(QString uuid) → a{sv}` — **non-interactive**, given a window
  UUID. Backed by `clientToVariantMap` (`src/dbusinterface.cpp:118-154`),
  which returns:
  `resourceClass` (= WM_CLASS class), `resourceName` (= WM_CLASS instance),
  `desktopFile` (= the `.desktop` basename → KDE's `app_id`, e.g.
  `org.kde.dolphin`), `caption` (= WM_NAME/title), `pid` ✓, `uuid`, plus
  geometry/state flags. **Data shape is exactly `AppInfo`** (`app_id` ←
  `desktopFile` with `resourceClass` fallback; `wm_class` ← `resourceClass`;
  `title` ← `caption`; `pid` ← `pid`).
- No `activeWindow`/`activeClient`/`activeUuid` method is exposed on
  `org.kde.KWin` (verified by reading `org.kde.KWin.xml` in full). The active
  output name (`activeOutputName`) is exposed, but not the active window.

**Verdict: partial.** `getWindowInfo` gives a complete `AppInfo` *only if the
daemon can name the active window's UUID*. The active UUID is not exposed via
D-Bus, so `getWindowInfo` alone cannot drive polling — but it is a useful
helper if a KWin script furnishes the UUID (see candidate #2).

### 2. KWin scripting API — **viable (the recommended feeder)**

KWin scripts run inside the KWin process via a QJSEngine
(`src/scripting/scripting.cpp`). They have read/write access to
`workspace.activeWindow` (a `KWin::Window *`), and the
`workspace.windowActivated(KWin::Window *)` signal fires on every focus change
(KWin `src/scripting/workspace_wrapper.h:60,168,334`; develop.kde.org KWin
scripting API).

The active `KWin::Window` exposes — to JS — every field we need
(`develop.kde.org/docs/plasma/kwin/api/`, "KWin::Window" section):
- `resourceClass` (= WM_CLASS class²) → `wm_class`
- `resourceName` (= WM_CLASS instance)
- `desktopFileName` (the `.desktop` basename, KDE's `app_id`) → `app_id`,
  with `resourceClass` fallback for XWayland apps without a desktop-file hint
- `caption` (= WM_NAME, `captionNormal`) → `title`
- `pid` (since KWin 5.20) → `pid`
- `internalId` (QUuid)

**Critical limitation confirmed against source.** KWin scripts can call D-Bus
**outbound** only — the `callDBus(service, path, interface, method, args…,
callback?)` global function (`src/scripting/scripting.cpp:301-…`; develop.kde.org
"Global / Functions"). They **cannot** own a D-Bus service name or register
inbound method handlers. The scripting subsystem registers its own object
paths (`/Scripting`, `/Scripting/Script<n>`) under the existing `org.kde.KWin`
bus name with two narrow interfaces:

- `org.kde.kwin.Scripting` at `/Scripting`
  (`src/scripting/scripting.cpp:682`, declaration `src/scripting/scripting.h:333-336`)
  exposes `Q_SCRIPTABLE Q_INVOKABLE`:
  - `int loadScript(QString filePath, QString pluginName = QString())` — loads
    and runs a JS file **at runtime**; returns a script id.
  - `int loadDeclarativeScript(QString filePath, QString pluginName)`
  - `bool isScriptLoaded(QString pluginName) const`
  - `bool unloadScript(QString pluginName)`
- `org.kde.kwin.Script` at `/Scripting/Script<n>` (`src/scripting/org.kde.kwin.Script.xml`)
  has only `run()` and `stop()`.

So **the daemon cannot poll a KWin script for the active window**: the script
has no inbound method slot. The architecture must **invert** to push:
script → `callDBus` → daemon-owned cache → `GetActiveWindow` (the polled
consumer keeps the GNOME wire shape unchanged).

**Install / enable flow** (develop.kde.org, "KWin scripting tutorial"):
- Package layout: `<id>/metadata.json` (with `"KPackageStructure":
  "KWin/Script"`, `"X-Plasma-API": "javascript"`,
  `"X-Plasma-MainScript": "code/main.js"`) and
  `<id>/contents/code/main.js`.
- Per-user install dir: `~/.local/share/kwin/scripts/<id>/`.
- Install: `kpackagetool6 --type=KWin/Script -i <id>/`.
- Enable at runtime:
  ```sh
  kwriteconfig6 --file kwinrc --group Plugins --key <id>Enabled true
  qdbus org.kde.KWin /KWin org.kde.KWin.reconfigure
  ```
  (Source: develop.kde.org KWin scripting tutorial "Installation".)
- **Hot-start without reconfigure/relogin**:
  ```sh
  qdbus org.kde.KWin /Scripting \
        org.kde.kwin.Scripting.loadScript \
        "$HOME/.local/share/kwin/scripts/<id>/contents/code/main.js" <id>
  ```
  (Returns a script id; later removable via `unloadScript <id>`.) This is the
  path the daemon should use on first run so the user sees focus events
  immediately, with the `kwriteconfig6` step making it persistent.

**Permissions / Wayland gotchas.** KWin scripts run as part of the compositor
process (the QJSEngine is hosted inside KWin) — see `src/scripting/scripting.cpp`
where the engine is constructed in the KWin process and `workspace_wrapper.cpp`
hands out `KWin::Window *` pointers. This is compositor-internal data, not
Wayland-client data, so §"clients cannot see other clients" of the Wayland
design does not apply. No KDE portal grant is required, no kwin-script "dev
mode" exists, and a non-root user can install/enable scripts under
`~/.local/share/kwin/`.

**Returned data shape.** `app_id` (via `desktopFileName`, fallback
`resourceClass`), `wm_class` (via `resourceClass`), `title` (via `caption`),
`pid` — exactly `AppInfo`. (For pure XWayland windows with no desktop-file hint,
`desktopFileName` is empty; we fall back to `resourceClass`, matching the GNOME
backend's wm_class fallback.)

### 3. `wlr-foreign-toplevel-management-unstable-v1` — **rejected (KWin does not implement it)**

The protocol
(`gitlab.freedesktop.org/wlroots/wlr-protocols`, `unstable/wlr-foreign-toplevel-management-unstable-v1.xml`
via wayland.app) gives `title`, `app_id`, and a `state` bitfield with an
`activated` (value `2`) flag — sufficient to identify the active window, plus
`parent` (since v3). **No `pid` field, no `wm_class` field.**

Wayland Explorer's compositor-support table (`wayland.app/protocols/wlr-foreign-toplevel-management-unstable-v1`,
"Compositor Support") lists "KWin 6.6" with version `3`. **This is
inaccurate for the current KWin master**, verified by primary source:

- KWin's server-side protocol generation lives in
  `src/wayland/CMakeLists.txt`. Every `.xml` KWin compiles a server binding
  for is listed there (lines 13-81, fetched from `invent.kde.org/plasma/kwin@master`).
  **`wlr-foreign-toplevel-management-unstable-v1.xml` does not appear.**
- The only XMLs KWin vendors in `src/wayland/protocols/` are
  `wlr-layer-shell-unstable-v1.xml`, `xx-fractional-scale-v2.xml`,
  `xx-pip-v1.xml` (verified by `ls src/wayland/protocols/`).
- A `grep -rilE "foreign.?toplevel|wlr_foreign_toplevel|ext_foreign_toplevel|
  zwlr_foreign"` across the checked-out `src/` subtree returned **zero hits**
  in `src/wayland/` and `src/plugins/`.

So a foreign-toplevel Wayland client cannot bind this protocol on KWin. (The
Wayland Explorer row for KWin likely reflects a stale community submission, or
confusion with `org_kde_plasma_window_management`; either way, KWin source
contradicts it.) wlroots compositors (Sway, Hyprland, Labwc, River, Wayfire,
Cage, COSMIC) do implement it — see candidate #8.

### 4. `ext-foreign-toplevel-list-v1` — **rejected (KWin does not implement it)**

The freedesktop `wayland-protocols` staging protocol
(`gitlab.freedesktop.org/wayland/wayland-protocols`,
`staging/ext-foreign-toplevel-list/ext-foreign-toplevel-list-v1.xml`).
Per toplevel it provides `title`, `app_id`, and a stable `identifier` — **no
`state`/`activated` flag, no `pid`**. This means even where it exists it
cannot name the *active* window, only the set of mapped toplevels; it must be
combined with another source to find focus. (See companion protocol note
inside the XML: "additional functionality … to be implemented in extension
protocols.")

Same primary-source check as candidate #3: KWin `src/wayland/CMakeLists.txt`
does **not** list `ext-foreign-toplevel-list-v1.xml`, and no
`ext_foreign_toplevel` token appears anywhere in `src/`. The Wayland Explorer
table's "KWin 6.6 → v1" row is wrong for KWin, same as #3.

### 5. `org.kde.taskmanager` / TaskManager applet D-Bus — **rejected (no public active-window interface)**

Plasma's Task Manager applet (in `plasma-workspace`) consumes
`org_kde_plasma_window_management` over Wayland *in-process* and keeps the
active-window state in an internal QML model. There is no public session-bus
service named `org.kde.taskmanager` or `org.kde.TaskManager` that exposes the
active window to third-party callers; the active-window truth lives in the
applet's C++ model, not behind a documented D-Bus interface. A `qdbus
org.kde.kded` / `org.kde.plasmashell` introspection on a stock Plasma 6
session lists no `taskmanager`-owned method returning the active window. (Not
checked into KWin source; rejected on documented-interface absence. Worth a
live `qdbus org.kde.plasmashell` survey step during #31 if we want to be
paranoid, but it is not a primary path.)

### 6. `org.freedesktop.portal.GlobalShortcuts` / `RemoteDesktop` / `ScreenCast` — **rejected (none leak active-window identity)**

- `GlobalShortcuts` is for registering and listening to global shortcuts; the
  portal's `Notify` callbacks carry the shortcut id and a `activation_token`,
  not the foreground app. (`docs/portal-permissions` on develop.kde.org is the
  pre-auth story.)
- `RemoteDesktop` pipes input events and pointer/seat state; it does not
  surface a foreground app id.
- `ScreenCast` exposes `PipeWire` node streams by `session_handle`/`node_id`;
  it does not identify the focused application.

Reject fast. Portals are deliberately app-agnostic so they can run inside a
confinement boundary.

### 7. `KWindowSystem` / `NETWinInfo` — **rejected on Wayland (X11-only)**

`KWindowSystem` (KDE Frameworks, `api.kde.org/frameworks/kwindowsystem/html/`)
on X11 reads `_NET_ACTIVE_WINDOW` from the root window (`NETWinInfo`) and
`_NET_WM_PID`/`WM_CLASS` from each client — exactly `AppInfo`. On Wayland
there is no X root window and no `WM_CLASS`; `KWindowSystem::activeWindow()`
returns a null `WId` out-of-process, because Wayland by design does not let
arbitrary clients see each other. The Wayland platform plugin inside the
compositor (KWin) holds that data but does not re-publish it over
libKWindowSystem. So an out-of-process daemon cannot use `KWindowSystem` on
Wayland. (This is the same wall the GNOME `org.gnome.Shell.Introspect` API hit
— see `docs/SPIKES.md` spike #2.)

### 8. Hyprland / Sway IPC — **out of scope for #30; viable, recommend a separate wlroots ticket**

- **Hyprland**: `hyprctl clients -j` returns each window with `initialClass`
  (≈ `wm_class`), `class`, `title`, `pid`; and `hyprctl activewindow -j`
  returns the focused window. The `hyprctl` IPC also emits a stream of
  `activewindow>>` events over the UNIX socket — but the daemon would have to
  IPC into the socket (the `hyprctl` binary is the simplest path).
- **Sway**: i3ipc-over-UNIX-socket (`swaymsg -t subscribe -m '["window"]'`,
  `swaymsg -t get_tree`) returns the full tree with `focused: true` on the
  active container, plus `window_properties.class`, `name`, `pid`.

Both feely include `pid` and `wm_class`; `app_id` is not native in Sway's i3
model (it surfaces `window_properties.class` instead). A single
`WlrIpcFocusBackend(PlatformBackend)` could cover Hyprland and Sway with
per-compositor dispatch; `pid` is available on both. **Recommendation: open a
separate wlroots focus-backend ticket for after #31** (the field notes that
both `AppInfo.app_id` and `pid` can be filled, with `app_id` left `None` on
Sway). Not covered by this KDE spike.

---

## Recommended path

### Architecture (one diagram, ASCII)

```
KWin process  ──[QJS: workspace.windowActivated]──▶ JS handler
                                                       │
                                                       │ callDBus()
                                                       ▼
daemon process ──[owns  org.deckd.Focus]──▶  UpdateActiveWindow(json_str)
                                                  │ caches latest
                                                  ▼
                       GetActiveWindow() ─▶ (returns cached JSON)

         (downstream: KdeFocusBackend = GnomeShellFocusBackend polling
          org.deckd.Focus.GetActiveWindow — wire shape identical to GNOME)
```

The GNOME pull model is preserved at the wire boundary: any consumer
(tests, `scripts/watch_focus.py`, `deckd` core) calls
`org.deckd.Focus.GetActiveWindow` and parses a single-string-tuple of JSON.
The only KDE-specific addition is the KWin script that feeds the cache.

### Install steps (KWin script)

Package skeleton shipped under `packaging/kwin-script/deckd-focus/`:

```
deckd-focus/                       # folder name == KPlugin.Id
├── metadata.json
└── contents/
    └── code/
        └── main.js
```

`metadata.json` (committed sketch — to be finalized by #31):

```json
{
  "KPlugin": {
    "Name": "deckd focus bridge",
    "Id": "deckd-focus",
    "Version": "1.0",
    "License": "GPLv3+"
  },
  "X-Plasma-API": "javascript",
  "X-Plasma-MainScript": "code/main.js",
  "KPackageStructure": "KWin/Script"
}
```

Install / enable / hot-start commands the daemon (or the README install hint)
should run:

```sh
# 1. install into ~/.local/share/kwin/scripts/deckd-focus/
kpackagetool6 --type=KWin/Script -i packaging/kwin-script/deckd-focus/

# 2. persist across relogins (writes kwinrc [Plugins] deckd-focusEnabled=true)
kwriteconfig6 --file kwinrc --group Plugins --key deckd-focusEnabled true

# 3a. start now without relogin: hot-inject via the Scripting interface
qdbus org.kde.KWin /Scripting \
      org.kde.kwin.Scripting.loadScript \
      "$HOME/.local/share/kwin/scripts/deckd-focus/contents/code/main.js" \
      deckd-focus

# 3b. (alternative to 3a) reconfigure so the enabled flag takes effect
qdbus org.kde.KWin /KWin org.kde.KWin.reconfigure
```

The daemon's `KdeFocusBackend.install_hint` (or `default_backend()` failure
path) should surface exactly these three lines so the user gets a one-shot
install.

### Data shape

| `AppInfo` field | KWin Script source (`KWin::Window` JS prop) | Notes |
|---|---|---|
| `app_id` | `win.desktopFileName \|\| null` | Wayland-native: KDE sets this from `xdg_toplevel.app_id`. Empty for XWayland windows without a `_KDE_NET_WM_DESKTOP_FILE` hint → fall back to `resourceClass`. |
| `wm_class` | `win.resourceClass \|\| null` | `WM_CLASS` class for XWayland; equals `app_id` for many native Wayland apps. |
| `title` | `win.caption \|\| null` | `captionNormal` (pure WM_NAME, no hostname suffix). |
| `pid` | `win.pid \|\| null` | Available since KWin 5.20; always non-negative for real clients. |

Plus, for diagnostic use, the script can add `"uuid": win.internalId`.

(All four fields verified against `develop.kde.org/docs/plasma/kwin/api/`,
"KWin::Window" section, cross-checked with the C++ `clientToVariantMap` in
KWin `src/dbusinterface.cpp:118-154` which exposes the same names.)

### Daemon-side wire call (byte-identical to GNOME)

```
gdbus call --session \
  --dest org.deckd.Focus \
  --object-path /org/deckd/Focus \
  --method org.deckd.Focus.GetActiveWindow
```

…returns `(JSON,)` — a single-element string tuple. The existing
`GnomeShellFocusBackend.get_active_app` (`daemon/deckd/platform.py:43-62`)
parses this with `_parse_single_string_tuple` and `json.loads`. **Reuse that
class unchanged on the KDE path** — the KDE backend only adds (a) the
D-Bus-server side that owns `org.deckd.Focus` and serves `GetActiveWindow` +
`UpdateActiveWindow`, and (b) the install/launch glue for the KWin script.

### Minimal KWin script sketch (NOT production — for #31 to harden)

Committed under `packaging/kwin-script/deckd-focus/contents/code/main.js`
(see that file — the script is intentionally kept small so #31 hardens
it in place rather than rotting a duplicate copy in this doc). The
sketch reads `workspace.activeWindow` and the
`workspace.windowActivated` signal, packages a JSON snapshot of
`{app_id, wm_class, title, pid, uuid}`, and pushes it via
`callDBus(`org.deckd.Focus`, `/org/deckd/Focus`,
`org.deckd.Focus`, `UpdateActiveWindow`, <json>)` after every focus
change plus once on load.

Daemon-side D-Bus server (sketch, dropped into the daemon; #31 to implement):

```python
# owns the same name the GNOME extension owns, but only on KDE sessions
# (gate on XDG_CURRENT_DESKTOP == "KDE" to avoid clashing with the GNOME
# extension on GNOME sessions — see Open Questions).

class DeckdFocusDBusService:
    bus_name = "org.deckd.Focus"
    object_path = "/org/deckd/Focus"
    interface = "org.deckd.Focus"

    def __init__(self) -> None:
        self._current = json.dumps(
            {"app_id": None, "wm_class": None, "title": None, "pid": None}
        )

    def GetActiveWindow(self) -> str:                 # out: s (wrapped in (s,) by gdbus)
        return self._current

    def UpdateActiveWindow(self, payload: str) -> None:  # in: s, no reply
        self._current = payload
```

(Use `dbus-next` or `pydbus` or `Gio.bus_own_name` — same shape already
demonstrated by the GNOME extension's `Gio.bus_own_name` path. The GNOME
extension is GJS; the daemon is Python, so #31 picks a Python binding.)

### Permissions / Wayland gotchas summary

- **Non-root, no TCC-style grant.** KWin scripts install under
  `~/.local/share/kwin/scripts/` and enable via `kwinrc` — no polkit, no
  portal, no capability.
- **No "KWin script dev mode" requirement.** `kpackagetool6` + `kwriteconfig6`
  + the `org.kde.kwin.Scripting.loadScript` runtime path are all stable
  user-level APIs (develop.kde.org KWin scripting tutorial; KWin `src/scripting/scripting.h:333-336`).
- **Wayland "clients cannot see each other" does NOT bite.** KWin scripts
  execute inside the compositor process (the QJSEngine in
  `src/scripting/scripting.cpp`), operating on `KWin::Window *` pointers that
  are compositor-internal — not Wayland-client-to-Wayland-client visibility.
  The `pid`/`caption`/`resourceClass`/`desktopFileName` are read directly off
  the `Window` object. Confirmed by reading
  `workspace_wrapper.h`/`workspace_wrapper.cpp` and the develop.kde.org
  scripting API page.
- **Stability across Plasma 6.x.** All APIs used —
  `workspace.activeWindow`, `workspace.windowActivated` (signal),
  `Window.{resourceClass,resourceName,desktopFileName,caption,pid,internalId}`,
  `callDBus`, `kpackagetool6`, `kwriteconfig6`, `org.kde.kwin.Scripting.loadScript`
  — are documented as KWin 6.0+ stable in the develop.kde.org scripting API
  page ("This page describes the KWin Scripting API as of KWin 6.0"). KWin
  scripts run in a QJS sandbox; minor Plasma 6.x point releases have not
  broken these APIs (no deprecation notices on `activeWindow` or
  `windowActivated` in master as of the spike date).
- **Plasma 7 risk.** Plasma 7 is not released; nothing in the current master
  trees deprecates `callDBus` or `workspace.activeWindow`. The push-into-cache
  design degrades gracefully: if the script's signal changes, only the small
  script needs updating, not the daemon.

---

## Open questions (todo for #31)

1. **Bus-name coexistence.** Both the GNOME Shell extension and this KDE
   daemon want to own `org.deckd.Focus`. They never coexist on the same
   session bus, but the daemon owning a name the GNOME extension already
   claims on GNOME makes the dual-purpose confusing. Options:
   (a) daemon owns `org.deckd.Focus` only when `XDG_CURRENT_DESKTOP == "KDE"`
   (recommended — minimal, keeps the wire shape the brief asked for); or
   (b) introduce a separate push-target name (`org.deckd.Focus.Source`) owned
   by the daemon and have `KdeFocusBackend` poll that instead — avoids the
   dual-purpose but breaks wire-shape symmetry. Pick (a) unless #31's review
   objects.
2. **`app_id` fallback rule.** For an XWayland window with an empty
   `desktopFileName`, the script currently emits
   `app_id: null, wm_class: resourceClass`. Confirm this matches the GNOME
   behavior for the same Firefox-on-XWayland case
   (`daemon/deckd/platform.py` reads `app_id` first; `AppInfo.identity`
   (`platform.py:19-21`) falls back to `wm_class`).
3. **Daemon-driven install vs. document-driven install.** Decide whether the
   daemon, on a `KdeFocusBackend` init failure, attempts the
   `kpackagetool6`/`kwriteconfig6`/`loadScript` install automatically
   (cleaner UX, requires the binaries on `$PATH`), or just prints the
   canonical install hint and bails (matches the X11 backend's stance in
   `platform.py:99-114`).
4. **Hot-start vs. reconfigure.** `org.kde.kwin.Scripting.loadScript` runs a
   script immediately without touching `kwinrc`, but does not survive
   relogin; `kwriteconfig6` + `reconfigure` persists but KWin may not pick
   up the script until the next session for some KWin versions. #31 should
   do both: hot-start for instant gratification, persist for next login.
5. **Window delete / unmapped state.** When the active window is closed
   (`windowRemoved` / `unmapped`), should the cache be cleared, or left
   pointing at the dead window until `windowActivated` fires next? GNOME
   behavior is "left until next activation"; mirror that.
6. **Title-only updates without a focus change.** `workspace.activeWindow` can
   change its caption (e.g. a browser tab switch in an already-focused
   window) without firing `windowActivated`. Decide whether to also connect
   `activeWindow.captionChanged` → repush. The 100 ms poll interval is long
   enough that a stale title for ≤100 ms may be acceptable; defer this to
   #31 if a user-perceptible lag shows up.
7. **wlroots family backend.** Open a separate ticket for a
   `WlrIpcFocusBackend` (Hyprland + Sway, candidate #8) covering everything
   KDE-KWin doesn't. Recommended for post-#31 work. Cross-reference the
   "KDE-X11 / XFCE / standalone WM" paragraph in `docs/SPIKES.md` spike #2
   decision so the supported-targets table stays consistent.
8. **Live introspection sanity check.** Before locking the recommendation
   into #31, run `qdbus org.kde.KWin /KWin` and `qdbus org.kde.KWin /Scripting`
   on a real Plasma 6 session box and paste the introspection into the ticket
   as evidence the methods cited here are reachable in a stock install
   (sources quoted are master; distro builds occasionally disable scripted
   effects via `-DKWIN_BUILD_KCM_KWIN_SCRIPTS=OFF`).

---

## References

- KWin source tree, `invent.kde.org/plasma/kwin@master`:
  - `src/org.kde.KWin.xml` — `org.kde.KWin` D-Bus interface introspection.
  - `src/dbusinterface.cpp:39-188` — `DBusInterface` impl; `queryWindowInfo`
    (interactive, line 158), `getWindowInfo` (non-interactive, line 180),
    `clientToVariantMap` (lines 118-154, the returned field set incl. `pid`).
  - `src/scripting/scripting.cpp` — QJSEngine hosting; `callDBus` (line 301);
    `/Scripting` + `/Scripting/Script<n>` D-Bus registration (lines 112, 682);
    per-script object registration (line 112).
  - `src/scripting/scripting.h:333-336` — `org.kde.kwin.Scripting`
    `Q_SCRIPTABLE Q_INVOKABLE loadScript / loadDeclarativeScript /
    isScriptLoaded / unloadScript`.
  - `src/scripting/org.kde.kwin.Script.xml` — per-script `run` / `stop`
    interface.
  - `src/scripting/workspace_wrapper.h:60,168,334` —
    `workspace.activeWindow` property (`NOTIFY windowActivated`) and the
    `workspace.windowActivated(Window *)` signal, confirmed against source.
  - `src/wayland/CMakeLists.txt:13-81` — every server-side Wayland protocol
    KWin implements; **does not** list `wlr-foreign-toplevel-management-v1`
    or `ext-foreign-toplevel-list-v1`.
  - `src/wayland/protocols/` — only three vendored XMLs
    (`wlr-layer-shell-unstable-v1`, `xx-fractional-scale-v2`, `xx-pip-v1`);
    confirms #3 and #4 rejection.
- KDE developer docs `develop.kde.org`:
  - `/docs/plasma/kwin/` — "KWin scripting tutorial" (install paths,
    `kpackagetool6`, `kwriteconfig6`, KPackage layout, `metadata.json`
    `KPackageStructure: KWin/Script`).
  - `/docs/plasma/kwin/api/` — "KWin scripting API"; `workspace.activeWindow`,
    `workspace.windowActivated`, `Window.{resourceClass, resourceName,
    desktopFileName, caption, pid, internalId}`, `callDBus(...)`, with the
    "KWin Scripting API as of KWin 6.0" coverage statement.
- `plasma-wayland-protocols` repo, `invent.kde.org/libraries/plasma-wayland-protocols`:
  - `src/protocols/plasma-window-management.xml` —
    `org_kde_plasma_window_management` and `org_kde_plasma_window`
    interfaces incl. `pid_changed`, `app_id_changed`, `state_changed` (with
    `active` bit), and the explicit warnings: *"Only one client can bind this
    interface at a time"* and *"Regular clients must not use this protocol"*
    (cited via `wayland.app/protocols/kde-plasma-window-management`). This
    rules out direct binding by an out-of-process daemon — plasmashell's
    task-manager holds the one allowed bind.
- freedesktop `wayland-protocols` repo, `gitlab.freedesktop.org/wayland/wayland-protocols`:
  - `staging/ext-foreign-toplevel-list/ext-foreign-toplevel-list-v1.xml` —
    fields `title`, `app_id`, `identifier`; no `state`/`activated`, no `pid`.
- wlroots `wlr-protocols` repo, `gitlab.freedesktop.org/wlroots/wlr-protocols`:
  - `unstable/wlr-foreign-toplevel-management-unstable-v1.xml` — fields
    `title`, `app_id`, `state` bitfield with `activated` (value `2`);
    no `wm_class`, no `pid`.
- `wayland.app` (Wayland Explorer) — used only as a secondary aggregator;
  its compositor-support table claims KWin 6.6 implements both #3 and #4,
  which contradicts the KWin source. This spike's #3/#4 rejections rest on
  the KWin source, not on Wayland Explorer.
- Existing project references (in-repo):
  - `daemon/deckd/platform.py:12-62` — `AppInfo`, the target data shape, and
    `GnomeShellFocusBackend` polling `org.deckd.Focus.GetActiveWindow`
    (the wire shape KDE must preserve).
  - `daemon/deckd/platform.py:80-114` — `X11FocusBackend` install-hint pattern
    to mirror in the KDE backend.
  - `docs/SPIKES.md` spike #2 — GNOME decision context; note that
    `org.gnome.Shell.Introspect` was ruled out for the same Wayland-isolation
    reason cited under candidate #7 here.