import assert from "node:assert/strict";
import fs from "node:fs";
import {activeWindowPayload, windowPayload} from "../packaging/gnome-shell/deckd-focus@local/wire-shape.js";

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
