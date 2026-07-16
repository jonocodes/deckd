import type { Widget } from "./protocol";

type Props = {
  widgets: Widget[];
  onPress: (id: string) => void;
};

const COLS = 4;
const ROWS = 4;

export function ButtonGrid({ widgets, onPress }: Props) {
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
          return (
            <button
              key={w.id}
              className="cell cell-button"
              style={{ gridColumn: `span ${gw}`, gridRow: `span ${gh}` }}
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
