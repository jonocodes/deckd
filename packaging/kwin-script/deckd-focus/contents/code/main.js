// deckd-focus KWin script — sketch (spike #30).
//
// Hardened by #31. NOT production-ready. Verified only against the KWin
// 6.0 scripting API docs (develop.kde.org/docs/plasma/kwin/api/).
//
// Pushes the active window over session D-Bus into a daemon-owned
// org.deckd.Focus.UpdateActiveWindow(s) cache. KWin scripts can only
// callDBus OUT (no inbound methods, no name ownership) — see
// docs/spike-kde-wayland-focus.md §"Recommended path" for the
// architecture. The daemon's KdeFocusBackend then polls
// org.deckd.Focus.GetActiveWindow with the same wire shape as
// GnomeShellFocusBackend, so the GNOME and KDE code paths converge on
// the same JSON contract.
//
// Install / hot-start sequence (per findings doc):
//
//   kpackagetool6 --type=KWin/Script -i packaging/kwin-script/deckd-focus/
//   kwriteconfig6 --file kwinrc --group Plugins --key deckd-focusEnabled true
//   qdbus org.kde.KWin /KWin org.kde.KWin.reconfigure
//   qdbus org.kde.KWin /Scripting \
//         org.kde.kwin.Scripting.loadScript \
//         "$HOME/.local/share/kwin/scripts/deckd-focus/contents/code/main.js" \
//         deckd-focus

const BUS_NAME = "org.deckd.Focus";
const OBJ_PATH = "/org/deckd/Focus";
const IFACE = "org.deckd.Focus";
const METHOD_PUSH = "UpdateActiveWindow";

function snapshot(win) {
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
        // for some XWayland clients → fall back to resourceClass so
        // AppInfo.identity has something to match layouts against.
        app_id:  win.desktopFileName || null,
        // resourceClass: WM_CLASS class slot. Same value as app_id for
        // most Wayland-native apps; always populated for XWayland.
        wm_class: win.resourceClass  || null,
        // caption: WM_NAME without the hostname suffix.
        title:   win.caption         || null,
        // pid: KWin 5.20+.
        pid:     win.pid              || null,
        // uuid kept for diagnostics only; the daemon strips unknown keys.
        uuid:    win.internalId       ? String(win.internalId) : null,
    });
}

function push(win) {
    callDBus(BUS_NAME, OBJ_PATH, IFACE, METHOD_PUSH, snapshot(win));
}

// Initial state so GetActiveWindow is non-empty before the first
// alt-tab.
push(workspace.activeWindow);

// Focus changes (Workspace::windowActivated signal).
workspace.windowActivated.connect(push);