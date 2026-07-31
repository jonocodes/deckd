import { useEffect, useState } from "react";

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
