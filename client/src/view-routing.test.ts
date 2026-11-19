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

  // Served under a sub-path (GitHub Pages: /deckd/demo/client/), every view lives
  // beneath the base, and paths outside it aren't views.
  describe("under a base path", () => {
    const base = "/deckd/demo/client/";

    it.each([
      ["/deckd/demo/client/", "deck"],
      ["/deckd/demo/client/trackpad", "trackpad"],
      ["/deckd/demo/client/now-playing", "nowplaying"],
      ["/deckd/demo/client/help", "help"],
    ] as const)("maps %s to %s", (path, view) => {
      expect(viewFromPath(path, base)).toBe(view);
      expect(pathForView(view, base)).toBe(path);
    });

    it("treats the base without its trailing slash as the deck", () => {
      expect(viewFromPath("/deckd/demo/client", base)).toBe("deck");
    });

    it("doesn't read a root-level path as a view", () => {
      expect(viewFromPath("/trackpad", base)).toBe("deck");
    });
  });
});
