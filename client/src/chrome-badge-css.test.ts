/** The app badge on a narrow (portrait-phone) bottom bar.
 *
 * jsdom can't evaluate container queries, so — like a11y-css.test.ts — pin
 * the rule in the stylesheet: below 430px a badge that has an icon collapses
 * to the icon (the name goes sr-only) instead of truncating to "Y…".
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "style.css"), "utf8");

describe("app badge on a narrow bottom bar", () => {
  it("collapses an icon badge to its icon inside the 430px container query", () => {
    const block = css.match(/@container \(max-width: 430px\) \{([\s\S]*?)\n\}/)?.[1] ?? "";
    expect(block).toMatch(/\.app-badge:has\(\.app-badge-icon\) \.app-badge-name/);
  });
});
