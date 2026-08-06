import { useCallback, useMemo, useState } from "react";
import type { MediaState } from "./protocol";

export type MediaReading = Omit<MediaState, "type">;

/** Per-widget activity gate for the media cache. A row passes the
 * ``activeIds`` membership check, or — for widgets whose rows the
 * client can't enumerate up front (the ``nowplaying`` surface collects
 * ``mpris.*`` ids from the daemon) — any row whose id starts with one
 * of ``activePrefixes``. Exact-id membership is the common case; the
 * prefix set is the narrow seam for the now-playing surface. */
export function useMediaStore(
  activeIds: ReadonlySet<string>,
  activePrefixes: ReadonlySet<string> = new Set(),
) {
  const [states, setStates] = useState<Record<string, MediaReading>>({});
  const onUpdate = useCallback((state: MediaState) => {
    setStates((previous) => ({ ...previous, [state.id]: state }));
  }, []);
  const visible = useMemo(() => {
    const result: Record<string, MediaReading> = {};
    for (const [id, state] of Object.entries(states)) {
      if (activeIds.has(id)) {
        result[id] = state;
        continue;
      }
      for (const prefix of activePrefixes) {
        if (id.startsWith(prefix)) {
          result[id] = state;
          break;
        }
      }
    }
    return result;
  }, [states, activeIds, activePrefixes]);
  return useMemo(() => ({ states: visible, onUpdate }), [visible, onUpdate]);
}
