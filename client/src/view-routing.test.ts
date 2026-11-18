import { describe, expect, it } from "vitest";
import { pathForView, viewFromPath } from "./view-routing";

describe("view routing", () => {
  it.each([
    ["/", "deck"],
    ["/trackpad", "trackpad"],
    ["/settings", "settings"],
    ["/now-playing", "nowplaying"],
    ["/editor", "editor"],
    ["/windows", "windows"],
    ["/help", "help"],
  ] as const)("maps %s to %s", (path, view) => {
    expect(viewFromPath(path)).toBe(view);
    expect(pathForView(view)).toBe(path);
  });

  it("falls back unknown paths to the deck", () => {
    expect(viewFromPath("/not-a-page")).toBe("deck");
  });

  // Served under a sub-path (GitHub Pages: /deckd/app/), every view lives
  // beneath the base, and paths outside it aren't views.
  describe("under a base path", () => {
    const base = "/deckd/app/";

    it.each([
      ["/deckd/app/", "deck"],
      ["/deckd/app/trackpad", "trackpad"],
      ["/deckd/app/now-playing", "nowplaying"],
      ["/deckd/app/help", "help"],
    ] as const)("maps %s to %s", (path, view) => {
      expect(viewFromPath(path, base)).toBe(view);
      expect(pathForView(view, base)).toBe(path);
    });

    it("treats the base without its trailing slash as the deck", () => {
      expect(viewFromPath("/deckd/app", base)).toBe("deck");
    });

    it("doesn't read a root-level path as a view", () => {
      expect(viewFromPath("/trackpad", base)).toBe("deck");
    });
  });
});
