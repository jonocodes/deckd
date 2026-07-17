import { useRef } from "react";

type Props = {
  onPad: (dx: number, dy: number) => void;
  onTap: (fingers: number) => void;
  onDrag: (state: "start" | "end") => void;
};

const TAP_MAX_MS = 250;
const TAP_MAX_PX = 10;
const DOUBLE_TAP_WINDOW_MS = 400;

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
 *
 * All state is held in refs so React re-renders never touch the pointer hot
 * path (see INCEPTION.md §5.2). Pointer capture is set per-pointer so a
 * finger sliding off the trackpad still reports moves.
 */
export function Trackpad({ onPad, onTap, onDrag }: Props) {
  const pointers = useRef<Map<number, PointerState>>(new Map());
  const maxFingers = useRef(0);
  const lastTapAt = useRef(0);
  const dragLocked = useRef(false);
  const dragPointerId = useRef<number | null>(null);

  const resetGesture = () => {
    maxFingers.current = 0;
  };

  return (
    <div
      className="trackpad"
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
        if (dragLocked.current) {
          if (e.pointerId === dragPointerId.current) onPad(dx, dy);
        } else if (pointers.current.size === 1) {
          onPad(dx, dy);
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
          if (isTap && maxFingers.current >= 2) {
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
        if (pointers.current.size === 0) resetGesture();
      }}
    >
      <span className="trackpad-hint">trackpad</span>
    </div>
  );
}
