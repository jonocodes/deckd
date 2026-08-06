import { describe, expect, it } from "vitest";
import { pathForView, viewFromPath } from "./view-routing";

describe("view routing", () => {
  it.each([
    ["/", "layout"],
    ["/trackpad", "trackpad"],
    ["/settings", "settings"],
    ["/media-browser", "mediabrowser"],
    ["/editor", "editor"],
    ["/windows", "windows"],
  ] as const)("maps %s to %s", (path, view) => {
    expect(viewFromPath(path)).toBe(view);
    expect(pathForView(view)).toBe(path);
  });

  it("falls back unknown paths to the layout", () => {
    expect(viewFromPath("/not-a-page")).toBe("layout");
  });
});
