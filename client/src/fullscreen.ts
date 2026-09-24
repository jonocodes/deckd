import { useCallback, useEffect, useState } from "react";

/** Track document fullscreen state and expose a toggle. The "enter" side
 * must be called from a user gesture (tap / keydown) — the browser enforces
 * that, so the hook only forwards the request. The ``fullscreenchange``
 * sync means external exits (system back gesture, Esc) update the state
 * without extra wiring. All calls are guarded: jsdom and older browsers
 * lack the API, in which case the state is permanently false and the
 * toggle is a no-op. */
export function useFullscreen(): [boolean, () => void] {
  const [isFullscreen, setFullscreen] = useState(
    () => typeof document !== "undefined" && document.fullscreenElement != null,
  );

  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement != null);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const toggle = useCallback(() => {
    if (!document.fullscreenEnabled) return;
    if (document.fullscreenElement != null) {
      void document.exitFullscreen().catch(() => {});
    } else {
      void document.documentElement
        .requestFullscreen({ navigationUI: "hide" })
        .catch(() => {});
    }
  }, []);

  return [isFullscreen, toggle];
}
