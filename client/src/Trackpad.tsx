import { useRef } from "react";
import type { KeyboardEvent } from "react";

type Props = {
  onPad: (dx: number, dy: number) => void;
  onTap: (fingers: number) => void;
  onDrag: (state: "start" | "end") => void;
  /** Multiplier applied to raw pointer deltas before they're accumulated
   * and sent to the daemon. 1.0 is raw (1 CSS pixel = 1 uinput unit). */
  sensitivity: number;
};

const TAP_MAX_MS = 250;
const TAP_MAX_PX = 10;
const DOUBLE_TAP_WINDOW_MS = 400;
/** uinput REL units per arrow-key tap (issue #60). Picked to match
 * a single pixel at sensitivity = 1, so a single key press moves the
 * cursor one CSS pixel — the same rate a one-finger touch produces
 * at the lowest sensitivity. */
const KEY_STEP = 1;
/** 16x jump for Page Up / Page Down; matches a small swipe on touch. */
const BIG_STEP = 16;
const REPEAT_DELAY_MS = 250;
const REPEAT_INTERVAL_MS = 50;

type PointerState = {
  startX: number;
  startY: number;
  lastX: number;
  lastY: number;
  startT: number;
  moved: boolean;
};

/** Trackpad surface. Detects three gestures client-side and forwards them
 * to the daemon as ``pad`` / ``pad_tap`` / ``pad_drag`` messages:
 *
 *   - Finger drag → ``pad`` (dx/dy at pointermove cadence)
 *   - Single-finger tap → ``pad_tap`` fingers=1  (left click)
 *   - Two-finger tap → ``pad_tap`` fingers=2  (right click)
 *   - Tap-and-a-half (tap, then quickly touch and drag) → ``pad_drag`` start,
 *     pad deltas while dragging, ``pad_drag`` end on lift
 *   - **Keyboard** (issue #60, AC #6): while focused, arrow keys
 *     produce small ``pad`` deltas; Page Up / Page Down / numpad
 *     diagonals produce larger jumps; Space / Enter fires a single
 *     ``pad_tap`` (left click). Same rhythm as the touch surface so
 *     a keyboard user can drive the cursor without leaving the keys.
 *
 * All state is held in refs so React re-renders never touch the pointer hot
 * path (see INCEPTION.md §5.2). Pointer capture is set per-pointer so a
 * finger sliding off the trackpad still reports moves.
 */
export function Trackpad({ onPad, onTap, onDrag, sensitivity }: Props) {
  // Snapshot into a ref so mid-gesture setting changes take effect on the
  // next pointermove without stale-closure risk (same pattern as JogStrip).
  const sensRef = useRef(sensitivity);
  sensRef.current = sensitivity;
  const pointers = useRef<Map<number, PointerState>>(new Map());
  const maxFingers = useRef(0);
  const lastTapAt = useRef(0);
  const dragLocked = useRef(false);
  const dragPointerId = useRef<number | null>(null);
  // Subpixel accumulators: pointermove hands us fractional deltas
  // (e.g. 3.33px per frame at 60fps). uinput REL_X/REL_Y takes integers,
  // and the wire schema (PadMessage) declares dx/dy as int, so we truncate
  // to whole pixels and carry the remainder into the next frame — same
  // pattern JogStrip uses for scroll deltas.
  const pendingDx = useRef(0);
  const pendingDy = useRef(0);
  // Held-key auto-repeat. ``repeatDir`` is a {dx, dy} pair so a held
  // Up+Right combination emits diagonal deltas, mirroring the touch
  // multi-pointer case.
  const repeatTimer = useRef<number | null>(null);
  const repeatDir = useRef<{ dx: number; dy: number } | null>(null);

  const flushPad = () => {
    const wx = Math.trunc(pendingDx.current);
    const wy = Math.trunc(pendingDy.current);
    if (wx === 0 && wy === 0) return;
    pendingDx.current -= wx;
    pendingDy.current -= wy;
    onPad(wx, wy);
  };

  const resetGesture = () => {
    maxFingers.current = 0;
    pendingDx.current = 0;
    pendingDy.current = 0;
  };

  const stopRepeat = () => {
    if (repeatTimer.current !== null) {
      window.clearTimeout(repeatTimer.current);
      repeatTimer.current = null;
    }
    repeatDir.current = null;
  };

  // Keyboard alternative to the pointer gestures (issue #60, AC
  // #6). Maps arrow keys + numpad to REL deltas; Space / Enter
  // fires a single left-click ``pad_tap``. The handler is added
  // to the trackpad div via ``onKeyDown`` so the trackpad has to
  // be focused (it is — ``tabIndex={0}``) before keys land. The
  // ``page up / page down`` keys produce larger jumps; holding any
  // key auto-repeats like a held touch-and-drag.
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    let dx = 0;
    let dy = 0;
    let big = false;
    switch (e.key) {
      case "ArrowLeft":
      case "Numpad4":
        dx = -1;
        break;
      case "ArrowRight":
      case "Numpad6":
        dx = 1;
        break;
      case "ArrowUp":
      case "Numpad8":
        dy = -1;
        break;
      case "ArrowDown":
      case "Numpad2":
        dy = 1;
        break;
      case "Numpad7":
        dx = -1;
        dy = -1;
        break;
      case "Numpad9":
        dx = 1;
        dy = -1;
        break;
      case "Numpad1":
        dx = -1;
        dy = 1;
        break;
      case "Numpad3":
        dx = 1;
        dy = 1;
        break;
      case "PageUp":
        dy = -1;
        big = true;
        break;
      case "PageDown":
        dy = 1;
        big = true;
        break;
      case "Home":
        e.preventDefault();
        // Big relative jump to the top-left of the screen; daemon
        // handles it the same way a big touch swipe would.
        onPad(-10000, -10000);
        return;
      case "End":
        e.preventDefault();
        onPad(10000, 10000);
        return;
      case " ":
      case "Enter":
        e.preventDefault();
        onTap(1);
        return;
      default:
        return;
    }
    e.preventDefault();
    const step = (big ? BIG_STEP : KEY_STEP) * sensRef.current;
    const fdx = Math.round(dx * step);
    const fdy = Math.round(dy * step);
    if (fdx !== 0 || fdy !== 0) onPad(fdx, fdy);
    // Auto-repeat if the user holds the key. We key the repeat
    // off the (dx, dy) pair so a held ArrowUp+ArrowRight combo
    // emits diagonal deltas rather than switching back and forth
    // between two repeat timers.
    const dir = { dx, dy };
    if (
      repeatTimer.current === null ||
      !repeatDir.current ||
      repeatDir.current.dx !== dir.dx ||
      repeatDir.current.dy !== dir.dy
    ) {
      stopRepeat();
      repeatDir.current = dir;
      repeatTimer.current = window.setTimeout(() => {
        repeatTimer.current = window.setInterval(() => {
          const d = repeatDir.current;
          if (!d) return;
          const s = KEY_STEP * sensRef.current;
          onPad(Math.round(d.dx * s), Math.round(d.dy * s));
        }, REPEAT_INTERVAL_MS);
      }, REPEAT_DELAY_MS);
    }
  };

  const onKeyUp = () => {
    stopRepeat();
  };

  return (
    <div
      className="trackpad"
      role="application"
      tabIndex={0}
      aria-label="Trackpad (use arrow keys to move, space or enter to click, page up/down for bigger steps)"
      onKeyDown={onKeyDown}
      onKeyUp={onKeyUp}
      onBlur={stopRepeat}
      onPointerDown={(e) => {
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        const now = e.timeStamp;

        // Tap-and-a-half: a second touch that arrives inside the double-tap
        // window while no other fingers are down promotes to a drag lock.
        if (
          pointers.current.size === 0 &&
          !dragLocked.current &&
          now - lastTapAt.current < DOUBLE_TAP_WINDOW_MS
        ) {
          dragLocked.current = true;
          dragPointerId.current = e.pointerId;
          lastTapAt.current = 0;
          onDrag("start");
        }

        pointers.current.set(e.pointerId, {
          startX: e.clientX,
          startY: e.clientY,
          lastX: e.clientX,
          lastY: e.clientY,
          startT: now,
          moved: false,
        });
        maxFingers.current = Math.max(maxFingers.current, pointers.current.size);
      }}
      onPointerMove={(e) => {
        const p = pointers.current.get(e.pointerId);
        if (!p) return;
        e.preventDefault();
        const dx = e.clientX - p.lastX;
        const dy = e.clientY - p.lastY;
        p.lastX = e.clientX;
        p.lastY = e.clientY;
        if (
          Math.abs(e.clientX - p.startX) > TAP_MAX_PX ||
          Math.abs(e.clientY - p.startY) > TAP_MAX_PX
        ) {
          p.moved = true;
        }

        // Move the cursor when: (a) we're in an explicit drag lock and this
        // is the drag pointer, or (b) there's a single pointer down (a plain
        // one-finger drag). A second finger present suppresses movement so
        // pinching / two-finger idling doesn't jitter the cursor.
        const routeMove =
          dragLocked.current
            ? e.pointerId === dragPointerId.current
            : pointers.current.size === 1;
        if (routeMove) {
          pendingDx.current += dx * sensRef.current;
          pendingDy.current += dy * sensRef.current;
          flushPad();
        }
      }}
      onPointerUp={(e) => {
        const p = pointers.current.get(e.pointerId);
        if (!p) return;
        e.preventDefault();
        pointers.current.delete(e.pointerId);
        if (e.currentTarget.hasPointerCapture(e.pointerId)) {
          e.currentTarget.releasePointerCapture(e.pointerId);
        }

        if (dragLocked.current && e.pointerId === dragPointerId.current) {
          dragLocked.current = false;
          dragPointerId.current = null;
          onDrag("end");
          if (pointers.current.size === 0) resetGesture();
          return;
        }

        const isTap =
          e.timeStamp - p.startT < TAP_MAX_MS && !p.moved;

        if (pointers.current.size === 0) {
          // Exactly two: right-click. Three-or-more is a stray fifth-finger
          // touch during a gesture and should not fire anything.
          if (isTap && maxFingers.current === 2) {
            onTap(2);
          } else if (isTap && maxFingers.current === 1) {
            onTap(1);
            lastTapAt.current = e.timeStamp;
          }
          resetGesture();
        }
      }}
      onPointerCancel={(e) => {
        const p = pointers.current.get(e.pointerId);
        if (!p) return;
        pointers.current.delete(e.pointerId);
        if (dragLocked.current && e.pointerId === dragPointerId.current) {
          dragLocked.current = false;
          dragPointerId.current = null;
          onDrag("end");
        }
        if (pointers.current.size === 0) {
          // Cancel invalidates any pending tap-and-a-half promotion so a
          // subsequent touch doesn't accidentally drag-lock.
          lastTapAt.current = 0;
          resetGesture();
        }
      }}
    >
      <span className="trackpad-hint">trackpad</span>
    </div>
  );
}
