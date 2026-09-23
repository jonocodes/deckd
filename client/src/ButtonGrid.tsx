import { useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { Widget } from "./protocol";
import { Icon } from "./Icon";
import { JogStrip } from "./JogStrip";
import { MeterCell } from "./MeterCell";
import { StatsCell } from "./StatsCell";
import { MediaCell } from "./MediaCell";
import type { MediaReading } from "./media-store";
import type { MeterReading } from "./meter-store";
import { computeReflow } from "./reflow";
import type { OverflowMode } from "./reflow";
import { MAX_CELL_DEFAULT, MIN_CELL_DEFAULT } from "./settings-store";
import { onActivate } from "./a11y";

/** Gap between cells, in CSS pixels. Kept in sync with ``.grid { gap }`` so the
 * reflow maths agrees with what the browser actually renders. */
const GRID_GAP = 8;

type Props = {
  widgets: Widget[];
  onPress: (id: string) => void;
  onJog: (id: string, delta: number) => void;
  onJogEnd: (id: string, velocity: number) => void;
  scrollScale: number;
  scrollInvert: boolean;
  /** What to do when the deck exceeds what the viewport holds at ``minCell``
   * (ADR-0011): ``clip`` (default) trims trailing widgets so the survivors
   * keep their size; ``shrink-to-fit`` keeps every widget by letting cells
   * fall below the floor. Resolved by ``App`` from the device preference,
   * falling back to the layout's ``overflow`` field. */
  overflow?: OverflowMode;
  /** Readability floor (client-side device preference, ADR-0011): the smallest
   * cell the user accepts. Decides how many widgets are visible under
   * ``clip``; ignored entirely under ``shrink-to-fit``. Defaults let harnesses
   * that don't wire settings still render sensibly. */
  minCell?: number;
  /** Comfort cap (client-side device preference, ADR-0011): stops a nearly
   * empty deck from becoming a few enormous buttons. */
  maxCell?: number;
  /** Latest reading per sensor source. Missing sources render with no
   * value (bar empty, "—" numeric). Stale readings show the bar at
   * its last position with a dimmed readout. */
  meterReadings?: Record<string, MeterReading>;
  mediaStates?: Record<string, MediaReading>;
  onMediaCommand?: (id: string, command: "volume" | "seek" | "rate", value: number) => void;
  /** Multiplier for the meter widget's caption label so it scales with
   * the same user-facing "label size" preference as buttons. */
  labelScale?: number;
  /** When true, buttons whose action is a key combo show that combo as a
   * small caption under the label (e.g. ``Ctrl+A``). */
  showKeyHints?: boolean;
};

/** Title-case each token of a key combo so ``ctrl+a`` reads as ``Ctrl+A``.
 * Purely presentational — the daemon-side combo string is untouched. */
function prettifyCombo(combo: string): string {
  return combo
    .split("+")
    .map((part) => (part.length <= 1 ? part.toUpperCase() : part[0].toUpperCase() + part.slice(1)))
    .join("+");
}

/** The key combo a button sends on press, for the optional key-hint caption.
 * Reads ``action.key`` (the shortcut form) and, for macros, the first ``key``
 * step. Returns null for buttons whose action isn't a key combo (shell, url,
 * dbus, …) so those render without a hint. */
function keyHint(w: Widget): string | null {
  const actionKey = w.action?.key;
  if (typeof actionKey === "string" && actionKey.length > 0) return prettifyCombo(actionKey);
  const step = w.macro?.steps.find((s) => s.type === "key" && s.value);
  if (step) return prettifyCombo(step.value);
  return null;
}

/** A widget's ``[w, h]`` column/row span. ``full`` and absent both collapse to
 * a single cell for span purposes (a ``full`` widget is placed separately). */
function spanOf(w: Widget): [number, number] {
  if (w.size == null || w.size === "full") return [1, 1];
  const [cw, ch] = w.size;
  return [Math.max(1, cw), Math.max(1, ch)];
}

/** Measure the grid area so the reflow maths can compute the column count and
 * cell size from live pixels (ADR-0003: the client sizes cells from available
 * screen space). A ``ResizeObserver`` keeps it current as the window is
 * dragged / the device rotates — no polling. */
function useMeasuredSize(): [React.RefObject<HTMLDivElement>, { width: number; height: number }] {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const update = () => setSize({ width: el.clientWidth, height: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size];
}

export function ButtonGrid({
  widgets,
  onPress,
  onJog,
  onJogEnd,
  scrollScale,
  scrollInvert,
  overflow = "clip",
  minCell = MIN_CELL_DEFAULT,
  maxCell = MAX_CELL_DEFAULT,
  meterReadings,
  labelScale,
  mediaStates,
  onMediaCommand,
  showKeyHints,
}: Props) {
  const [gridRef, size] = useMeasuredSize();

  // Cells occupied by flow widgets (spans counted). ``full`` widgets leave the
  // flow, so they don't add.
  const unitsOf = (w: Widget) => {
    if (w.size === "full") return 0;
    const [cw, ch] = spanOf(w);
    return cw * ch;
  };
  const totalUnits = widgets.reduce((sum, w) => sum + unitsOf(w), 0);

  const { cols, rows, cellPx, visibleUnits } = computeReflow({
    containerWidth: size.width,
    containerHeight: size.height,
    minCell,
    maxCell,
    gap: GRID_GAP,
    totalUnits,
    mode: overflow,
  });

  // ADR-0011: ``clip`` trims the deck rather than letting CSS crop it, so the
  // surface never shows a row sliced in half at the fold. Strict order, so the
  // prefix stops at the first widget that would not fit whole — we never skip
  // a wide widget to squeeze in a later narrow one. ``full`` widgets cost no
  // units and so always survive the trim.
  const shown =
    visibleUnits >= totalUnits
      ? widgets
      : (() => {
          let used = 0;
          return widgets.filter((w) => {
            const units = unitsOf(w);
            if (used + units > visibleUnits) return false;
            used += units;
            return true;
          });
        })();

  // Square, fixed tracks: every column is ``cellPx`` wide and every implicit
  // row is ``cellPx`` tall, so a cell is square and an ``[w, h]`` span is
  // exactly ``w`` columns by ``h`` rows (gaps included). CSS grid's own
  // auto-placement performs the fill-and-wrap, and ``justify-content: center``
  // on a fixed track list centres the block while leaving short rows washed
  // left against it — exactly the distribution ADR-0011 specifies.
  const gridStyle: CSSProperties = {
    gridTemplateColumns: `repeat(${cols}, ${cellPx}px)`,
    gridAutoRows: `${cellPx}px`,
    // Centre the block vertically too, but only when it genuinely fits: a
    // spanned widget can wrap into more rows than the maths predicted, and
    // centring an overflowing grid would crop its top as well as its bottom.
    alignContent:
      rows * cellPx + Math.max(0, rows - 1) * GRID_GAP <= size.height ? "center" : "start",
  };

  return (
    <div ref={gridRef} className="grid" style={gridStyle}>
      {shown.map((w) => {
        const full = w.size === "full";
        const [cw, ch] = spanOf(w);
        // Cap a span at the current column count so a too-wide widget doesn't
        // force horizontal overflow; strict order (no dense) wraps it down.
        const style: CSSProperties = full
          ? { gridColumn: "1 / -1" }
          : { gridColumn: `span ${Math.min(cw, cols)}`, gridRow: `span ${ch}` };

        if (w.kind === "blank") {
          // A deliberate gap in the flow: holds its span, renders nothing.
          return <div key={w.id} className="cell cell-empty" style={style} aria-hidden="true" />;
        }
        if (w.kind === "jogstrip") {
          return (
            <JogStrip
              key={w.id}
              widget={w}
              style={style}
              scale={scrollScale}
              invert={scrollInvert}
              onJog={onJog}
              onJogEnd={onJogEnd}
            />
          );
        }
        if (w.kind === "meter") {
          return (
            <MeterCell
              key={w.id}
              widget={w}
              reading={(w.source ? meterReadings?.[w.source] : null) ?? null}
              style={style}
              labelScale={labelScale ?? 1}
            />
          );
        }
        if (w.kind === "media") {
          return (
            <MediaCell
              key={w.id}
              widget={w}
              state={mediaStates?.[w.id] ?? null}
              style={style}
              onPress={onPress}
              onCommand={onMediaCommand ?? (() => undefined)}
            />
          );
        }
        if (w.kind === "stats") {
          return (
            <StatsCell
              key={w.id}
              widget={w}
              readings={meterReadings ?? {}}
              style={style}
              labelScale={labelScale ?? 1}
            />
          );
        }
        const buttonStyle: CSSProperties = w.color ? { ...style, backgroundColor: w.color } : style;
        const hint = showKeyHints ? keyHint(w) : null;
        // ``confirm: true`` widgets carry a persistent danger affordance
        // (issue #69 / #109): red border + small ⚠ badge so a user can
        // spot danger before pressing. The widget record the daemon
        // relays on every layout push carries the field verbatim.
        const isDangerous = w.confirm === true;
        const cellClassName = isDangerous
          ? "cell cell-button cell-danger"
          : "cell cell-button";
        return (
          <button
            key={w.id}
            className={cellClassName}
            style={buttonStyle}
            aria-label={w.label ?? w.id}
            data-confirm-dangerous={isDangerous ? "true" : undefined}
            onPointerDown={() => onPress(w.id)}
            onKeyDown={onActivate(() => onPress(w.id))}
          >
            {isDangerous ? (
              <span className="cell-danger-badge" aria-hidden="true">
                <Icon icon={{ source: "lucide", name: "alert-triangle" }} />
              </span>
            ) : null}
            {w.icon ? <Icon icon={w.icon} className="icon" /> : null}
            {/* Text is opt-in per button: a widget with a ``label`` shows it,
                one without is icon-only. The id is only a last-resort
                fallback so a widget with neither label nor icon isn't a
                blank, unidentifiable button. */}
            {w.label ? (
              <span className="label">{w.label}</span>
            ) : !w.icon ? (
              <span className="label">{w.id}</span>
            ) : null}
            {hint ? <span className="key-hint">{hint}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
