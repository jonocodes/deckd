import * as simpleIcons from "simple-icons";
import { describe, expect, it } from "vitest";
import { DESKTOP_ICONS } from "./nowplaying-icons";

describe("now-playing desktop-entry icons", () => {
  it("maps every player to a Simple Icons slug that exists", () => {
    // A slug that doesn't exist renders the missing-icon placeholder in
    // the art slot instead of falling back to the disc glyph.
    const slugs = new Set(Object.values(simpleIcons).map((icon) => icon.slug));
    const missing = Object.entries(DESKTOP_ICONS).filter(([, icon]) => !slugs.has(icon.name));
    expect(missing).toEqual([]);
  });
});
