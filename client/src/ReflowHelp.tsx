/** User-facing explainer for how the button grid lays itself out (ADR-0011).
 *
 * This is a help surface, not a preview: it teaches the rule rather than
 * mirroring the user's screen. Their window is unstable (a browser can be
 * resized at any moment), so there is deliberately no device frame and no
 * chrome model — the diagrams show "the area your buttons live in", drawn at
 * an illustrative size.
 *
 * The geometry is not re-implemented. Every diagram calls the same
 * ``computeReflow`` that ``ButtonGrid`` uses, so the pictures cannot drift from
 * the product. The only thing this file owns is presentation, the interactive
 * sandbox, and the copy.
 *
 * Mounted two ways (one component, no second source of truth):
 *   - in-app as the ``help`` view (``/help``), opened from Settings;
 *   - standalone as ``help.html`` for a public, linkable page.
 * The standalone mount passes no ``onClose``/``onApply``, so the size sliders
 * are a sandbox you can't accidentally write to a device with. */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
  RefObject,
} from "react";

import { computeReflow, fillRows } from "./reflow";
import type { OverflowMode } from "./reflow";
import { CELL_SIZE_MAX, CELL_SIZE_MIN, CELL_SIZE_STEP } from "./settings-store";

/** Cell gap, in CSS pixels. Must match ``.grid { gap }`` in ``style.css`` /
 * ``GRID_GAP`` in ``ButtonGrid.tsx`` so the diagrams agree with the product. */
const GAP = 8;

/* --- sandbox bounds (in the drawing's own pixel space) ------------------- */
const BOX_MIN_W = 120;
const BOX_MAX_W = 360;
const BOX_MIN_H = 120;
const BOX_MAX_H = 420;
const BOX_DEFAULT_W = 240;
const BOX_DEFAULT_H = 340;
const COUNT_MIN = 1;
const COUNT_MAX = 40;
const COUNT_DEFAULT = 8;

/* --- illustration inputs. Fixed examples, so the pictures stay legible at
 * any setting; the sandbox above is the live one. Each is one props object so
 * the drawing and the caption that names its row shape cannot disagree. ---- */
const SHAPE_UNITS = 6;
const SHAPE_SCALE = 0.6;
const SHAPE_TALL: MiniGridProps = {
  width: 150, height: 210, units: SHAPE_UNITS, minCell: 48, maxCell: CELL_SIZE_MAX, mode: "shrink-to-fit",
};
const SHAPE_WIDE: MiniGridProps = {
  width: 210, height: 150, units: SHAPE_UNITS, minCell: 48, maxCell: CELL_SIZE_MAX, mode: "shrink-to-fit",
};

const OVERFLOW_UNITS = 12;
const OVERFLOW_MIN = 56;
const OVERFLOW_SCALE = 0.6;
const OVERFLOW_SHRINK: MiniGridProps = {
  width: 170, height: 230, units: OVERFLOW_UNITS, minCell: OVERFLOW_MIN, maxCell: CELL_SIZE_MAX, mode: "shrink-to-fit",
};
const OVERFLOW_CLIP: MiniGridProps = { ...OVERFLOW_SHRINK, mode: "clip" };

const DIST_UNITS = 10;
const DIST_SCALE = 0.6;
const DIST_GRID: MiniGridProps = {
  width: 200, height: 240, units: DIST_UNITS, minCell: 48, maxCell: CELL_SIZE_MAX, mode: "shrink-to-fit",
};
/** The row count the 10-button example lands at, read off the algorithm rather
 * than written down a second time. */
const DIST_ROWS = layoutOf(DIST_GRID).rows.length;

const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));

/** Max-balanced split (rows as even as possible), used only to name the
 * arrangement stage 3 deliberately does NOT produce: 10 in 4 rows is 3+3+3+1,
 * never 3+3+2+2. */
function balancedRows(units: number, rows: number): number[] {
  const base = Math.floor(units / rows);
  let extra = units % rows;
  return Array.from({ length: rows }, () => base + (extra-- > 0 ? 1 : 0));
}

export type ReflowHelpProps = {
  /** The device's current band, seeding the sandbox and detecting an edit. */
  minCell?: number;
  maxCell?: number;
  /** The resolved overflow policy, so the page can point at the diagram that
   * matches what this device actually does. */
  overflow?: OverflowMode;
  /** Apply the sandbox's edited band to this device. Absent on the standalone
   * page, where the controls are read-only. */
  onApply?: (next: { minCell: number; maxCell: number }) => void;
  /** Leave the page. In-app, this is the target of the close button — the
   * apply prompt fires first if the band was edited. Absent standalone. */
  onClose?: () => void;
};

type MiniGridProps = {
  /** Area the buttons live in, in the drawing's own pixels. */
  width: number;
  height: number;
  units: number;
  minCell: number;
  maxCell: number;
  mode: OverflowMode;
};

/** Run the real geometry for one diagram, and report its row breakdown — the
 * shared source for both the squares and the caption that names their shape. */
function layoutOf({ width, height, units, minCell, maxCell, mode }: MiniGridProps) {
  const result = computeReflow({
    containerWidth: width,
    containerHeight: height,
    minCell,
    maxCell,
    gap: GAP,
    totalUnits: units,
    mode,
  });
  return { ...result, rows: fillRows(result.visibleUnits, result.cols) };
}

/** A schematic grid: numbered squares, no icons, drawn with the real geometry.
 *
 * Uses the same fixed-track CSS grid as ``ButtonGrid`` — ``justify-content:
 * center`` centres the block while short rows wash left against it — so a
 * diagram is structurally identical to the surface. */
function MiniGrid({ width, height, ...rest }: MiniGridProps) {
  const { cols, cellPx, visibleUnits, rows } = layoutOf({ width, height, ...rest });
  const gridHeight = rows.length * cellPx + Math.max(0, rows.length - 1) * GAP;
  return (
    <div className="help-frame" style={{ width, height }} aria-hidden="true">
      <div
        className="help-grid"
        style={{
          gridTemplateColumns: `repeat(${cols}, ${cellPx}px)`,
          gridAutoRows: `${cellPx}px`,
          gap: `${GAP}px`,
          justifyContent: "center",
          alignContent: gridHeight <= height ? "center" : "start",
        }}
      >
        {Array.from({ length: visibleUnits }, (_, i) => (
          <div key={i} className={`help-cell${i === 0 ? " help-cell-first" : ""}`}>
            {i + 1}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Wraps a true-pixel ``MiniGrid`` and scales it down for display. Layout still
 * runs at the drawing's real size — only the pixels are shrunk — so a scaled
 * diagram is not a different geometry, just a smaller picture of the same one. */
function Diagram({
  width,
  height,
  scale,
  children,
}: {
  width: number;
  height: number;
  scale: number;
  children: ReactNode;
}) {
  return (
    <div
      className="help-diagram"
      style={{ width: Math.round(width * scale), height: Math.round(height * scale) }}
    >
      <div style={{ width, height, transform: `scale(${scale})`, transformOrigin: "top left" }}>
        {children}
      </div>
    </div>
  );
}

/** Track the sandbox stage's width so the drawing can shrink to fit a narrow
 * phone instead of overflowing. */
function useMeasuredWidth(): [RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const update = () => setWidth(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export function ReflowHelp({
  minCell = 100,
  maxCell = 240,
  overflow = "clip",
  onApply,
  onClose,
}: ReflowHelpProps) {
  const [stageRef, stageWidth] = useMeasuredWidth();

  const [draftMin, setDraftMinState] = useState(minCell);
  const [draftMax, setDraftMaxState] = useState(maxCell);
  const [count, setCount] = useState(COUNT_DEFAULT);
  const [boxW, setBoxW] = useState(BOX_DEFAULT_W);
  const [boxH, setBoxH] = useState(BOX_DEFAULT_H);
  const [asking, setAsking] = useState(false);

  // Latest-value refs so the clamp callbacks below don't need to be rebuilt on
  // every keystroke of the sliders.
  const draftMinRef = useRef(draftMin);
  const draftMaxRef = useRef(draftMax);
  draftMinRef.current = draftMin;
  draftMaxRef.current = draftMax;

  // Keep the draft ordered, exactly as ``useCellBand`` keeps the shipped band:
  // pushing the floor past the cap drags the cap along, and vice versa.
  const setDraftMin = useCallback((n: number) => {
    setDraftMinState(Math.min(n, draftMaxRef.current));
  }, []);
  const setDraftMax = useCallback((n: number) => {
    setDraftMaxState(Math.max(n, draftMinRef.current));
  }, []);

  const dirty = draftMin !== minCell || draftMax !== maxCell;

  // The drawing is scaled to the stage width so a 300px-wide box still fits a
  // narrow phone. Dragging divides the on-screen delta by the scale captured
  // at pointer-down (see below), so the box tracks the finger 1:1.
  const scale = stageWidth > 0 ? Math.min(1, stageWidth / boxW) : 1;

  const dragRef = useRef<{ x: number; y: number; w: number; h: number; scale: number } | null>(null);

  const onResizeStart = (e: ReactPointerEvent<HTMLButtonElement>) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY, w: boxW, h: boxH, scale };
  };
  const onResizeMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const d = dragRef.current;
    if (!d) return;
    const dw = Math.round((e.clientX - d.x) / d.scale);
    const dh = Math.round((e.clientY - d.y) / d.scale);
    setBoxW(clamp(d.w + dw, BOX_MIN_W, BOX_MAX_W));
    setBoxH(clamp(d.h + dh, BOX_MIN_H, BOX_MAX_H));
  };
  const onResizeEnd = (e: ReactPointerEvent<HTMLButtonElement>) => {
    dragRef.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };
  // Keyboard equivalent for the drag, so the sandbox isn't pointer-only.
  const onResizeKey = (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    const step = e.shiftKey ? 40 : 10;
    if (e.key === "ArrowRight") setBoxW((w) => clamp(w + step, BOX_MIN_W, BOX_MAX_W));
    else if (e.key === "ArrowLeft") setBoxW((w) => clamp(w - step, BOX_MIN_W, BOX_MAX_W));
    else if (e.key === "ArrowDown") setBoxH((h) => clamp(h + step, BOX_MIN_H, BOX_MAX_H));
    else if (e.key === "ArrowUp") setBoxH((h) => clamp(h - step, BOX_MIN_H, BOX_MAX_H));
    else return;
    e.preventDefault();
  };

  const applyPreset = (w: number, h: number) => {
    setBoxW(clamp(w, BOX_MIN_W, BOX_MAX_W));
    setBoxH(clamp(h, BOX_MIN_H, BOX_MAX_H));
  };

  const requestClose = () => {
    if (dirty && onApply) setAsking(true);
    else onClose?.();
  };

  // Sandbox geometry, from the real algorithm, at the drawing's true pixels.
  const sandbox = computeReflow({
    containerWidth: boxW,
    containerHeight: boxH,
    minCell: draftMin,
    maxCell: draftMax,
    gap: GAP,
    totalUnits: count,
    mode: overflow,
  });
  const sandboxRows = fillRows(sandbox.visibleUnits, sandbox.cols);
  const sandboxGridHeight =
    sandboxRows.length * sandbox.cellPx + Math.max(0, sandboxRows.length - 1) * GAP;

  return (
    <div className="help" role="region" aria-label="How button layout works">
      <header className="help-header">
        <h2 className="help-title">How your buttons are laid out</h2>
        {onClose ? (
          <button type="button" className="help-close" aria-label="Close help" onClick={requestClose}>
            <span aria-hidden="true">&times;</span>
          </button>
        ) : null}
      </header>

      <p className="help-lede">
        deckd works out the layout from the space it has, every time the window changes. Nothing is
        pinned to fixed positions &mdash; that is why buttons move when you resize or rotate.
        Buttons always keep their order, so the first button is always first.
      </p>

      {/* --- Sandbox ------------------------------------------------------ */}
      <section className="help-section">
        <h3 className="help-heading">Try it</h3>
        <p className="help-body">
          Drag the corner of the box, or tap a shape. In this box:
        </p>

        <div className="help-stage" ref={stageRef}>
          <div
            className="help-diagram"
            style={{ width: Math.round(boxW * scale), height: Math.round(boxH * scale) }}
          >
            <div
              style={{ width: boxW, height: boxH, transform: `scale(${scale})`, transformOrigin: "top left" }}
            >
              <div className="help-frame" style={{ width: boxW, height: boxH }}>
                <div
                  className="help-grid"
                  aria-hidden="true"
                  style={{
                    gridTemplateColumns: `repeat(${sandbox.cols}, ${sandbox.cellPx}px)`,
                    gridAutoRows: `${sandbox.cellPx}px`,
                    gap: `${GAP}px`,
                    justifyContent: "center",
                    alignContent: sandboxGridHeight <= boxH ? "center" : "start",
                  }}
                >
                  {Array.from({ length: sandbox.visibleUnits }, (_, i) => (
                    <div key={i} className={`help-cell${i === 0 ? " help-cell-first" : ""}`}>
                      {i + 1}
                    </div>
                  ))}
                </div>
                <button
                  type="button"
                  className="help-resize"
                  aria-label="Resize the example area"
                  onPointerDown={onResizeStart}
                  onPointerMove={onResizeMove}
                  onPointerUp={onResizeEnd}
                  onPointerCancel={onResizeEnd}
                  onKeyDown={onResizeKey}
                />
              </div>
            </div>
          </div>
        </div>

        <p className="help-stats" aria-live="polite">
          <b>
            {sandbox.hiddenUnits > 0
              ? `Showing ${sandbox.visibleUnits} of ${count}`
              : `${count} ${count === 1 ? "button" : "buttons"}`}
          </b>{" "}
          &middot; {sandboxRows.join("+")} &middot; {Math.round(sandbox.cellPx)}px each
          {sandbox.hiddenUnits > 0 ? (
            <>
              {" "}
              &middot; <span className="help-hidden">{sandbox.hiddenUnits} hidden</span>
            </>
          ) : null}
        </p>

        {/* Shapes, roughly matched in area to the default so switching mostly
            changes the arrangement rather than how much fits. */}
        <div className="help-presets" role="group" aria-label="Example shapes">
          <button type="button" onClick={() => applyPreset(220, 380)}>Tall</button>
          <button type="button" onClick={() => applyPreset(360, 210)}>Wide</button>
          <button type="button" onClick={() => applyPreset(330, 420)}>Large</button>
          <button type="button" onClick={() => applyPreset(150, 150)}>Small</button>
        </div>

        <div className="help-controls">
          <label className="help-control">
            <span className="help-control-label">Buttons</span>
            <input
              type="range"
              className="help-slider"
              aria-label="Buttons"
              min={COUNT_MIN}
              max={COUNT_MAX}
              step={1}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
            />
            <span className="help-control-value">{count}</span>
          </label>
          <label className="help-control">
            <span className="help-control-label">Min size</span>
            <input
              type="range"
              className="help-slider"
              aria-label="Min size"
              min={CELL_SIZE_MIN}
              max={CELL_SIZE_MAX}
              step={CELL_SIZE_STEP}
              value={draftMin}
              onChange={(e) => setDraftMin(Number(e.target.value))}
            />
            <span className="help-control-value">{draftMin}px</span>
          </label>
          <label className="help-control">
            <span className="help-control-label">Max size</span>
            <input
              type="range"
              className="help-slider"
              aria-label="Max size"
              min={CELL_SIZE_MIN}
              max={CELL_SIZE_MAX}
              step={CELL_SIZE_STEP}
              value={draftMax}
              onChange={(e) => setDraftMax(Number(e.target.value))}
            />
            <span className="help-control-value">{draftMax}px</span>
          </label>
        </div>

        {overflow === "shrink-to-fit" ? (
          <p className="help-note">
            You use <b>Shrink buttons</b>, so every button is always shown and the minimum size is
            never applied. Switch to <b>Hide extras</b> in Settings to see the minimum take effect.
          </p>
        ) : null}
      </section>

      {/* --- Why they move ------------------------------------------------ */}
      <section className="help-section">
        <h3 className="help-heading">Why do my buttons move?</h3>
        <p className="help-body">
          The app measures the space, then picks the arrangement that makes the buttons as big as
          possible. A tall space gets more rows, a wide one gets more columns &mdash; same buttons,
          same order, only the shape changes.
        </p>
        <div className="help-pair">
          <figure className="help-example">
            <Diagram width={SHAPE_TALL.width} height={SHAPE_TALL.height} scale={SHAPE_SCALE}>
              <MiniGrid {...SHAPE_TALL} />
            </Diagram>
            <figcaption>Tall area &rarr; {layoutOf(SHAPE_TALL).rows.join("+")}</figcaption>
          </figure>
          <figure className="help-example">
            <Diagram width={SHAPE_WIDE.width} height={SHAPE_WIDE.height} scale={SHAPE_SCALE}>
              <MiniGrid {...SHAPE_WIDE} />
            </Diagram>
            <figcaption>Wide area &rarr; {layoutOf(SHAPE_WIDE).rows.join("+")}</figcaption>
          </figure>
        </div>
      </section>

      {/* --- Why some are missing ----------------------------------------- */}
      <section className="help-section">
        <h3 className="help-heading">Why can&rsquo;t I see all my buttons?</h3>
        <p className="help-body">
          <b>Min size</b> is a promise: buttons are never drawn smaller than it. When there
          isn&rsquo;t room for them all at that size, <b>When there&rsquo;s no room</b> decides what
          happens.
        </p>
        <div className="help-pair">
          <figure className="help-example">
            <Diagram width={OVERFLOW_SHRINK.width} height={OVERFLOW_SHRINK.height} scale={OVERFLOW_SCALE}>
              <MiniGrid {...OVERFLOW_SHRINK} />
            </Diagram>
            <figcaption className={overflow === "shrink-to-fit" ? "help-example-on" : undefined}>
              Shrink buttons &rarr; all {OVERFLOW_UNITS} shown, smaller
              {overflow === "shrink-to-fit" ? <b className="help-you"> (you use this)</b> : null}
            </figcaption>
          </figure>
          <figure className="help-example">
            <Diagram width={OVERFLOW_CLIP.width} height={OVERFLOW_CLIP.height} scale={OVERFLOW_SCALE}>
              <MiniGrid {...OVERFLOW_CLIP} />
            </Diagram>
            <figcaption className={overflow === "clip" ? "help-example-on" : undefined}>
              Hide extras &rarr; keeps the minimum, hides the rest
              {overflow === "clip" ? <b className="help-you"> (you use this)</b> : null}
            </figcaption>
          </figure>
        </div>
      </section>

      {/* --- Why the last row is short ------------------------------------ */}
      <section className="help-section">
        <h3 className="help-heading">Why isn&rsquo;t the last row full?</h3>
        <p className="help-body">
          Buttons fill each row across, then wrap. When the count doesn&rsquo;t divide evenly, the
          leftover sits in the bottom row on its own &mdash; {DIST_UNITS} buttons in{" "}
          {DIST_ROWS} rows is {layoutOf(DIST_GRID).rows.join("+")}, never{" "}
          {balancedRows(DIST_UNITS, DIST_ROWS).join("+")}. The whole block is centred, and every row
          starts at the same left edge.
        </p>
        <div className="help-pair">
          <figure className="help-example">
            <Diagram width={DIST_GRID.width} height={DIST_GRID.height} scale={DIST_SCALE}>
              <MiniGrid {...DIST_GRID} />
            </Diagram>
            <figcaption>{layoutOf(DIST_GRID).rows.join("+")}</figcaption>
          </figure>
        </div>
      </section>

      {/* --- Band ---------------------------------------------------------- */}
      <section className="help-section">
        <h3 className="help-heading">How big can they get?</h3>
        <p className="help-body">
          <b>Max size</b> is a cap. Only a few buttons in a big space would otherwise grow into
          enormous tiles; the cap keeps them button-sized.
        </p>
      </section>

      <p className="help-note help-footer">
        The blue square is button&nbsp;1 &mdash; watch it stay first as the grid reshapes.
        {onApply ? (
          <>
            {" "}
            Changes to <b>Min size</b> and <b>Max size</b> here are only applied to this device if
            you tap Apply when you close.
          </>
        ) : (
          <> Open this page from Settings to apply changes to your device.</>
        )}
      </p>

      {asking ? (
        <ApplyDialog
          minCell={draftMin}
          maxCell={draftMax}
          onCancel={() => {
            setAsking(false);
            onClose?.();
          }}
          onApply={() => {
            onApply?.({ minCell: draftMin, maxCell: draftMax });
            setAsking(false);
            onClose?.();
          }}
        />
      ) : null}
    </div>
  );
}

/** The apply-on-close prompt. Deliberately local rather than reusing
 * ``ConfirmModal``: that one speaks the daemon's ``confirm_id`` handshake for
 * dangerous widgets, which has nothing to do with a device preference. */
function ApplyDialog({
  minCell,
  maxCell,
  onCancel,
  onApply,
}: {
  minCell: number;
  maxCell: number;
  onCancel: () => void;
  onApply: () => void;
}) {
  const applyRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    applyRef.current?.focus();
  }, []);
  return (
    <div
      className="help-dialog-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="help-dialog-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onCancel();
        }
      }}
    >
      <div className="help-dialog">
        <h2 className="help-dialog-title" id="help-dialog-title">
          Apply these button sizes?
        </h2>
        <p className="help-dialog-body">
          Min size <b>{minCell}px</b>, max size <b>{maxCell}px</b>. This changes this device only.
        </p>
        <div className="help-dialog-actions">
          <button type="button" className="help-dialog-button" onClick={onCancel}>
            Don&rsquo;t apply
          </button>
          <button
            ref={applyRef}
            type="button"
            className="help-dialog-button help-dialog-primary"
            onClick={onApply}
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  );
}
