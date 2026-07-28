/** Accessible tooltip for icon-only chrome controls (issue #59).
 *
 * Surfaces on:
 * - **pointer enter** (mouse hover, with a short delay so the tooltip
 *   doesn't flash as the cursor crosses the page)
 * - **keyboard focus** (immediate, since a keyboard user is asking
 *   to learn what the focused control does)
 * - **touch-and-hold** (a long-press shows it; release dismisses)
 *
 * Hides on:
 * - **pointer leave**
 * - **blur** (keyboard focus moves away)
 * - **Escape** (keyboard dismissable)
 * - **4 second timeout** so a stale tooltip doesn't linger on screen
 *   after the user moves on
 *
 * Accessibility:
 * - The host element gets ``aria-describedby="tooltip-<id>"`` so a
 *   screen reader announces the tooltip text after the control's
 *   accessible name. The text is the same string the parent passes
 *   in via ``label`` (which should match its ``aria-label``), so
 *   sighted and assistive-tech users see the same name (AC #2).
 * - The floating element carries ``role="tooltip"`` and a matching
 *   ``id`` so the relationship is bidirectional.
 * - The trigger uses a ``<div>`` wrapper around the child so the
 *   tooltip host can take pointer / focus events without changing
 *   the underlying button's semantics. The actual button keeps its
 *   own ``aria-label`` and click handler.
 */
import {
  cloneElement,
  forwardRef,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import type {
  CSSProperties,
  KeyboardEvent,
  ReactElement,
  ReactNode,
  TouchEvent,
} from "react";

const HOVER_DELAY_MS = 200;
const LONG_PRESS_MS = 500;
const AUTO_DISMISS_MS = 4000;

export interface TooltipProps {
  /** The tooltip text — must match the wrapped control's ``aria-label``
   *  so sighted and screen-reader users see the same string (AC #2). */
  label: string;
  /** The control the tooltip describes. Must be a single React
   *  element (typically a ``<button>``). */
  children: ReactElement;
}

/** Wraps a control in an accessible tooltip. See the module docstring
 *  for behaviour.
 *
 *  Forwarded ref (issue #60): the tooltip sits between the parent
 *  component and the wrapped child, so the parent's ``ref`` lands
 *  here first. We forward it through ``cloneElement``'s ``ref``
 *  prop so a parent that passes ``ref={someUseRefObject}`` still
 *  gets the resolved DOM node (React 18 strips the ``ref`` prop
 *  before it reaches the inner child unless the wrapper is a
 *  ``forwardRef`` component). */
export const Tooltip = forwardRef<HTMLElement, TooltipProps>(function Tooltip(
  { label, children },
  forwardedRef,
) {
  const id = useId();
  const tooltipId = `tooltip-${id}`;
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const hoverTimer = useRef<number | null>(null);
  const longPressTimer = useRef<number | null>(null);
  const autoDismissTimer = useRef<number | null>(null);
  const touchActive = useRef(false);
  // We need a ref to the host element so we can read its bounding
  // rect when showing — the tooltip floats above the host.
  const hostRef = useRef<HTMLElement | null>(null);

  const clearTimers = useCallback(() => {
    if (hoverTimer.current !== null) {
      window.clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
    if (longPressTimer.current !== null) {
      window.clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
    if (autoDismissTimer.current !== null) {
      window.clearTimeout(autoDismissTimer.current);
      autoDismissTimer.current = null;
    }
  }, []);

  const measure = useCallback(() => {
    const el = hostRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setPos({ left: rect.left + rect.width / 2, top: rect.top });
  }, []);

  const show = useCallback(() => {
    measure();
    clearTimers();
    setOpen(true);
    // Auto-dismiss after a few seconds so the tooltip doesn't
    // linger on screen after the user has read it (AC #3).
    autoDismissTimer.current = window.setTimeout(() => {
      setOpen(false);
      autoDismissTimer.current = null;
    }, AUTO_DISMISS_MS);
  }, [clearTimers, measure]);

  const hide = useCallback(() => {
    clearTimers();
    setOpen(false);
  }, [clearTimers]);

  // Cancel any pending show on unmount so a delayed timer doesn't
  // try to setState on a dead component.
  useEffect(() => clearTimers, [clearTimers]);

  // Re-position when the host moves (orientation change, scroll,
  // layout shift). Cheap: a single getBoundingClientRect call when
  // open and a relevant event fires.
  useEffect(() => {
    if (!open) return;
    const onReflow = () => measure();
    window.addEventListener("scroll", onReflow, true);
    window.addEventListener("resize", onReflow);
    return () => {
      window.removeEventListener("scroll", onReflow, true);
      window.removeEventListener("resize", onReflow);
    };
  }, [open, measure]);

  const onPointerEnter = useCallback(() => {
    // Pointer enter covers both mouse hover and pen hover. The
    // short delay prevents the tooltip from flashing as the
    // cursor traverses unrelated areas of the page.
    hoverTimer.current = window.setTimeout(() => {
      hoverTimer.current = null;
      show();
    }, HOVER_DELAY_MS);
  }, [show]);

  const onPointerLeave = useCallback(() => {
    if (touchActive.current) return; // touch release handler dismisses
    hide();
  }, [hide]);

  const onFocus = useCallback(() => {
    // Keyboard focus shows the tooltip immediately — the user is
    // explicitly asking what the control does.
    show();
  }, [show]);

  const onBlur = useCallback(() => {
    hide();
  }, [hide]);

  const onKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) {
        e.stopPropagation();
        hide();
      }
    },
    [hide, open],
  );

  const onTouchStart = useCallback(
    (_e: TouchEvent) => {
      touchActive.current = true;
      longPressTimer.current = window.setTimeout(() => {
        longPressTimer.current = null;
        show();
      }, LONG_PRESS_MS);
    },
    [show],
  );

  const onTouchEnd = useCallback(() => {
    // Touch release dismisses regardless of whether the long-press
    // timer had fired yet.
    if (longPressTimer.current !== null) {
      window.clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
    touchActive.current = false;
    hide();
  }, [hide]);

  if (!isValidElement(children)) {
    throw new Error("Tooltip: children must be a single React element");
  }
  // Inject the tooltip glue onto the host element. The host's own
  // onPointerEnter / onKeyDown are preserved (we re-invoke them
  // after the tooltip's handlers so a parent's logic still runs).
  const childProps = children.props as Record<string, unknown>;
  const setHostRef = (node: HTMLElement | null) => {
    hostRef.current = node;
  };
  // Chain THREE refs onto the wrapped child: (a) the parent's
  // forwarded ref from ``<Tooltip ref={...}>`` (forwardRef form);
  // (b) the host's own ``ref={...}`` if it was set on the child
  // directly; (c) the tooltip's internal positioning ref. The
  // combined ref runs all three on every commit so neither path
  // observes the wrong node. React 18 strips the ``ref`` from a
  // child element's props before the parent component sees it, so
  // path (b) needs ``childProps``'s ``ref`` — which React leaves
  // intact in some flows and strips in others; we defend in
  // depth by also writing through ``forwardedRef``.
  const combinedRef = chainRefs([forwardedRef, childProps.ref, setHostRef]);
  const augmented = cloneElement(children as ReactElement<Record<string, unknown>>, {
    "aria-describedby": open ? tooltipId : undefined,
    ref: combinedRef,
    onPointerEnter: chain(childProps.onPointerEnter, onPointerEnter),
    onPointerLeave: chain(childProps.onPointerLeave, onPointerLeave),
    onFocus: chain(childProps.onFocus, onFocus),
    onBlur: chain(childProps.onBlur, onBlur),
    onKeyDown: chain(childProps.onKeyDown, onKeyDown),
    onTouchStart: chain(childProps.onTouchStart, onTouchStart),
    onTouchEnd: chain(childProps.onTouchEnd, onTouchEnd),
  });

  const style: CSSProperties | undefined =
    open && pos
      ? { left: `${pos.left}px`, top: `${pos.top}px` }
      : undefined;

  return (
    <>
      {augmented}
      {open ? (
        <span
          id={tooltipId}
          role="tooltip"
          className="tooltip-floating"
          aria-hidden="false"
          style={style}
        >
          {label}
        </span>
      ) : null}
    </>
  );
});

/** Compose two optional single-arg handlers so the wrapped control
 *  can keep its own focus / pointer handlers while the tooltip
 *  observes them. ``Function`` is the broadest signature React
 *  accepts for a handler prop and lets the typed
 *  ``(e: KeyboardEvent) => void`` / ``(e: TouchEvent) => void`` we
 *  declared on the wrapper be assigned without explicit casting. */
function chain(existing: unknown, added: (...args: never[]) => void): (...args: never[]) => void {
  if (typeof existing === "function") {
    return (...args: never[]) => {
      (existing as (...a: never[]) => void)(...args);
      added(...args);
    };
  }
  return added;
}

/** Compose several refs (forwarded, host-side, internal) into a
 *  single callback ref. Each entry is either a callback ``(node) =>
 *  ...``, a ref object ``{ current: T | null }``, or absent. The
 *  returned function runs every present entry on every commit so
 *  neither the parent nor the tooltip's internal positioning
 *  observe a stale node. */
function chainRefs(refs: Array<unknown>): (node: HTMLElement | null) => void {
  const observers = refs.filter((r) => r != null).map((ref) => {
    if (typeof ref === "function") {
      return ref as (node: HTMLElement | null) => void;
    }
    if (typeof ref === "object" && ref !== null && "current" in ref) {
      const refObj = ref as { current: HTMLElement | null };
      return (node: HTMLElement | null) => {
        refObj.current = node;
      };
    }
    return () => {};
  });
  if (observers.length === 0) return () => {};
  if (observers.length === 1) return observers[0];
  return (node) => {
    for (const o of observers) o(node);
  };
}

// Re-export the ReactNode prop name for the test so callers can
// mock the wrapper without importing the full React types.
export type TooltipChild = ReactNode;

