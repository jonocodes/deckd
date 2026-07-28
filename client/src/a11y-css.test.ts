/** Tests for the accessibility CSS (issues #60 + #62).
 *
 * jsdom doesn't apply CSS media queries, so we can't drive
 * ``prefers-contrast`` / ``prefers-reduced-motion`` from JS. The
 * next-best thing is to lock the rules down: read the stylesheet
 * text and assert the AC-relevant selectors exist. A regression
 * here means the surface silently dropped the focus ring or the
 * reduced-motion fallback — the kind of breakage a user with the
 * OS accessibility setting enabled would see immediately.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(__dirname, "style.css"), "utf8");

describe("Accessibility CSS — issue #60", () => {
  it("defines a focus-visible ring on plain buttons", () => {
    expect(css).toMatch(/button:focus-visible\s*\{[^}]*box-shadow/s);
  });

  it("defines a focus-visible ring on the jogstrip and trackpad surfaces", () => {
    expect(css).toMatch(/\.cell-jogstrip:focus-visible/);
    expect(css).toMatch(/\.trackpad:focus-visible/);
  });

  it("thicker focus ring under prefers-contrast: more", () => {
    // The high-contrast override should push the focus ring wider
    // than the default — we look for any 5px+ ring inside the
    // ``prefers-contrast: more`` block.
    expect(css).toMatch(/@media \(prefers-contrast:\s*more\)/);
    expect(css).toMatch(/0\s+0\s+0\s+5px/);
  });
});

describe("Accessibility CSS — issue #62", () => {
  it("suppresses the connection pulse under prefers-reduced-motion", () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion:\s*reduce\)/);
    expect(css).toMatch(/connection-connecting \.connection-dot \{ animation: none/);
  });

  it("suppresses the chrome media playing-dot pulse under prefers-reduced-motion", () => {
    expect(css).toMatch(/chrome-btn-playing::after \{ animation: none/);
  });

  it("suppresses press-feedback transforms under prefers-reduced-motion", () => {
    // Without removing the static brightness feedback, the press
    // affordance still reads — just without the scale animation.
    expect(css).toMatch(/prefers-reduced-motion[\s\S]*?transform: none/);
  });

  it("bumps cell / chrome border widths under prefers-contrast: more", () => {
    expect(css).toMatch(/prefers-contrast:\s*more[\s\S]*?\.cell-button[\s\S]*?border-width:\s*2px/);
  });
});

describe("Accessibility CSS — issue #65", () => {
  it("defines larger controls: min 48x48 touch targets for chrome buttons", () => {
    expect(css).toMatch(/\.a11y-larger-controls[\s\S]*?\.chrome-btn[\s\S]*?min-width:\s*48px/);
    expect(css).toMatch(/\.a11y-larger-controls[\s\S]*?\.chrome-btn[\s\S]*?min-height:\s*48px/);
  });

  it("defines larger controls: min 48x48 touch targets for grid cell buttons", () => {
    expect(css).toMatch(/\.a11y-larger-controls[\s\S]*?\.cell-button[\s\S]*?min-width:\s*48px/);
    expect(css).toMatch(/\.a11y-larger-controls[\s\S]*?\.cell-button[\s\S]*?min-height:\s*48px/);
  });

  it("defines larger controls: larger slider thumb", () => {
    expect(css).toMatch(/\.a11y-larger-controls[\s\S]*?\.slider::-webkit-slider-thumb[\s\S]*?width:\s*32px/);
  });

  it("defines high contrast: thicker borders on cells and chrome", () => {
    expect(css).toMatch(/\.a11y-high-contrast[\s\S]*?\.cell-button[\s\S]*?border-width:\s*2px/);
    expect(css).toMatch(/\.a11y-high-contrast[\s\S]*?\.chrome-btn[\s\S]*?border-width:\s*2px/);
  });

  it("defines high contrast: thicker focus ring", () => {
    expect(css).toMatch(/\.a11y-high-contrast[\s\S]*?button:focus-visible[\s\S]*?box-shadow/);
  });

  it("defines reduce motion: suppresses connection pulse", () => {
    expect(css).toMatch(/\.a11y-reduce-motion[\s\S]*?connection-connecting \.connection-dot[\s\S]*?animation:\s*none/);
  });

  it("defines reduce motion: suppresses press transforms", () => {
    expect(css).toMatch(/\.a11y-reduce-motion[\s\S]*?transform:\s*none/);
  });
});