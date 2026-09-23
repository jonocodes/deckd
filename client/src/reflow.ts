/** Reflow geometry (ADR-0011).
 *
 * The grid has no authored shape. Widgets pack in list order, and the client
 * derives the whole layout from the measured container in three stages, each
 * consuming exactly one piece of configuration:
 *
 *   1. CAPACITY      minCell + viewport -> how many cells are VISIBLE
 *   2. SHAPE         visible count      -> column count + resolved cell size
 *   3. DISTRIBUTION  cols               -> fill rows, remainder at the bottom
 *
 * Stage 2 takes no configuration at all: it is pure arithmetic on the
 * viewport, and the row count is its only free variable. Stage 3 is ordinary
 * text-style wrapping, which CSS grid auto-placement already performs — so
 * this module only has to produce the column count and cell size.
 *
 * Kept side-effect-free (no DOM, no React) so the geometry is unit testable in
 * isolation. ``ButtonGrid`` feeds it live ``ResizeObserver`` measurements. */

export type OverflowMode = "clip" | "shrink-to-fit";

export type ReflowInput = {
  /** Inner width of the grid area, in CSS pixels. */
  containerWidth: number;
  /** Inner height of the grid area, in CSS pixels. */
  containerHeight: number;
  /** Readability floor (device preference): the smallest cell the user is
   * willing to accept. Under ``clip`` this is a hard promise — the visible
   * set is trimmed until every cell can meet it. Under ``shrink-to-fit`` it
   * is never consulted, because nothing is ever trimmed. */
  minCell: number;
  /** Comfort cap (device preference): stops two widgets on a 4K panel from
   * becoming two enormous buttons. */
  maxCell: number;
  /** Gap between cells, in CSS pixels (matches the CSS ``gap``). */
  gap: number;
  /** Total occupied cells, counting spans (sum of ``w*h`` over flow widgets). */
  totalUnits: number;
  mode: OverflowMode;
};

export type ReflowResult = {
  /** Columns to render (``grid-template-columns: repeat(cols, cellPx)``). */
  cols: number;
  /** Rows the visible units occupy at ``cols``. */
  rows: number;
  /** Resolved square cell edge in CSS pixels. */
  cellPx: number;
  /** Units that fit. Equals ``totalUnits`` under ``shrink-to-fit``. */
  visibleUnits: number;
  /** Units trimmed by ``clip``. Always 0 under ``shrink-to-fit``. */
  hiddenUnits: number;
};

/** Absolute floor so a pathological viewport can't drive cells to zero (or
 * negative) size. Below this nothing is tappable anyway. */
export const HARD_FLOOR = 16;

/** How many whole cells of edge ``minCell`` the viewport holds at all.
 *
 * Whole ``cols * rows`` deliberately: it is what lets ``clip`` show complete
 * cells rather than slicing a row at the fold, which is what ADR-0010's
 * CSS-only ``overflow: hidden`` did. */
export function capacityUnits(
  containerWidth: number,
  containerHeight: number,
  minCell: number,
  gap: number,
): number {
  const pitch = minCell + gap;
  if (pitch <= 0) return 0;
  const cols = Math.floor((containerWidth + gap) / pitch);
  const rows = Math.floor((containerHeight + gap) / pitch);
  return Math.max(0, cols) * Math.max(0, rows);
}

/** Split ``visibleUnits`` into rows of at most ``cols``, filling each row left
 * to right so the remainder lands in the bottom row alone (ADR-0011 stage 3).
 * Returns one count per non-empty row: 10 units at 3 columns -> ``[3, 3, 3, 1]``.
 *
 * The renderer gets this for free from CSS grid auto-placement (``ButtonGrid``
 * just hands ``cols`` to ``grid-template-columns``). This helper exists so
 * surfaces that draw their own rectangles — the user-facing help page — can
 * report the row shape without re-deriving a rule the layout already owns. */
export function fillRows(visibleUnits: number, cols: number): number[] {
  const units = Math.max(0, Math.floor(visibleUnits));
  const perRow = Math.max(1, Math.floor(cols));
  const rows: number[] = [];
  for (let left = units; left > 0; left -= perRow) rows.push(Math.min(perRow, left));
  return rows;
}

type Shape = { cols: number; rows: number; cell: number };

/** Choose the row count that makes cells largest, and report the column count
 * and cell edge that follow from it.
 *
 * The dominance prune is load-bearing, not an optimisation: skipping the ``R``
 * whose columns would already hold every unit in ``R - 1`` rows is exactly
 * what keeps the candidate set closed under ``(rows, cols) -> (cols, rows)``,
 * so a portrait grid and its landscape counterpart resolve consistently. It
 * also guarantees plain fill-wrapping yields exactly ``R`` non-empty rows. */
function bestShape(
  units: number,
  width: number,
  height: number,
  gap: number,
  maxCell: number,
): Shape | null {
  if (units <= 0 || width <= 0 || height <= 0) return null;
  const aspect = width / height;
  // How far a candidate's grid shape sits from the container's shape. Only
  // consulted to break ties, which happen once ``maxCell`` clamps several
  // candidates to the same size.
  const shapeErr = (cols: number, rows: number) =>
    Math.abs(Math.log(cols / rows / aspect));

  let best: Shape | null = null;
  let bestErr = Infinity;
  for (let rows = 1; rows <= units; rows++) {
    const cols = Math.ceil(units / rows);
    if ((rows - 1) * cols >= units) continue; // dominated by `rows - 1`
    const byWidth = (width - (cols - 1) * gap) / cols;
    const byHeight = (height - (rows - 1) * gap) / rows;
    const cell = Math.min(byWidth, byHeight);
    if (cell <= 0) continue;
    const err = shapeErr(cols, rows);
    if (
      best === null ||
      Math.min(cell, maxCell) - Math.min(best.cell, maxCell) > 1e-9 ||
      (Math.abs(Math.min(cell, maxCell) - Math.min(best.cell, maxCell)) <= 1e-9 && err < bestErr)
    ) {
      best = { cols, rows, cell };
      bestErr = err;
    }
  }
  return best;
}

export function computeReflow(input: ReflowInput): ReflowResult {
  const { containerWidth, containerHeight, minCell, maxCell, gap, totalUnits, mode } = input;
  const units = Math.max(0, totalUnits);
  // Not measured yet (first paint, or no ResizeObserver): report everything as
  // visible at zero size rather than trimming to nothing. Trimming is a
  // decision that needs a measurement, and reporting nothing visible would
  // blank the surface for a frame — or forever, in a host without a
  // ResizeObserver.
  if (units === 0 || containerWidth <= 0 || containerHeight <= 0) {
    return { cols: 1, rows: units, cellPx: 0, visibleUnits: units, hiddenUnits: 0 };
  }

  // Stage 1. ``shrink-to-fit`` never trims, so it never consults capacity —
  // and therefore never consults ``minCell`` either. ``clip`` trims to whole
  // cells that can honour the floor, but always shows at least one widget so a
  // hostile viewport can't blank the surface entirely.
  const visibleUnits =
    mode === "shrink-to-fit"
      ? units
      : Math.min(units, Math.max(1, capacityUnits(containerWidth, containerHeight, minCell, gap)));

  // Stage 2.
  const shape = bestShape(visibleUnits, containerWidth, containerHeight, gap, maxCell);
  if (shape === null) return { cols: 1, rows: units, cellPx: 0, visibleUnits: units, hiddenUnits: 0 };

  return {
    cols: shape.cols,
    rows: shape.rows,
    cellPx: Math.max(HARD_FLOOR, Math.min(shape.cell, maxCell)),
    visibleUnits,
    hiddenUnits: units - visibleUnits,
  };
}
