import { useRef } from "react";
import type { CSSProperties, KeyboardEvent } from "react";
import { ChevronsUpDown } from "lucide-react";

/** Minimal shape a JogStrip needs. Layout widgets satisfy this via the full
 * ``Widget`` type; the chrome strip supplies an ``id`` only, without the
 * bogus grid placement that a real grid widget requires. */
export type JogHandle = {
  id: string;
  label?: string | null;
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

/** Wheel-units per arrow-key tap (issue #60). Matches a moderate
 * wheel notch so a single keypress feels like one click of a mouse
 * wheel — the same rhythm a touch user gets from a small flick. */
const KEY_STEP = 120;

/** Map each keyboard surface to its sign + whether it's a "big"
 * step. Home and End are handled separately (they fire a one-shot
 * jump instead of a stepped delta). */
const KEY_MAP: Record<string, { sign: number; big: boolean } | undefined> = {
  ArrowUp: { sign: -1, big: false },
  ArrowRight: { sign: -1, big: false },
  ArrowDown: { sign: 1, big: false },
  ArrowLeft: { sign: 1, big: false },
  PageUp: { sign: -1, big: true },
  PageDown: { sign: 1, big: true },
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
  // Hold auto-repeat timers so a held arrow key streams scroll
  // deltas, matching the OS convention for held keys.
  const repeatTimer = useRef<number | null>(null);
  const repeatSign = useRef(0);

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

  const stopRepeat = () => {
    if (repeatTimer.current !== null) {
      window.clearTimeout(repeatTimer.current);
      repeatTimer.current = null;
    }
    repeatSign.current = 0;
  };

  // Keyboard alternative for the pointer-only scroll surface
  // (issue #60, AC #6). While the strip has focus, ArrowUp /
  // ArrowDown produce scroll deltas; Page Up / Page Down emit a
  // larger notch; Home / End jump to the top / bottom (signalled
  // via a single large delta — the daemon treats big deltas the
  // same as small ones, just faster scroll). Hold-to-repeat uses
  // a 250ms delay then a 50ms cadence so a held key streams
  // smooth deltas without flooding the daemon.
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    // Home / End: a single big jump to the top / bottom of the
    // scroll surface. The daemon treats big deltas as faster scroll,
    // so a single huge delta reads as "jump to the end".
    if (e.key === "Home") {
      e.preventDefault();
      onJog(widget.id, -10000);
      return;
    }
    if (e.key === "End") {
      e.preventDefault();
      onJog(widget.id, 10000);
      return;
    }
    // Map the key to a (sign, big) pair in one expression so the
    // linter doesn't flag a useless initial assignment.
    const keySpec = KEY_MAP[e.key];
    if (!keySpec) return;
    e.preventDefault();
    const { sign: rawSign, big } = keySpec;
    const effective = rawSign * signRef.current;
    const delta = (big ? KEY_STEP * 8 : KEY_STEP) * effective;
    onJog(widget.id, delta);
    // Auto-repeat if the user holds the key. 250ms is the OS
    // convention for the first repeat — fast enough to feel
    // responsive, slow enough that single taps don't accidentally
    // double-fire.
    if (repeatTimer.current === null || repeatSign.current !== effective) {
      stopRepeat();
      repeatSign.current = effective;
      repeatTimer.current = window.setTimeout(() => {
        repeatTimer.current = window.setInterval(() => {
          onJog(widget.id, KEY_STEP * repeatSign.current);
        }, 50);
      }, 250);
    }
  };

  const onKeyUp = (e: KeyboardEvent<HTMLDivElement>) => {
    if (
      e.key === "ArrowUp" ||
      e.key === "ArrowDown" ||
      e.key === "ArrowLeft" ||
      e.key === "ArrowRight" ||
      e.key === "PageUp" ||
      e.key === "PageDown"
    ) {
      stopRepeat();
    }
  };

  const accessibleLabel = variant === "chrome"
    ? `scroll strip (use arrow keys or page up/down to scroll)`
    : `${widget.label ?? widget.id} scroll strip (use arrow keys or page up/down to scroll)`;

  return (
    <div
      className={["cell", "cell-jogstrip", className].filter(Boolean).join(" ")}
      style={style}
      role="scrollbar"
      tabIndex={0}
      aria-label={accessibleLabel}
      aria-orientation="vertical"
      aria-valuenow={0}
      onKeyDown={onKeyDown}
      onKeyUp={onKeyUp}
      onBlur={stopRepeat}
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
          <ChevronsUpDown className="jog-mark" aria-hidden />
          <span className="label">{widget.label ?? widget.id}</span>
          <span className="hint">scale {scale} · drag or arrow keys</span>
        </>
      ) : (
        <>
          <ChevronsUpDown className="jog-mark" aria-hidden />
          <span className="hint chrome-jogstrip-hint">scroll · arrow keys</span>
        </>
      )}
    </div>
  );
}
