import { useEffect, useState } from "react";
import type { Widget } from "./protocol";

export type Orientation = "portrait" | "landscape";

/** Track the viewport's orientation and re-render on rotation.
 *
 * Uses the ``(orientation: portrait)`` media query rather than
 * ``window.innerWidth < innerHeight`` so re-renders are coalesced with the
 * browser's own layout pass — no polling, no jank at the rotation moment. */
export function useOrientation(): Orientation {
  const [orientation, setOrientation] = useState<Orientation>(() => currentOrientation());
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(orientation: portrait)");
    const onChange = (e: MediaQueryListEvent) =>
      setOrientation(e.matches ? "portrait" : "landscape");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return orientation;
}

function currentOrientation(): Orientation {
  if (typeof window === "undefined" || !window.matchMedia) return "landscape";
  return window.matchMedia("(orientation: portrait)").matches ? "portrait" : "landscape";
}

/** Transpose every widget's grid so a layout authored for landscape
 * (wider than tall) also fills a portrait viewport sensibly. A 4x2 firefox
 * grid becomes 2x4; a single-row terminal grid becomes a single-column.
 * Coordinates flip diagonally: ``[x, y, w, h] -> [y, x, h, w]``.
 *
 * ADR-0004 reserved orientation-specific YAML blocks for the future; until
 * a layout opts into that, this auto-transpose gives portrait devices a
 * usable button size without every layout author having to author twice. */
export function transposeWidgets(widgets: Widget[]): Widget[] {
  return widgets.map((w) => ({
    ...w,
    grid: [w.grid[1], w.grid[0], w.grid[3], w.grid[2]] as Widget["grid"],
  }));
}
