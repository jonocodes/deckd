import { useRef } from "react";
import type { CSSProperties } from "react";
import type { Widget } from "./protocol";

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
          const style = { gridColumn: `span ${gw}`, gridRow: `span ${gh}` };
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

type JogStripProps = {
  widget: Widget;
  style: CSSProperties;
  onJog: (id: string, delta: number) => void;
  onJogEnd: (id: string, velocity: number) => void;
};

const SCROLL_UNITS_PER_PX = readNumberSetting(
  "scrollScale",
  (import.meta.env.VITE_DECKD_SCROLL_SCALE ?? "") as string,
  3,
);
const SCROLL_DIRECTION = readBooleanSetting(
  "scrollInvert",
  (import.meta.env.VITE_DECKD_SCROLL_INVERT ?? "") as string,
)
  ? -1
  : 1;

function JogStrip({ widget, style, onJog, onJogEnd }: JogStripProps) {
  const activePointer = useRef<number | null>(null);
  const lastY = useRef(0);
  const lastT = useRef(0);
  const velocity = useRef(0);
  const pending = useRef(0);
  const raf = useRef<number | null>(null);

  const flush = () => {
    raf.current = null;
    const whole = Math.trunc(pending.current);
    pending.current -= whole;
    if (whole !== 0) onJog(widget.id, whole);
  };

  const scheduleFlush = () => {
    if (raf.current === null) raf.current = window.requestAnimationFrame(flush);
  };

  const finish = (el: HTMLElement, pointerId: number, sendMomentum: boolean) => {
    if (activePointer.current !== pointerId) return;
    activePointer.current = null;
    if (el.hasPointerCapture(pointerId)) el.releasePointerCapture(pointerId);
    if (raf.current !== null) {
      window.cancelAnimationFrame(raf.current);
      flush();
    }
    onJogEnd(widget.id, sendMomentum ? Math.round(velocity.current) : 0);
  };

  return (
    <div
      className="cell cell-jogstrip"
      style={style}
      onPointerDown={(e) => {
        e.preventDefault();
        activePointer.current = e.pointerId;
        lastY.current = e.clientY;
        lastT.current = e.timeStamp;
        velocity.current = 0;
        pending.current = 0;
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (activePointer.current !== e.pointerId) return;
        e.preventDefault();
        const dt = Math.max((e.timeStamp - lastT.current) / 1000, 0.001);
        const delta = (lastY.current - e.clientY) * SCROLL_UNITS_PER_PX * SCROLL_DIRECTION;
        pending.current += delta;
        velocity.current = delta / dt;
        lastY.current = e.clientY;
        lastT.current = e.timeStamp;
        scheduleFlush();
      }}
      onPointerUp={(e) => finish(e.currentTarget, e.pointerId, true)}
      onPointerCancel={(e) => finish(e.currentTarget, e.pointerId, false)}
    >
      <span className="label">{widget.label ?? widget.id}</span>
      <span className="hint">scale {SCROLL_UNITS_PER_PX} · drag or flick vertically</span>
    </div>
  );
}

function readNumberSetting(queryName: string, envValue: string, fallback: number): number {
  const raw = new URLSearchParams(window.location.search).get(queryName) ?? envValue;
  if (!raw) return fallback;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function readBooleanSetting(queryName: string, envValue: string): boolean {
  const raw = (new URLSearchParams(window.location.search).get(queryName) ?? envValue).toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}
