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
  /** High-resolution wheel units per CSS pixel. Owned by the parent
   * (``useScrollSettings``) so the setting can be tuned live from the
   * settings view. */
  scale: number;
  /** Flip the vertical scroll direction. */
  invert: boolean;
  onJog: (id: string, delta: number) => void;
  onJogEnd: (id: string, velocity: number) => void;
};

export function JogStrip({
  widget,
  style,
  className,
  variant = "grid",
  scale,
  invert,
  onJog,
  onJogEnd,
}: JogStripProps) {
  const activePointer = useRef<number | null>(null);
  const lastY = useRef(0);
  const lastT = useRef(0);
  const velocity = useRef(0);
  const pending = useRef(0);
  const raf = useRef<number | null>(null);
  // Snapshot scale/invert into refs so pointer callbacks read the latest
  // value without stale-closure risk if React re-renders mid-gesture.
  const scaleRef = useRef(scale);
  scaleRef.current = scale;
  const signRef = useRef(invert ? -1 : 1);
  signRef.current = invert ? -1 : 1;

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
        const delta = (lastY.current - e.clientY) * scaleRef.current * signRef.current;
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
          <span className="hint">scale {scale} · drag or flick vertically</span>
        </>
      ) : (
        <span className="hint chrome-jogstrip-hint">scroll</span>
      )}
    </div>
  );
}
