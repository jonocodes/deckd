// deckd-focus — KWin focus/window bridge for the deckd daemon (#31, #133).
//
// Pushes the active window AND the full open-window list over the session
// D-Bus into a daemon-owned cache at org.deckd.Focus (UpdateActiveWindow /
// UpdateWindowList), and drives window raises the daemon can't issue
// itself. The daemon's KdeFocusBackend (daemon/deckd/platform.py) owns the
// org.deckd.Focus name, serves GetActiveWindow / ListWindows with wire
// shape byte-identical to the GNOME Shell extension deckd-focus@local, and
// its watchers read the cache on every 100ms poll.
//
// KWin scripts run inside the compositor process and can callDBus OUT
// only — they cannot own a D-Bus name or expose inbound method slots
// (src/scripting/scripting.cpp; develop.kde.org KWin scripting API). That
// one constraint shapes the whole design:
//   * focus + enumeration invert to PUSH (script → daemon cache);
//   * raise inverts to ENQUEUE-AND-POLL — the daemon can't call into
//     KWin, so it queues a window id and this script drains the queue on
//     a QTimer tick (DrainPendingRaises) and sets workspace.activeWindow.
// See docs/spike-kde-wayland-focus.md §"Recommended path" and
// docs/PLATFORM-PARITY.md (KDE backend note) for the full rationale.
//
// KWin API surface used (all verified against invent.kde.org/plasma/kwin
// master — see the #133 research notes; stable since KWin 6.0):
//   workspace.activeWindow        — KWin::Window * (focused); WRITABLE:
//                                   assigning raises + focuses the window
//   workspace.windowList()        — every managed window (Plasma 6 name;
//                                   the Plasma 5 clientList() was removed)
//   workspace.windowActivated     — signal fired on every focus change
//   workspace.windowAdded/Removed — signals fired on open/close
//   win.desktopFileName           — .desktop basename (KDE's app_id);
//                                   empty for some XWayland clients →
//                                   fall back to resourceClass
//   win.resourceClass             — WM_CLASS class slot
//   win.caption                   — WM_NAME without hostname suffix
//   win.pid                       — process pid (KWin 5.20+)
//   win.internalId                — QUuid; stringified as the stable,
//                                   opaque window_id shared with the daemon
//   win.minimized / win.desktops  — window state for the enumeration wire
//   win.skipTaskbar               — filters Plasma panels / OSDs out
//   win.{caption,minimized,desktops}Changed — per-window state signals
//   QTimer                        — exposed to the script sandbox by
//                                   scripting.cpp; drives the raise poll
//   callDBus(svc, path, iface, method, args…, cb?) — outbound D-Bus call;
//                                   the trailing callable is a reply cb
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
const METHOD_PUSH_LIST = "UpdateWindowList";
const METHOD_DRAIN_RAISES = "DrainPendingRaises";
// Raise-poll cadence. The daemon enqueues a raise the instant a
// running-windows row is tapped; this is the worst-case lag before the
// window activates. 200ms keeps the tap feeling responsive without
// busying the session bus (cf. the daemon's own 100ms focus poll).
const RAISE_POLL_MS = 200;

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

// --- Window enumeration (#133) -------------------------------------------
//
// The enumeration counterpart of the focus push: build a JSON array of
// every open application window and push it via UpdateWindowList. The
// daemon serves it back on ListWindows(), and its inherited
// GnomeShellFocusBackend.watch_windows gdbus-polls that unchanged — so the
// running-windows list lights up with the same plumbing as GNOME.

function windowId(win) {
    return win && win.internalId ? String(win.internalId) : null;
}

function windowSnapshot(win) {
    // Keys match the daemon's _window_info_from_payload and the GNOME
    // extension's per-window shape (wire-shape.js windowPayload). Unknown
    // keys are ignored by the daemon, missing ones tolerated via .get().
    const desktops = win.desktops;
    // 0-based to match the GNOME extension's get_workspace().index wire
    // value — KWin's x11DesktopNumber is 1-based, so subtract one. The
    // field is unrendered in v1's chrome, but keep the wire semantics
    // identical across backends. Empty desktops list ⇒ on all desktops ⇒
    // null, mirroring GNOME's null-workspace case.
    const ws =
        desktops && desktops.length && typeof desktops[0].x11DesktopNumber === "number"
            ? desktops[0].x11DesktopNumber - 1
            : null;
    return {
        window_id: windowId(win),
        // resourceClass is the WM_CLASS class slot — the primary identity
        // token the layout matcher compares against.
        wm_class: win.resourceClass || null,
        // KDE exposes no GTK application id; leave it null (GNOME fills it
        // for GTK apps). desktopFileName — KDE's .desktop id — is the
        // closest analogue to the GNOME extension's Meta.App id, so it
        // rides in sandboxed_app_id to give the matcher a desktop-file
        // token too (see docs/PLATFORM-PARITY.md, KDE backend note).
        gtk_application_id: null,
        sandboxed_app_id: win.desktopFileName || null,
        app_name: null,
        title: win.caption || null,
        workspace: ws,
        minimized: win.minimized === true,
    };
}

function enumerableWindows() {
    // windowList() is the Plasma 6 accessor (the Plasma 5 clientList()
    // was removed). typeof-guarded so a KWin without it degrades to an
    // empty list rather than throwing every tick.
    const all = typeof workspace.windowList === "function" ? workspace.windowList() : [];
    const out = [];
    for (let i = 0; i < all.length; i++) {
        const win = all[i];
        if (!win) continue;
        // skipTaskbar is KWin's native "don't show in the task switcher"
        // flag — exactly the running-windows semantics — so it's the only
        // filter we apply: it drops Plasma panels / docks / OSDs while
        // keeping every real app window, INCLUDING the rare Wayland client
        // with no resourceClass (which the GNOME extension's ListWindows
        // also lists, wm_class null). Requiring a resourceClass here would
        // silently drop such a window and diverge from GNOME. An undefined
        // skipTaskbar is falsy, so a KWin lacking the property just widens
        // the list rather than emptying it.
        if (win.skipTaskbar) continue;
        out.push(win);
    }
    return out;
}

// id -> true for windows whose state signals we've already wired, so a
// window is connected once no matter how many enumerations it appears in.
const trackedWindows = {};

function trackWindow(win, id) {
    if (trackedWindows[id]) return;
    trackedWindows[id] = true;
    // Re-push when a tracked window's label-relevant state changes, so the
    // running-windows list reflects title / minimize / desktop moves
    // without waiting for the next add/remove/activate (GNOME's
    // ListWindows is live-polled, so this keeps parity). These per-window
    // connections aren't explicitly disconnected — windowRemoved only
    // forgets the tracking flag; KWin drops the signal connections when the
    // window object itself is destroyed, so no handler leaks past a close.
    if (win.captionChanged) win.captionChanged.connect(pushWindowList);
    if (win.minimizedChanged) win.minimizedChanged.connect(pushWindowList);
    if (win.desktopsChanged) win.desktopsChanged.connect(pushWindowList);
}

function pushWindowList() {
    const wins = enumerableWindows();
    const activeId = windowId(workspace.activeWindow);
    const entries = [];
    for (let i = 0; i < wins.length; i++) {
        const entry = windowSnapshot(wins[i]);
        if (entry.window_id === null) continue;
        entries.push(entry);
        trackWindow(wins[i], entry.window_id);
    }
    // Focused-first (the MRU primary sort the GNOME extension applies), so
    // the active window heads the chrome list.
    entries.sort(function (a, b) {
        if (a.window_id === activeId) return -1;
        if (b.window_id === activeId) return 1;
        return 0;
    });
    try {
        callDBus(BUS_NAME, OBJ_PATH, IFACE, METHOD_PUSH_LIST, JSON.stringify(entries));
    } catch (err) {
        console.error("deckd-focus: callDBus UpdateWindowList failed:", err);
    }
}

// --- Raise (#133) --------------------------------------------------------
//
// KWin scripts can't receive inbound D-Bus, so the daemon can't tell KWin
// to raise a window. Instead it enqueues the target window id and this
// script polls for the queue on a QTimer tick: DrainPendingRaises returns
// a JSON array of ids (and clears the queue daemon-side); we activate each
// by assigning workspace.activeWindow (which raises + focuses).

function activateById(id) {
    const wins = typeof workspace.windowList === "function" ? workspace.windowList() : [];
    for (let j = 0; j < wins.length; j++) {
        if (String(wins[j].internalId) === id) {
            workspace.activeWindow = wins[j];
            return;
        }
    }
    // No match: the id retired between enumeration and the drain. The
    // daemon already declines raises for ids absent from its cache, so
    // this is a rare race — drop it silently (fire-and-forget).
}

function drainRaises() {
    try {
        callDBus(BUS_NAME, OBJ_PATH, IFACE, METHOD_DRAIN_RAISES, function (reply) {
            if (!reply) return;
            let ids;
            try {
                ids = JSON.parse(reply);
            } catch (e) {
                return;
            }
            if (!ids || !ids.length) return;
            for (let k = 0; k < ids.length; k++) activateById(String(ids[k]));
        });
    } catch (err) {
        console.error("deckd-focus: callDBus DrainPendingRaises failed:", err);
    }
}

// --- Wiring --------------------------------------------------------------

// Initial state so GetActiveWindow / ListWindows are non-empty before the
// first alt-tab. If the daemon isn't up yet these pushes are silently
// dropped (see push() comment); re-running install-focus-kwin re-fires them.
push(workspace.activeWindow);
pushWindowList();

// Focus changes (Workspace::windowActivated). Both the active-window
// snapshot and the window list get pushed: activation reorders the
// focused-first list even when the window set is unchanged.
workspace.windowActivated.connect(function (win) {
    push(win);
    pushWindowList();
});

// Open / close change the window set. windowRemoved also forgets the
// window's tracking flag so trackedWindows doesn't grow across a long
// session of opening and closing windows.
if (workspace.windowAdded) {
    workspace.windowAdded.connect(pushWindowList);
}
if (workspace.windowRemoved) {
    workspace.windowRemoved.connect(function (win) {
        const id = windowId(win);
        if (id) delete trackedWindows[id];
        pushWindowList();
    });
}

// Raise poll. QTimer is exposed to the script sandbox by scripting.cpp;
// the persistent timer is what lets a daemon-initiated raise reach KWin
// despite the outbound-only D-Bus constraint.
const raiseTimer = new QTimer();
raiseTimer.interval = RAISE_POLL_MS;
raiseTimer.timeout.connect(drainRaises);
raiseTimer.start();