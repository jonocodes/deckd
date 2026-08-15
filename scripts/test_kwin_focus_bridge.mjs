// Contract test for the KWin focus/window bridge (#31, #133).
//
// The KWin script runs inside KWin's QJSEngine, which — unlike GNOME's GJS —
// has NO ES module loader, so the script can't be split into an importable
// pure module the way the GNOME extension factors out wire-shape.js. Instead
// we test the REAL packaging/kwin-script/.../main.js by evaluating it in a
// node:vm sandbox that supplies fakes for the KWin globals it touches
// (workspace, callDBus, QTimer, console), then assert on:
//   * the initial UpdateActiveWindow + UpdateWindowList pushes,
//   * the per-window enumeration wire shape (matches the GNOME window shape),
//   * the taskbar/resourceClass filter (panels excluded),
//   * focused-first ordering,
//   * the QTimer raise poll: a DrainPendingRaises reply activates the
//     matching window via workspace.activeWindow.
//
// This is the KDE counterpart of scripts/test_focus_wire_shape.mjs and runs
// in the same `just test` step — no compositor required.

import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const SOURCE = fs.readFileSync(
  new URL("../packaging/kwin-script/deckd-focus/contents/code/main.js", import.meta.url),
  "utf8",
);

// --- KWin global fakes ---------------------------------------------------

function makeSignal() {
  const handlers = [];
  return {
    connect: (fn) => handlers.push(fn),
    emit: (...args) => handlers.forEach((h) => h(...args)),
  };
}

// A fake KWin::Window. `id` stands in for the QUuid internalId; the script
// stringifies it into the opaque window_id.
function fakeWindow(id, resourceClass, caption, opts = {}) {
  return {
    internalId: id,
    resourceClass,
    caption,
    desktopFileName: opts.desktopFileName ?? "",
    pid: opts.pid ?? 1000,
    minimized: opts.minimized ?? false,
    skipTaskbar: opts.skipTaskbar ?? false,
    desktops: opts.desktops ?? [{x11DesktopNumber: 1}],
    captionChanged: makeSignal(),
    minimizedChanged: makeSignal(),
    desktopsChanged: makeSignal(),
  };
}

// Build the sandbox and evaluate main.js in it. Returns handles for driving
// signals and inspecting captured D-Bus traffic.
function loadBridge(windows, activeIndex) {
  const dbusPushes = []; // {method, payload}
  let pendingRaiseReply = "[]";
  let timerHandler = null;
  let activeWindow = windows[activeIndex] ?? null;
  const activatedTo = [];

  function callDBus(...args) {
    const method = args[3];
    const last = args[args.length - 1];
    if (typeof last === "function") {
      // reply-callback form — DrainPendingRaises
      last(pendingRaiseReply);
      return;
    }
    dbusPushes.push({method, payload: args[4]});
  }

  class QTimer {
    constructor() {
      this.interval = 0;
      this.timeout = {connect: (fn) => (timerHandler = fn)};
    }
    start() {
      this.started = true;
    }
  }

  const workspace = {
    windowList: () => windows,
    get activeWindow() {
      return activeWindow;
    },
    set activeWindow(win) {
      activeWindow = win;
      activatedTo.push(win);
    },
    windowActivated: makeSignal(),
    windowAdded: makeSignal(),
    windowRemoved: makeSignal(),
  };

  const sandbox = {workspace, callDBus, QTimer, console: {error: () => {}, log: () => {}}};
  vm.createContext(sandbox);
  vm.runInContext(SOURCE, sandbox);

  return {
    dbusPushes,
    workspace,
    activatedTo,
    tick: () => timerHandler(),
    // Move focus the way KWin would (updates activeWindow) WITHOUT
    // recording to activatedTo, which is reserved for script-driven raises.
    setActive: (win) => (activeWindow = win),
    setRaiseReply: (r) => (pendingRaiseReply = r),
    lastPush: (method) => [...dbusPushes].reverse().find((c) => c.method === method),
  };
}

// --- Fixtures ------------------------------------------------------------

const dolphin = fakeWindow("w-dolphin", "dolphin", "Dolphin — Home", {
  desktopFileName: "org.kde.dolphin",
});
const firefox = fakeWindow("w-firefox", "firefox", "deckd — GitHub", {
  desktopFileName: "org.mozilla.firefox",
  minimized: true,
  desktops: [{x11DesktopNumber: 2}],
});
const panel = fakeWindow("w-panel", "plasmashell", "Panel", {skipTaskbar: true});
// A classless-but-taskbar-visible window: GNOME's ListWindows lists such a
// window (wm_class null), so the KDE bridge must too — skipTaskbar, not
// resourceClass, is the filter. This locks that parity decision.
const classless = fakeWindow("w-none", "", "Some Dialog");

const windows = [dolphin, firefox, panel, classless];
const bridge = loadBridge(windows, /* active */ 1 /* firefox */);

// --- 1. Initial pushes ---------------------------------------------------

const activePush = bridge.lastPush("UpdateActiveWindow");
assert.ok(activePush, "expected an UpdateActiveWindow push on load");
assert.deepEqual(JSON.parse(activePush.payload), {
  app_id: "org.mozilla.firefox", // desktopFileName → app_id (active-window shape)
  wm_class: "firefox",
  title: "deckd — GitHub",
  pid: 1000,
  uuid: "w-firefox",
});

const listPush = bridge.lastPush("UpdateWindowList");
assert.ok(listPush, "expected an UpdateWindowList push on load");
const list = JSON.parse(listPush.payload);

// --- 2. Filtering: only skipTaskbar (panels) excluded; focused-first -----

assert.deepEqual(
  list.map((w) => w.window_id),
  ["w-firefox", "w-dolphin", "w-none"],
  "taskbar-visible windows only (panel dropped), focused (firefox) first",
);

// The classless window is listed with wm_class null — GNOME-parity
// inclusiveness, not silently dropped.
const classlessEntry = list.find((w) => w.window_id === "w-none");
assert.equal(classlessEntry.wm_class, null);
assert.equal(classlessEntry.title, "Some Dialog");

// --- 3. Per-window wire shape (matches _window_info_from_payload keys) ----

const firefoxEntry = list.find((w) => w.window_id === "w-firefox");
assert.deepEqual(firefoxEntry, {
  window_id: "w-firefox",
  wm_class: "firefox",
  gtk_application_id: null,
  sandboxed_app_id: "org.mozilla.firefox", // desktopFileName → sandboxed_app_id
  app_name: null,
  title: "deckd — GitHub",
  workspace: 1, // x11DesktopNumber 2 → 0-based 1, matching GNOME's index
  minimized: true,
});
const dolphinEntry = list.find((w) => w.window_id === "w-dolphin");
assert.equal(dolphinEntry.minimized, false);
assert.equal(dolphinEntry.workspace, 0); // x11DesktopNumber 1 → 0-based 0

// --- 4. Re-push on focus change, focused-first reorders ------------------

// KWin moves focus (activeWindow) and fires windowActivated together.
bridge.setActive(dolphin);
bridge.workspace.windowActivated.emit(dolphin);
const reordered = JSON.parse(bridge.lastPush("UpdateWindowList").payload);
assert.deepEqual(
  reordered.map((w) => w.window_id),
  ["w-dolphin", "w-firefox", "w-none"],
  "windowActivated re-pushes the list, now focused-first on dolphin",
);

// --- 5. Raise poll: a DrainPendingRaises reply activates the window ------

bridge.setRaiseReply(JSON.stringify(["w-dolphin"]));
bridge.tick();
assert.equal(
  bridge.activatedTo[bridge.activatedTo.length - 1],
  dolphin,
  "a queued raise id activates the matching window via workspace.activeWindow",
);

// A retired id (not in windowList) is a silent no-op, not a throw.
const before = bridge.activatedTo.length;
bridge.setRaiseReply(JSON.stringify(["w-gone"]));
bridge.tick();
assert.equal(bridge.activatedTo.length, before, "unknown raise id is dropped silently");

// An empty queue does nothing.
bridge.setRaiseReply("[]");
bridge.tick();
assert.equal(bridge.activatedTo.length, before, "empty raise queue is a no-op");

console.log("kwin-focus-bridge: all assertions passed");
