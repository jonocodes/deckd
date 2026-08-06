import Gio from "gi://Gio";
import GLib from "gi://GLib";
import Meta from "gi://Meta";
import * as Main from "resource:///org/gnome/shell/ui/main.js";
import {Extension} from "resource:///org/gnome/shell/extensions/extension.js";

const BUS_NAME = "org.deckd.Focus";
const OBJECT_PATH = "/org/deckd/Focus";

const DBUS_XML = `
<node>
  <interface name="org.deckd.Focus">
    <method name="GetActiveWindow">
      <arg type="s" name="window_json" direction="out"/>
    </method>
    <method name="ListWindows">
      <arg type="s" name="windows_json" direction="out"/>
    </method>
    <method name="RaiseWindow">
      <arg type="s" name="window_id" direction="in"/>
      <arg type="b" name="raised" direction="out"/>
    </method>
    <method name="RaiseApp">
      <arg type="s" name="identity" direction="in"/>
      <arg type="b" name="raised" direction="out"/>
    </method>
    <signal name="ActiveWindowChanged">
      <arg type="s" name="window_json"/>
    </signal>
  </interface>
</node>`;

export default class DeckdFocusExtension extends Extension {
  enable() {
    // id (String(Meta.Window.get_id())) -> Meta.Window, populated on
    // every ListWindows() enumeration (the daemon polls it at the focus
    // cadence) and pruned when a window is unmanaged. RaiseWindow(id)
    // resolves through this table; a retired id returns false (#122).
    this._windowMap = new Map();
    this._windowEntries = new Map();
    // Per-window ``unmanaging`` handler ids so we can disconnect on
    // disable() and when a window retires — no leaked signal handlers.
    this._unmanagingIds = new Map();
    // Export the object FIRST (on the connection's unique name), then acquire the
    // well-known name with the 6-arg standalone helper. The method-style
    // Gio.DBus.session.own_name(...) used here previously was removed on GNOME 50
    // ("At least 6 arguments required, but only 5 passed"), which killed enable().
    // Callbacks make ownership observable instead of silently assumed.
    this._dbus = Gio.DBusExportedObject.wrapJSObject(DBUS_XML, this);
    this._dbus.export(Gio.DBus.session, OBJECT_PATH);

    this._busNameId = Gio.bus_own_name(
      Gio.BusType.SESSION,
      BUS_NAME,
      Gio.BusNameOwnerFlags.REPLACE,
      (conn, name) => log(`[deckd-focus] bus acquired ${name}`),
      (conn, name) => log(`[deckd-focus] name registered ${name}`),
      (conn, name) => log(`[deckd-focus] bus lost/failed ${name}`),
    );

    this._focusSignalId = global.display.connect("notify::focus-window", () => {
      this._emitActiveWindowChanged();
    });

    this._emitActiveWindowChanged();
  }

  disable() {
    if (this._unmanagingIds) {
      for (const [metaWindow, handlerId] of this._unmanagingIds) {
        try {
          metaWindow.disconnect(handlerId);
        } catch (_e) {
          // window already gone; nothing to disconnect
        }
      }
      this._unmanagingIds.clear();
      this._unmanagingIds = null;
    }
    if (this._windowMap) {
      this._windowMap.clear();
      this._windowMap = null;
    }
    if (this._windowEntries) {
      this._windowEntries.clear();
      this._windowEntries = null;
    }
    if (this._focusSignalId) {
      global.display.disconnect(this._focusSignalId);
      this._focusSignalId = 0;
    }
    if (this._dbus) {
      this._dbus.unexport();
      this._dbus = null;
    }
    if (this._busNameId) {
      Gio.bus_unown_name(this._busNameId);
      this._busNameId = 0;
    }
  }

  GetActiveWindow() {
    return this._activeWindowJson();
  }

// Stage 2 (#120 / #126): JSON snapshot of every open window,
// MRU-sorted by ``global.display.focus_window`` first. The daemon
// polls this at the same ~100ms cadence as ``GetActiveWindow``;
// ``window_id`` is the stringified ``Meta.Window.get_id()`` — stable
// for the window's lifetime, opaque to the daemon and the client
// (#119). No extension-side registry: the daemon derives labels from
// the snapshot and the client echoes the id back on tap (stage 3,
// #122); closing the window drops it from the snapshot on the next
// enumeration tick.
ListWindows() {
    // ``get_window_actors()`` lives on the Shell ``global`` (Shell.Global),
    // NOT on ``global.display`` (Meta.Display has no such method). Prefer
    // it; fall back to the display accessor only if a future Shell moves
    // it, and to ``[]`` if neither exists — so a missing API surfaces as
    // the chrome's empty state rather than a thrown method call.
    const actors = typeof global.get_window_actors === "function"
      ? global.get_window_actors()
      : (typeof global.display.get_window_actors === "function"
          ? global.display.get_window_actors()
          : []);
    const focused = global.display.focus_window;
    const entries = [];
    for (const actor of actors) {
      const metaWindow = actor.meta_window;
      if (!metaWindow) continue;
      const entry = this._windowJson(metaWindow);
      if (entry) {
        entries.push(entry);
        this._trackWindow(entry.window_id, metaWindow);
        this._windowEntries.set(entry.window_id, entry);
      }
    }
    entries.sort((a, b) => {
      if (a.window_id === this._focusedWindowId(focused)) return -1;
      if (b.window_id === this._focusedWindowId(focused)) return 1;
      return 0;
    });
    return JSON.stringify(entries);
  }

  // Raise (activate) the window carrying ``window_id``. Returns true when
  // the id resolves to a live window, false when it's unknown/retired —
  // the daemon logs the false and emits a diagnostic ``raise_failed``
  // event (#122). ``Main.activateWindow`` handles unminimize + workspace
  // switch + focus in one call.
  RaiseWindow(window_id) {
    const metaWindow = this._windowMap ? this._windowMap.get(window_id) : undefined;
    if (!metaWindow) return false;
    Main.activateWindow(metaWindow);
    return true;
  }

  // Raise the MRU window whose wm_class, GTK application id, or sandboxed
  // application id exactly matches the configured identity.
  RaiseApp(identity) {
    if (!this._windowMap) return false;
    this.ListWindows();
    for (const entry of this._windowEntries.values()) {
      if (![entry.wm_class, entry.gtk_application_id, entry.sandboxed_app_id].includes(identity)) continue;
      const metaWindow = this._windowMap.get(entry.window_id);
      if (!metaWindow) continue;
      Main.activateWindow(metaWindow);
      return true;
    }
    return false;
  }

  // Record id -> Meta.Window and, once per window, wire its
  // ``unmanaging`` signal so the entry is pruned the instant the window
  // closes (rather than lingering until the next enumeration tick).
  _trackWindow(windowId, metaWindow) {
    if (!this._windowMap) return;
    this._windowMap.set(windowId, metaWindow);
    if (this._unmanagingIds && !this._unmanagingIds.has(metaWindow)) {
      const handlerId = metaWindow.connect("unmanaging", () => {
        this._forgetWindow(windowId, metaWindow);
      });
      this._unmanagingIds.set(metaWindow, handlerId);
    }
  }

  _forgetWindow(windowId, metaWindow) {
    if (this._windowMap) this._windowMap.delete(windowId);
    if (this._unmanagingIds && this._unmanagingIds.has(metaWindow)) {
      try {
        metaWindow.disconnect(this._unmanagingIds.get(metaWindow));
      } catch (_e) {
        // already disconnected
      }
      this._unmanagingIds.delete(metaWindow);
    }
  }

  _emitActiveWindowChanged() {
    if (!this._dbus) return;
    this._dbus.emit_signal("ActiveWindowChanged", new GLib.Variant("(s)", [this._activeWindowJson()]));
  }

  _activeWindowJson() {
    const win = global.display.focus_window;
    if (!win) {
      return JSON.stringify({
        app_id: null,
        wm_class: null,
        title: null,
        pid: null,
      });
    }

    return JSON.stringify({
      app_id: this._callOrNull(win, "get_gtk_application_id"),
      wm_class: this._callOrNull(win, "get_wm_class"),
      title: this._callOrNull(win, "get_title"),
      pid: this._callOrNull(win, "get_pid"),
    });
  }

  _windowJson(metaWindow) {
    const id = this._callOrNull(metaWindow, "get_id");
    if (id === null) return null;
    const workspace = this._callOrNull(metaWindow, "get_workspace");
    const sandboxed = this._sandboxedAppId(metaWindow);
    return {
      window_id: String(id),
      wm_class: this._callOrNull(metaWindow, "get_wm_class"),
      gtk_application_id: this._callOrNull(metaWindow, "get_gtk_application_id"),
      sandboxed_app_id: sandboxed,
      title: this._callOrNull(metaWindow, "get_title"),
      workspace: workspace !== null && typeof workspace.index === "number" ? workspace.index : null,
      minimized: this._callOrNull(metaWindow, "minimized") === true,
    };
  }

  _focusedWindowId(focused) {
    if (!focused) return null;
    const id = this._callOrNull(focused, "get_id");
    return id === null ? null : String(id);
  }

  _sandboxedAppId(metaWindow) {
    // Flatpak / Snap apps expose a third identity key on MetaWindow
    // via ``get_app()`` → ``Meta.App`` → ``get_id()`` (the
    // sandboxed-app id, e.g. ``org.flathub.Firefox``). The getter is
    // stable across GNOME 40-48 per #118. Falls back to ``null`` when
    // the window doesn't expose an app object (legacy X11 windows).
    const app = this._callOrNull(metaWindow, "get_app");
    if (!app) return null;
    return this._callOrNull(app, "get_id");
  }

  _callOrNull(obj, method) {
    if (!obj || typeof obj[method] !== "function") return null;
    const value = obj[method]();
    return value === undefined ? null : value;
  }
}
