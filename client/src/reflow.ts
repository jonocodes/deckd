/** Ordered-list reflow geometry (ADR-0010).
 *
 * The grid has no authored shape: widgets pack in list order, left-to-right,
 * wrapping down, and the client computes how many columns fit the available
 * width against a client-side cell-size target. This module is the pure
 * geometry — given a measured container and the target, it yields the column
 * count and the resolved square cell size. ``ButtonGrid`` feeds it live
 * measurements from a ``ResizeObserver`` and turns the result into
 * ``grid-template-columns`` + a ``--cell-px`` content-sizing var.
 *
 * Kept side-effect-free (no DOM, no React) so the packing maths is unit
 * testable in isolation. */

export type OverflowMode = "clip" | "shrink-to-fit";

export type ReflowInput = {
  /** Inner width of the grid area, in CSS pixels. */
  containerWidth: number;
  /** Inner height of the grid area, in CSS pixels. Only consulted for
   * ``shrink-to-fit`` — ``clip`` never looks at height (it just clips). */
  containerHeight: number;
  /** Target square cell edge (CSS px). Columns are packed so the resolved
   * cell size stays near this value; exact-fit distributes leftover width
   * evenly (no separate max/cap — more columns simply fit as width grows). */
  cellSize: number;
  /** Gap between cells, in CSS pixels (matches the CSS ``gap``). */
  gap: number;
  /** Total occupied cells, counting spans (sum of ``w*h`` over flow widgets).
   * Used only by ``shrink-to-fit`` to estimate the row count. */
  totalUnits: number;
  mode: OverflowMode;
};

export type ReflowResult = {
  /** Number of columns to render (``grid-template-columns: repeat(cols, 1fr)``). */
  cols: number;
  /** Resolved square cell edge in CSS pixels, for ``--cell-px`` content sizing. */
  cellPx: number;
};

/** Absolute floor for ``shrink-to-fit`` so a pathological layout can't drive
 * cells to zero (or negative) size. */
const HARD_FLOOR = 16;

export function computeReflow(input: ReflowInput): ReflowResult {
  const { containerWidth, containerHeight, cellSize, gap, totalUnits, mode } = input;
  const w = Math.max(0, containerWidth);
  const targetPlusGap = cellSize + gap;

  // Columns that fit at the target cell size.
  const colsForWidth = (width: number) => Math.max(1, Math.floor((width + gap) / targetPlusGap));
  // Cell edge when ``cols`` columns share the width evenly (no leftover).
  const cellForCols = (cols: number) => (w - (cols - 1) * gap) / cols;

  let cols = colsForWidth(w);
  let cellPx = cellForCols(cols);

  // Reflow favours fewer columns (larger cells). Scan downward from the
  // target — never upward, since the user asked for fewer columns — and
  // pick the best: prefer perfectly even rows, then at-least-half-full
  // rows, then fewest total rows. The dynamic max-px cap is tighter on
  // narrow screens (prevents 2-col phone layouts) and looser on wide ones
  // (allows 4-col reflow of 7 widgets on a 747px screen).
  if (totalUnits > 0) {
    const rowsFor = (c: number) => Math.ceil(totalUnits / c);
    const fill = (c: number) => totalUnits % c || c;
    const score = (c: number): number => {
      if (totalUnits % c === 0) return 0;
      if (fill(c) >= Math.ceil(c / 2)) return 1;
      return 2;
    };
    const maxPx = Math.min(w / 3, Math.max(cellSize * 1.5, 200));
    let best = cols;
    let bestScore = score(cols);
    let bestRows = rowsFor(cols);
    for (let c = cols - 1; c >= 2; c--) {
      if (cellForCols(c) > maxPx) continue;
      const s = score(c);
      if (s > bestScore) continue;
      if (s < bestScore || rowsFor(c) < bestRows || (rowsFor(c) === bestRows && c < best)) {
        best = c; bestScore = s; bestRows = rowsFor(c);
      }
    }
    cols = best;
    cellPx = cellForCols(cols);
  }

  if (mode === "shrink-to-fit" && totalUnits > 0 && containerHeight > 0) {
    const rowsFor = (c: number) => Math.ceil(totalUnits / c);
    const fits = (c: number, px: number) => {
      const rows = rowsFor(c);
      return rows * px + (rows - 1) * gap <= containerHeight;
    };
    // Add columns (which shrinks cells) until every widget fits the height,
    // or everything is packed into a single row.
    while (!fits(cols, cellPx) && cols < totalUnits) {
      cols += 1;
      cellPx = cellForCols(cols);
    }
    // Even packed as wide as it goes it still overflows the height: clamp the
    // cell to the height budget so the last row is visible, honouring the
    // hard floor.
    if (!fits(cols, cellPx)) {
      const rows = rowsFor(cols);
      cellPx = Math.min(cellPx, (containerHeight - (rows - 1) * gap) / rows);
    }
    cellPx = Math.max(HARD_FLOOR, cellPx);
  }

  return { cols, cellPx: Math.max(0, cellPx) };
}
