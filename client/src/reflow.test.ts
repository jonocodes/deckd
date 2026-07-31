import { describe, expect, it } from "vitest";

import { computeReflow } from "./reflow";

const TARGET = 96;
const GAP = 8;

describe("computeReflow — clip", () => {
  it("fits fewer columns as the viewport narrows", () => {
    const narrow = computeReflow({ cellSize: TARGET, gap: GAP, containerWidth: 300, containerHeight: 800, totalUnits: 8, mode: "clip" });
    const wide = computeReflow({ cellSize: TARGET, gap: GAP, containerWidth: 1000, containerHeight: 800, totalUnits: 8, mode: "clip" });
    expect(narrow.cols).toBe(2); // floor(308/104) = 2
    expect(wide.cols).toBeGreaterThan(narrow.cols);
  });

  it("always yields at least one column, even below the floor", () => {
    const tiny = computeReflow({ cellSize: TARGET, gap: GAP, containerWidth: 40, containerHeight: 800, totalUnits: 4, mode: "clip" });
    expect(tiny.cols).toBe(1);
  });

  it("cells grow when fewer columns fit (no explicit max cap)", () => {
    const r = computeReflow({ cellSize: TARGET, gap: GAP, containerWidth: 150, containerHeight: 800, totalUnits: 4, mode: "clip" });
    expect(r.cols).toBe(1);
    expect(r.cellPx).toBe(150);
  });

  it("ignores height in clip mode", () => {
    const short = computeReflow({ cellSize: TARGET, gap: GAP, containerWidth: 300, containerHeight: 50, totalUnits: 30, mode: "clip" });
    const tall = computeReflow({ cellSize: TARGET, gap: GAP, containerWidth: 300, containerHeight: 5000, totalUnits: 30, mode: "clip" });
    expect(short).toEqual(tall);
  });
});

describe("computeReflow — even-row scan", () => {
  it("8 widgets at 5 target cols → scan to 4 (4×2)", () => {
    // cellSize=72, width=394: floor(402/80)=5. 5→4 gives even 4×2, 5+3 is ragged.
    const r = computeReflow({ cellSize: 72, gap: 8, containerWidth: 394, containerHeight: 800, totalUnits: 8, mode: "clip" });
    expect(r.cols).toBe(4);
  });

  it("8 widgets at 3 target cols → stays 3 (2 blocked by w/3 cap, scan only goes down)", () => {
    // cellSize=100, portrait 360: target=3. c=2: perfect but 176px > w/3=120 → skip.
    const r = computeReflow({ cellSize: 100, gap: 8, containerWidth: 360, containerHeight: 668, totalUnits: 8, mode: "clip" });
    expect(r.cols).toBe(3);
  });

  it("6 widgets at 4 target cols → scan to 3 (3×2)", () => {
    // cellSize=72, width=314: floor(322/80)=4. 4→3 gives even 3×2.
    const r = computeReflow({ cellSize: 72, gap: 8, containerWidth: 314, containerHeight: 800, totalUnits: 6, mode: "clip" });
    expect(r.cols).toBe(3);
  });

  it("7 widgets at 6 target cols → best candidate is 4 (4+3, not 6+1)", () => {
    // cellSize=100, width=747: target=floor(755/108)=6. Score(6)=2 (ragged 6+1).
    // Candidates: 5 (score 2), 4 (score 1: 3≥2 half-full, rows=2), 3 (score 2),
    // 2 (score 1 but cellPx=370 > 200 cap). Best: 4.
    const r = computeReflow({ cellSize: 100, gap: 8, containerWidth: 747, containerHeight: 300, totalUnits: 7, mode: "clip" });
    expect(r.cols).toBe(4);
  });

  it("7 widgets at 3 target cols → stays at 3 (2 would be 176px, w/3 cap blocks it)", () => {
    const r = computeReflow({ cellSize: 100, gap: 8, containerWidth: 360, containerHeight: 800, totalUnits: 7, mode: "clip" });
    expect(r.cols).toBe(3);
  });
});

describe("computeReflow — shrink-to-fit", () => {
  it("adds columns so all widgets fit a short viewport", () => {
    const clip = computeReflow({ cellSize: TARGET, gap: GAP, containerWidth: 300, containerHeight: 120, totalUnits: 12, mode: "clip" });
    const fit = computeReflow({ cellSize: TARGET, gap: GAP, containerWidth: 300, containerHeight: 120, totalUnits: 12, mode: "shrink-to-fit" });
    expect(fit.cols).toBeGreaterThan(clip.cols);
    const rows = Math.ceil(12 / fit.cols);
    expect(rows * fit.cellPx + (rows - 1) * GAP).toBeLessThanOrEqual(120 + 1e-6);
  });

  it("allows cells below the hard floor to fit everything", () => {
    const fit = computeReflow({ cellSize: TARGET, gap: GAP, containerWidth: 300, containerHeight: 90, totalUnits: 20, mode: "shrink-to-fit" });
    expect(fit.cellPx).toBeLessThan(TARGET);
    expect(fit.cellPx).toBeGreaterThanOrEqual(16);
  });

  it("matches clip when the content already fits the height", () => {
    const clip = computeReflow({ cellSize: TARGET, gap: GAP, containerWidth: 300, containerHeight: 2000, totalUnits: 6, mode: "clip" });
    const fit = computeReflow({ cellSize: TARGET, gap: GAP, containerWidth: 300, containerHeight: 2000, totalUnits: 6, mode: "shrink-to-fit" });
    expect(fit).toEqual(clip);
  });
});
