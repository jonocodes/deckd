import assert from "node:assert/strict";
import fs from "node:fs";
import {activeWindowPayload, resolveWindowActors, windowPayload} from "../packaging/gnome-shell/deckd-focus@local/wire-shape.js";

const fixture = JSON.parse(fs.readFileSync(new URL("../tests/fixtures/focus-wire.json", import.meta.url)));
const schema = JSON.parse(fs.readFileSync(new URL("../tests/fixtures/focus-wire.schema.json", import.meta.url)));

function assertSchemaShape(value, definition) {
  assert.deepEqual(Object.keys(value).sort(), definition.required.slice().sort());
  for (const [key, property] of Object.entries(definition.properties)) {
    const actual = value[key];
    const types = Array.isArray(property.type) ? property.type : [property.type];
    const valid = types.some((type) =>
      type === "null" ? actual === null : type === "string" ? typeof actual === "string" :
        type === "boolean" ? typeof actual === "boolean" : Number.isInteger(actual));
    assert.equal(valid, true, `${key} has the wrong type`);
  }
}

const callOrNull = (object, method) => {
  if (!object || typeof object[method] !== "function") return null;
  const value = object[method]();
  return value === undefined ? null : value;
};
const window = {
  get_id: () => 42,
  get_wm_class: () => "firefox",
  get_gtk_application_id: () => "org.mozilla.firefox",
  get_title: () => "YouTube - Mozilla Firefox",
  get_pid: () => 4242,
  get_workspace: () => ({index: 1}),
  minimized: () => false,
  get_app: () => ({get_name: () => "Firefox"}),
};

const active = activeWindowPayload(window, callOrNull);
const entry = windowPayload(window, callOrNull, () => "org.mozilla.Firefox");
assert.deepEqual(active, fixture.active_window);
assert.deepEqual(entry, fixture.window);
assertSchemaShape(active, schema.$defs.active_window);
assertSchemaShape(entry, schema.$defs.window);

// resolveWindowActors: enumeration-source selection + loud-fail on a missing
// API (#128). The daemon polls ListWindows() at the focus cadence, so a
// missing accessor must degrade to [] rather than throw — but not silently.
const actorsA = [{tag: "a"}];
const actorsB = [{tag: "b"}];

// Preferred path: Shell ``global.get_window_actors()``.
let missedGlobal = null;
const globalWithShellAccessor = {
  get_window_actors: () => actorsA,
  display: {get_window_actors: () => actorsB},
};
assert.deepEqual(
  resolveWindowActors(globalWithShellAccessor, () => {missedGlobal = "warned";}),
  actorsA,
  "prefers global.get_window_actors()",
);
assert.equal(missedGlobal, null, "no warning when the preferred accessor exists");

// Fallback path: only ``global.display.get_window_actors()`` exists.
let missedFallback = null;
const globalWithDisplayAccessor = {display: {get_window_actors: () => actorsB}};
assert.deepEqual(
  resolveWindowActors(globalWithDisplayAccessor, () => {missedFallback = "warned";}),
  actorsB,
  "falls back to global.display.get_window_actors()",
);
assert.equal(missedFallback, null, "no warning when the fallback accessor exists");

// Neither accessor exists: return [] AND invoke the onMissing callback.
let missedCount = 0;
const globalWithNoAccessor = {display: {}};
assert.deepEqual(
  resolveWindowActors(globalWithNoAccessor, () => {missedCount += 1;}),
  [],
  "returns [] when no enumeration API is present",
);
assert.equal(missedCount, 1, "warns exactly once per call when the API is missing");
