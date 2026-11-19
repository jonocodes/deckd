import { describe, expect, it } from "vitest";
import { demoLanding } from "./demo-landing";

describe("demo landing (GitHub Pages build)", () => {
  const target = "/deckd/demo/";

  it("forwards a visit with nothing to show to the demo page", () => {
    expect(demoLanding("", target)).toBe(target);
  });

  it("leaves demo, playground and pinned-deck links alone", () => {
    expect(demoLanding("?demo=firefox", target)).toBeNull();
    expect(demoLanding("?playground", target)).toBeNull();
    expect(demoLanding("?deck=youtube", target)).toBeNull();
  });

  it("does nothing outside the Pages build (no target configured)", () => {
    expect(demoLanding("", undefined)).toBeNull();
    expect(demoLanding("", "")).toBeNull();
  });
});
