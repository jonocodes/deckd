import { useEffect, useRef } from "react";

/** Hold a Screen Wake Lock sentinel while ``enabled`` is true and the tab
 * is visible. Browsers auto-release the sentinel when the tab is hidden,
 * so we watch ``visibilitychange`` and re-acquire on the way back to
 * visible. All failures (unsupported browser, permission denied, iOS
 * quirks) are logged and swallowed — the surface must still work; it
 * just may sleep.
 *
 * The caller combines its own signals into ``enabled`` (typical shape:
 * user setting × socket-open). The hook doesn't inspect socket state or
 * user preference on its own — one clean seam. */
export function useWakeLock(enabled: boolean): void {
  const sentinelRef = useRef<WakeLockSentinel | null>(null);

  useEffect(() => {
    if (!enabled) {
      dropSentinel();
      return;
    }
    if (typeof navigator === "undefined" || !navigator.wakeLock) {
      // Feature unsupported (older Android WebView, non-secure context).
      // Log once so it's discoverable from devtools without spamming.
      console.info("[wake lock] navigator.wakeLock unavailable; screen may sleep");
      return;
    }

    let cancelled = false;

    const acquire = async () => {
      if (cancelled) return;
      if (document.hidden) return; // Sentinel request rejects while hidden.
      if (sentinelRef.current) return;
      try {
        const sentinel = await navigator.wakeLock.request("screen");
        if (cancelled) {
          void sentinel.release().catch(() => {});
          return;
        }
        sentinelRef.current = sentinel;
        // The sentinel emits "release" when the browser drops the lock
        // (tab hidden, screen off, OS pressure). Clear our ref so a later
        // visibility change re-acquires cleanly instead of thinking a
        // stale sentinel is still live.
        sentinel.addEventListener("release", () => {
          if (sentinelRef.current === sentinel) sentinelRef.current = null;
        });
      } catch (err) {
        console.warn("[wake lock] acquire failed:", err);
      }
    };

    const onVisibility = () => {
      if (document.hidden) {
        // Browsers auto-release on hidden anyway, but call release()
        // explicitly so the spec's "released on hidden" wording holds
        // even on any non-conforming implementation.
        dropSentinel();
      } else {
        void acquire();
      }
    };

    document.addEventListener("visibilitychange", onVisibility);
    void acquire();

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisibility);
      dropSentinel();
    };

    function dropSentinel() {
      const s = sentinelRef.current;
      if (!s) return;
      sentinelRef.current = null;
      void s.release().catch(() => {});
    }
  }, [enabled]);
}
