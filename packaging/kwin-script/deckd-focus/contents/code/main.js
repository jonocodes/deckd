// deckd-focus — KWin focus bridge for the deckd daemon (issue #31).
//
// Pushes the active window over the session D-Bus into a daemon-owned
// cache at org.deckd.Focus.UpdateActiveWindow(s). The daemon's
// KdeFocusBackend (daemon/deckd/platform.py) owns the org.deckd.Focus
// name, serves GetActiveWindow(s) with byte-identical wire shape to
// the GNOME Shell extension's deckd-focus@local, and the daemon's
// focus watcher reads the cache on every 100ms poll.
//
// KWin scripts run inside the compositor process and can callDBus OUT
// only — they cannot own a D-Bus name or expose inbound method slots
// (src/scripting/scripting.cpp; develop.kde.org KWin scripting API).
// See docs/spike-kde-wayland-focus.md §"Recommended path" for the
// architecture rationale and §"Open questions" for the
// daemon-vs-script ownership split.
//
// KWin API surface used (stable since KWin 6.0; develop.kde.org/docs/
// plasma/kwin/api/, "KWin::Window" + "Global / Functions"):
//   workspace.activeWindow        — KWin::Window *  (the focused window)
//   workspace.windowActivated     — signal fired on every focus change
//   win.desktopFileName           — .desktop basename (KDE's app_id);
//                                   empty for some XWayland clients →
//                                   fall back to resourceClass
//   win.resourceClass             — WM_CLASS class slot
//   win.caption                   — WM_NAME without hostname suffix
//   win.pid                       — process pid (KWin 5.20+)
//   win.internalId                — QUuid (diagnostic only)
//   callDBus(svc, path, iface, method, args…) — outbound D-Bus call
//
// Install / hot-start (consumers should use `just install-focus-kwin`,
// which wraps these three steps):
//
//   kpackagetool6 --type=KWin/Script -i packaging/kwin-script/deckd-focus/
//   kwriteconfig6 --file kwinrc --group Plugins --key deckd-focusEnabled true
//   qdbus org.kde.KWin /KWin org.kde.KWin.reconfigure
//   qdbus org.kde.KWin /Scripting \
//         org.kde.kwin.Scripting.loadScript \
//         "$HOME/.local/share/kwin/scripts/deckd-focus/contents/code/main.js" \
//         deckd-focus
//
// When the daemon starts AFTER the script is loaded (the common case
// once the script is enabled in kwinrc), the script's initial
// push(workspace.activeWindow) goes nowhere — the cache is empty until
// the next window activation. Re-running `just install-focus-kwin`
// reloads the script and re-fires the initial push against the
// now-running daemon, populating the cache without a relogin.

const BUS_NAME = "org.deckd.Focus";
const OBJ_PATH = "/org/deckd/Focus";
const IFACE = "org.deckd.Focus";
const METHOD_PUSH = "UpdateActiveWindow";

function snapshot(win) {
    // The daemon's DeckdFocusCache.update validates JSON and tolerates
    // missing keys via data.get(...), matching GnomeShellFocusBackend's
    // parse. Keep the keys aligned with the AppInfo fields the daemon
    // accepts: app_id / wm_class / title / pid (+ diagnostic uuid).
    if (!win) {
        return JSON.stringify({
            app_id: null,
            wm_class: null,
            title: null,
            pid: null,
        });
    }
    return JSON.stringify({
        // desktopFileName: KDE's app_id (the .desktop basename, set
        // from xdg_toplevel.app_id for Wayland-native windows). Empty
        // for some XWayland clients → fall back to null; the daemon's
        // AppInfo.identity falls back to wm_class anyway.
        app_id:  win.desktopFileName || null,
        // resourceClass: WM_CLASS class slot. Same value as app_id
        // for most Wayland-native apps; always populated for XWayland.
        wm_class: win.resourceClass  || null,
        // caption: WM_NAME without the hostname suffix.
        title:   win.caption         || null,
        // pid: KWin 5.20+.
        pid:     win.pid             || null,
        // uuid kept for diagnostics only; the daemon's cache.update
        // ignores unknown keys via data.get(...).
        uuid:    win.internalId      ? String(win.internalId) : null,
    });
}

function push(win) {
    // callDBus throws through to KWin's logging if the daemon isn't
    // running (org.deckd.Focus unowned). Swallow it — the daemon
    // coming online later will receive the next windowActivated push,
    // and re-running install-focus-kwin re-fires the initial push.
    try {
        callDBus(BUS_NAME, OBJ_PATH, IFACE, METHOD_PUSH, snapshot(win));
    } catch (err) {
        console.error("deckd-focus: callDBus UpdateActiveWindow failed:", err);
    }
}

// Initial state so GetActiveWindow is non-empty before the first
// alt-tab. If the daemon isn't up yet this push is silently dropped
// (see push() comment); re-running install-focus-kwin re-fires it.
push(workspace.activeWindow);

// Focus changes (Workspace::windowActivated signal). Title-only
// updates (captionChanged on an already-focused window) are NOT wired
// here: the 100ms poll interval is short enough that a stale caption
// is invisible, and connecting captionChanged would double the push
// frequency on tab switches inside a focused browser. See spike #30
// open question #6 for the deferred consideration.
workspace.windowActivated.connect(push);