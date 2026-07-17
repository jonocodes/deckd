import { useRef } from "react";
import type { CSSProperties } from "react";

/** Minimal shape a JogStrip needs. Layout widgets satisfy this via the full
 * ``Widget`` type; the chrome strip supplies an ``id`` only, without the
 * bogus grid placement that a real grid widget requires. */
export type JogHandle = {
  id: string;
  label?: string | null;
  icon?: string | null;
};

export type JogStripProps = {
  widget: JogHandle;
  style?: CSSProperties;
  className?: string;
  variant?: "grid" | "chrome";
  onJog: (id: string, delta: number) => void;
  onJogEnd: (id: string, velocity: number) => void;
};

export const SCROLL_UNITS_PER_PX = readNumberSetting(
  "scrollScale",
  (import.meta.env.VITE_DECKD_SCROLL_SCALE ?? "") as string,
  3,
);
export const SCROLL_DIRECTION = readBooleanSetting(
  "scrollInvert",
  (import.meta.env.VITE_DECKD_SCROLL_INVERT ?? "") as string,
)
  ? -1
  : 1;

export function JogStrip({
  widget,
  style,
  className,
  variant = "grid",
  onJog,
  onJogEnd,
}: JogStripProps) {
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
      className={["cell", "cell-jogstrip", className].filter(Boolean).join(" ")}
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
      {variant === "grid" ? (
        <>
          <span className="label">{widget.label ?? widget.id}</span>
          <span className="hint">scale {SCROLL_UNITS_PER_PX} · drag or flick vertically</span>
        </>
      ) : (
        <span className="hint chrome-jogstrip-hint">scroll</span>
      )}
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
