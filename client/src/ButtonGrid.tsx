import type { CSSProperties } from "react";
import type { Widget } from "./protocol";
import { Icon } from "./Icon";
import { JogStrip } from "./JogStrip";
import { transposeWidgets, useOrientation } from "./orientation";

type Props = {
  widgets: Widget[];
  onPress: (id: string) => void;
  onJog: (id: string, delta: number) => void;
  onJogEnd: (id: string, velocity: number) => void;
  scrollScale: number;
  scrollInvert: boolean;
};

const FALLBACK_DIM = 4;

/** Derive grid dimensions from the layout's widget extents so cells fill the
 * chrome-excluded area rather than leaving empty 1fr rows/columns when a
 * layout doesn't use the full 4x4 space (ADR-0003: the client computes
 * cell sizes from available screen space). Falls back to 4x4 when there
 * are no widgets to size against. */
function deriveDims(widgets: Widget[]): [number, number] {
  if (widgets.length === 0) return [FALLBACK_DIM, FALLBACK_DIM];
  let cols = 0;
  let rows = 0;
  for (const w of widgets) {
    const [x, y, wCols, wRows] = w.grid;
    cols = Math.max(cols, x + wCols);
    rows = Math.max(rows, y + wRows);
  }
  return [Math.max(cols, 1), Math.max(rows, 1)];
}

export function ButtonGrid({ widgets, onPress, onJog, onJogEnd, scrollScale, scrollInvert }: Props) {
  const orientation = useOrientation();
  // In portrait, transpose so a landscape-authored grid keeps sensibly-sized
  // cells (a 4x2 firefox layout becomes 2x4 with taller buttons).
  const laid = orientation === "portrait" ? transposeWidgets(widgets) : widgets;
  const [COLS, ROWS] = deriveDims(laid);
  const filled = Array.from({ length: ROWS }, () => Array(COLS).fill(null) as (Widget | null)[]);
  for (const w of laid) {
    const [x, y, wCols, wRows] = w.grid;
    for (let dy = 0; dy < wRows; dy++) {
      for (let dx = 0; dx < wCols; dx++) {
        if (y + dy < ROWS && x + dx < COLS) filled[y + dy][x + dx] = w;
      }
    }
  }

  return (
    <div
      className="grid"
      style={{ gridTemplateColumns: `repeat(${COLS}, 1fr)`, gridTemplateRows: `repeat(${ROWS}, 1fr)` }}
    >
      {filled.flatMap((row, y) =>
        row.map((w, x) => {
          // ``w.grid`` here already reflects any transpose applied above.
          if (!w) return <div key={`${x}-${y}`} className="cell cell-empty" />;
          const [gx, gy, gw, gh] = w.grid;
          const isOrigin = gx === x && gy === y;
          if (!isOrigin) return null;
          const style: CSSProperties = { gridColumn: `span ${gw}`, gridRow: `span ${gh}` };
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
          const buttonStyle: CSSProperties = w.color
            ? { ...style, backgroundColor: w.color }
            : style;
          return (
            <button
              key={w.id}
              className="cell cell-button"
              style={buttonStyle}
              onPointerDown={(e) => {
                e.preventDefault();
                onPress(w.id);
              }}
            >
              {w.icon ? <Icon icon={w.icon} className="icon" /> : null}
              <span className="label">{w.label ?? w.id}</span>
            </button>
          );
        }),
      )}
    </div>
  );
}
