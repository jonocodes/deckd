import type { CSSProperties } from "react";
import type { Widget } from "./protocol";
import { JogStrip } from "./JogStrip";

type Props = {
  widgets: Widget[];
  onPress: (id: string) => void;
  onJog: (id: string, delta: number) => void;
  onJogEnd: (id: string, velocity: number) => void;
};

const COLS = 4;
const ROWS = 4;

export function ButtonGrid({ widgets, onPress, onJog, onJogEnd }: Props) {
  const filled = Array.from({ length: ROWS }, () => Array(COLS).fill(null) as (Widget | null)[]);
  for (const w of widgets) {
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
          if (!w) return <div key={`${x}-${y}`} className="cell cell-empty" />;
          const [gx, gy, gw, gh] = w.grid;
          const isOrigin = gx === x && gy === y;
          if (!isOrigin) return <div key={`${x}-${y}`} className="cell cell-empty" />;
          const style: CSSProperties = { gridColumn: `span ${gw}`, gridRow: `span ${gh}` };
          if (w.kind === "jogstrip") {
            return (
              <JogStrip
                key={w.id}
                widget={w}
                style={style}
                onJog={onJog}
                onJogEnd={onJogEnd}
              />
            );
          }
          return (
            <button
              key={w.id}
              className="cell cell-button"
              style={style}
              onPointerDown={(e) => {
                e.preventDefault();
                onPress(w.id);
              }}
            >
              <span className="label">{w.label ?? w.id}</span>
              {w.icon ? <span className="icon">{w.icon}</span> : null}
            </button>
          );
        }),
      )}
    </div>
  );
}
