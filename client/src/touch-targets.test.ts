/** Touch-target CSS guard (issue #61).
 *
 * The real proof is the browser measurement in
 * ``e2e/touch-targets.spec.ts``. This unit test locks the stylesheet
 * down so a later refactor can't silently drop a 44px hit-area floor
 * or collapse the inter-control spacing below the 8px minimum — the
 * exact regressions the ticket's acceptance criteria name.
 *
 * jsdom doesn't compute layout or apply the responsive sizing that
 * makes these floors necessary, so we assert against the CSS text
 * (same approach as ``a11y-css.test.ts``).
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const css = readFileSync(resolve(__dirname, "style.css"), "utf8");

/** Body of the first rule whose selector starts with ``selector``. */
function ruleBody(selector: string): string {
  const match = css.match(new RegExp(`${selector}\\s*\\{([^}]*)\\}`, "s"));
  if (!match) throw new Error(`CSS rule not found: ${selector}`);
  return match[1];
}

describe("Touch targets — issue #61", () => {
  it("chrome buttons keep a 44x44 hit area regardless of glyph size", () => {
    const btn = ruleBody("\\.chrome-btn");
    expect(btn).toMatch(/min-width:\s*44px/);
    expect(btn).toMatch(/min-height:\s*44px/);
    // Inline-flex keeps the glyph centred in the expanded box.
    expect(btn).toMatch(/display:\s*inline-flex/);
  });

  it("keeps at least 8px between adjacent bottom-chrome controls", () => {
    expect(ruleBody("\\.chrome-bottom")).toMatch(/gap:\s*max\(8px/);
  });

  it("keeps at least 8px between controls on the manual control surface", () => {
    const strip = ruleBody("\\.kbd-strip");
    expect(strip).toMatch(/gap:\s*8px/);
    // A fixed 4x2 grid, so the arrows never split across rows.
    expect(strip).toMatch(/display:\s*grid/);
    expect(strip).toMatch(/grid-template-columns:\s*repeat\(4/);
    expect(ruleBody("\\.kbd-strip-btn")).toMatch(/min-width:\s*44px/);
  });

  it("gives settings sliders a 44px tall tap area with a thin visible track", () => {
    expect(ruleBody("\\.slider")).toMatch(/height:\s*44px/);
    expect(ruleBody("\\.slider")).toMatch(/background:\s*transparent/);
    expect(css).toMatch(/\.slider::-webkit-slider-runnable-track\s*\{[^}]*height:\s*6px/s);
    expect(css).toMatch(/\.slider::-moz-range-track\s*\{[^}]*height:\s*6px/s);
  });

  it("gives settings toggles a 44px hit area", () => {
    expect(ruleBody("\\.toggle")).toMatch(/height:\s*44px/);
  });

  it("gives the remaining settings controls a 44px minimum height", () => {
    expect(ruleBody("\\.settings-choice-option")).toMatch(/min-height:\s*44px/);
    expect(ruleBody("\\.settings-help-link")).toMatch(/min-height:\s*44px/);
    expect(ruleBody("\\.settings-logout")).toMatch(/min-height:\s*44px/);
  });

  it("gives the chrome jogstrip a 44px minimum width", () => {
    expect(ruleBody("\\.chrome-jogstrip")).toMatch(/min-width:\s*44px/);
  });

  it("gives now-playing transport buttons a 44x44 hit area", () => {
    expect(ruleBody("\\.nowplaying-skip")).toMatch(/width:\s*44px/);
    expect(ruleBody("\\.nowplaying-skip")).toMatch(/height:\s*44px/);
    expect(ruleBody("\\.nowplaying-play")).toMatch(/width:\s*44px/);
    expect(ruleBody("\\.nowplaying-play")).toMatch(/height:\s*44px/);
  });

  it("gives the media-cell transport controls a 44x44 hit area", () => {
    const skip = ruleBody("\\.media-skip");
    expect(skip).toMatch(/min-width:\s*44px/);
    expect(skip).toMatch(/min-height:\s*44px/);
    expect(ruleBody("\\.media-speed button")).toMatch(/min-width:\s*44px/);
    expect(ruleBody("\\.media-speed button")).toMatch(/min-height:\s*44px/);
    expect(ruleBody("\\.media-volume-fallback button")).toMatch(/min-width:\s*44px/);
    expect(ruleBody("\\.media-volume-fallback button")).toMatch(/min-height:\s*44px/);
  });
});
