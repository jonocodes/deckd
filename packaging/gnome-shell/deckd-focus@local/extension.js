import Gio from "gi://Gio";
import GLib from "gi://GLib";
import Meta from "gi://Meta";
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
    <signal name="ActiveWindowChanged">
      <arg type="s" name="window_json"/>
    </signal>
  </interface>
</node>`;

export default class DeckdFocusExtension extends Extension {
  enable() {
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
    const actors = global.display.get_window_actors ? global.display.get_window_actors() : [];
    const focused = global.display.focus_window;
    const entries = [];
    for (const actor of actors) {
      const metaWindow = actor.meta_window;
      if (!metaWindow) continue;
      const entry = this._windowJson(metaWindow);
      if (entry) entries.push(entry);
    }
    entries.sort((a, b) => {
      if (a.window_id === this._focusedWindowId(focused)) return -1;
      if (b.window_id === this._focusedWindowId(focused)) return 1;
      return 0;
    });
    return JSON.stringify(entries);
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