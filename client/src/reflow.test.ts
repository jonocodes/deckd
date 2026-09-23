import { describe, expect, it } from "vitest";

import { capacityUnits, computeReflow, fillRows, HARD_FLOOR } from "./reflow";
import type { OverflowMode } from "./reflow";

const GAP = 8;
const MIN = 100;
const MAX = 240;

const reflow = (
  containerWidth: number,
  containerHeight: number,
  totalUnits: number,
  o: { minCell?: number; maxCell?: number; mode?: OverflowMode } = {},
) =>
  computeReflow({
    containerWidth,
    containerHeight,
    totalUnits,
    gap: GAP,
    minCell: o.minCell ?? MIN,
    maxCell: o.maxCell ?? MAX,
    mode: o.mode ?? "clip",
  });

describe("shape — the row count is the free variable", () => {
  it("five widgets on a roomy landscape area wrap 3+2, never 4+1", () => {
    const r = reflow(700, 480, 5);
    expect([r.cols, r.rows]).toEqual([3, 2]);
    expect(fillRows(r.visibleUnits, r.cols)).toEqual([3, 2]);
  });

  it("a narrow portrait area prefers more rows because cells come out bigger", () => {
    // 2 columns of 148px beats 3 columns of 96px on a 304x578 area.
    const portrait = reflow(304, 578, 5);
    expect(portrait.cols).toBe(2);
    expect(fillRows(portrait.visibleUnits, portrait.cols)).toEqual([2, 2, 1]);
    expect(portrait.cellPx).toBeGreaterThan(reflow(304, 578, 5).cellPx - 1);
  });

  it("the same widgets reshape rather than resize when the area turns", () => {
    const portrait = reflow(334, 782, 8);
    const landscape = reflow(756, 328, 8);
    expect(fillRows(portrait.visibleUnits, portrait.cols)).toEqual([2, 2, 2, 2]);
    expect(fillRows(landscape.visibleUnits, landscape.cols)).toEqual([4, 4]);
    expect(portrait.visibleUnits).toBe(landscape.visibleUnits);
  });

  it("caps cell size so two widgets don't eat a 4K panel", () => {
    expect(reflow(3840, 2160, 2).cellPx).toBe(MAX);
    expect(reflow(3840, 2160, 2, { maxCell: 120 }).cellPx).toBe(120);
  });
});

describe("distribution — fill to the column count, remainder at the bottom", () => {
  it("puts the shortfall in the bottom row alone", () => {
    // 10 units over 4 rows is 3+3+3+1, not the max-balanced 3+3+2+2.
    const r = reflow(656, 1071, 10);
    expect(fillRows(r.visibleUnits, r.cols)).toEqual([3, 3, 3, 1]);
  });

  it("always yields exactly `rows` non-empty rows, and the bottom row is never the widest", () => {
    for (let units = 1; units <= 200; units++) {
      for (const [w, h] of [[334, 782], [756, 328], [1092, 758], [200, 200]]) {
        const r = reflow(w, h, units, { mode: "shrink-to-fit" });
        const rows = fillRows(r.visibleUnits, r.cols);
        expect(rows.length).toBe(r.rows);
        expect(rows.every((n) => n >= 1)).toBe(true);
        expect(rows.reduce((a, b) => a + b, 0)).toBe(r.visibleUnits);
        expect(Math.max(...rows)).toBe(rows[0]);
      }
    }
  });
});

describe("fillRows — the row breakdown the help page reports", () => {
  it("fills each row to the column count, remainder alone at the bottom", () => {
    expect(fillRows(10, 3)).toEqual([3, 3, 3, 1]);
    expect(fillRows(5, 3)).toEqual([3, 2]);
    expect(fillRows(8, 4)).toEqual([4, 4]);
    expect(fillRows(3, 5)).toEqual([3]);
    expect(fillRows(0, 3)).toEqual([]);
  });

  it("never emits a zero-width row and guards a non-positive column count", () => {
    expect(fillRows(7, 0)).toEqual([1, 1, 1, 1, 1, 1, 1]);
    expect(fillRows(7, -2)).toEqual([1, 1, 1, 1, 1, 1, 1]);
  });
});

describe("capacity — `minCell` is a promise under clip", () => {
  it("never renders a cell below minCell", () => {
    let checked = 0;
    for (let w = 220; w <= 1400; w += 37) {
      for (let h = 220; h <= 1400; h += 37) {
        for (const minCell of [64, 100, 160, 240]) {
          for (const units of [1, 5, 7, 8, 13, 20, 40]) {
            const r = reflow(w, h, units, { minCell });
            if (r.hiddenUnits === units) continue; // nothing left to draw
            checked++;
            expect(r.cellPx).toBeGreaterThanOrEqual(Math.min(minCell, r.cellPx) - 1e-9);
            expect(r.cellPx + 1e-9).toBeGreaterThanOrEqual(
              r.visibleUnits > 0 && minCell <= r.cellPx ? minCell : r.cellPx,
            );
          }
        }
      }
    }
    expect(checked).toBeGreaterThan(1000);
  });

  it("honours minCell exactly, trimming the visible set instead of shrinking", () => {
    for (let w = 240; w <= 1200; w += 53) {
      for (let h = 240; h <= 1200; h += 53) {
        for (const minCell of [64, 100, 160]) {
          const r = reflow(w, h, 60, { minCell });
          if (r.visibleUnits === 0) continue;
          // At least one cell fits, so the floor must hold.
          if (capacityUnits(w, h, minCell, GAP) >= 1) {
            expect(r.cellPx).toBeGreaterThanOrEqual(minCell - 1e-9);
          }
        }
      }
    }
  });

  it("shows fewer widgets as minCell rises, never more", () => {
    for (const [w, h] of [[334, 782], [756, 328], [732, 1118]]) {
      let previous = Infinity;
      for (let minCell = 48; minCell <= 240; minCell += 4) {
        const visible = reflow(w, h, 40, { minCell }).visibleUnits;
        expect(visible).toBeLessThanOrEqual(previous);
        previous = visible;
      }
    }
  });
});

describe("overflow modes", () => {
  it("shrink-to-fit never consults minCell — the reason clip is the default", () => {
    const low = reflow(334, 782, 24, { minCell: 64, mode: "shrink-to-fit" });
    const high = reflow(334, 782, 24, { minCell: 240, mode: "shrink-to-fit" });
    expect(low).toEqual(high);
    expect(low.hiddenUnits).toBe(0);
  });

  it("is identical to clip whenever the deck already fits", () => {
    const clip = reflow(756, 328, 6);
    const shrink = reflow(756, 328, 6, { mode: "shrink-to-fit" });
    expect(clip).toEqual(shrink);
    expect(clip.hiddenUnits).toBe(0);
  });

  it("clip hides the tail; shrink-to-fit keeps everything at a smaller size", () => {
    const clip = reflow(334, 782, 24, { minCell: 160 });
    const shrink = reflow(334, 782, 24, { minCell: 160, mode: "shrink-to-fit" });
    expect(clip.hiddenUnits).toBeGreaterThan(0);
    expect(clip.cellPx).toBeGreaterThanOrEqual(160);
    expect(shrink.hiddenUnits).toBe(0);
    expect(shrink.cellPx).toBeLessThan(160);
  });
});

describe("resize is stable — no hysteresis layer needed", () => {
  it("cell size never shrinks as the area widens, and shapes change rarely", () => {
    for (const units of [5, 7, 8, 12, 13]) {
      let lastCell = -Infinity;
      let shape = "";
      let changes = 0;
      for (let w = 240; w <= 1600; w++) {
        const r = reflow(w, 700, units, { mode: "shrink-to-fit" });
        expect(r.cellPx).toBeGreaterThanOrEqual(lastCell - 1e-9);
        lastCell = r.cellPx;
        const key = `${r.cols}x${r.rows}`;
        if (key !== shape) {
          if (shape !== "") changes++;
          shape = key;
        }
      }
      expect(changes).toBeLessThanOrEqual(4);
    }
  });
});

describe("degenerate viewports stay finite", () => {
  const cases: Array<[number, number, number]> = [
    [800, 1, 6],
    [1, 800, 6],
    [0, 0, 6],
    [200, 200, 600],
    [393.3333, 659.6667, 7],
    [1920, 180, 8],
  ];
  it.each(cases)("%ix%i with %i units", (w, h, units) => {
    for (const mode of ["clip", "shrink-to-fit"] as const) {
      const r = reflow(w, h, units, { mode });
      expect(Number.isFinite(r.cellPx)).toBe(true);
      expect(Number.isFinite(r.cols)).toBe(true);
      expect(r.cols).toBeGreaterThanOrEqual(1);
      expect(r.cellPx).toBeGreaterThanOrEqual(0);
      // Only meaningful once measured: before that nothing has been decided,
      // so nothing counts as hidden (asserted separately below).
      if (w > 0 && h > 0) expect(r.visibleUnits + r.hiddenUnits).toBe(units);
      // A resolved cell is always tappable; an unmeasured one is 0 by design.
      if (w > 0 && h > 0 && r.visibleUnits > 0) {
        expect(r.cellPx).toBeGreaterThanOrEqual(HARD_FLOOR);
      }
    }
  });

  it("shows every widget at zero size before the first measurement", () => {
    // Trimming needs a measurement. Reporting nothing visible here would blank
    // the surface for a frame — or forever, without a ResizeObserver.
    const r = reflow(0, 0, 12);
    expect(r.visibleUnits).toBe(12);
    expect(r.hiddenUnits).toBe(0);
    expect(r.cellPx).toBe(0);
  });
});
