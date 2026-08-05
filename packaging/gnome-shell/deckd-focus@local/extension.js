import Gio from "gi://Gio";
import GLib from "gi://GLib";
import {Extension} from "resource:///org/gnome/shell/extensions/extension.js";

const BUS_NAME = "org.deckd.Focus";
const OBJECT_PATH = "/org/deckd/Focus";

const DBUS_XML = `
<node>
  <interface name="org.deckd.Focus">
    <method name="GetActiveWindow">
      <arg type="s" name="window_json" direction="out"/>
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

  _callOrNull(obj, method) {
    if (typeof obj[method] !== "function") return null;
    const value = obj[method]();
    return value === undefined ? null : value;
  }
}
