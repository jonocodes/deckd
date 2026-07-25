import { useCallback, useMemo, useState } from "react";
import type { MediaState } from "./protocol";

export type MediaReading = Omit<MediaState, "type">;

export function useMediaStore(activeIds: ReadonlySet<string>) {
  const [states, setStates] = useState<Record<string, MediaReading>>({});
  const onUpdate = useCallback((state: MediaState) => {
    setStates((previous) => ({ ...previous, [state.id]: state }));
  }, []);
  const visible = useMemo(() => {
    const result: Record<string, MediaReading> = {};
    for (const [id, state] of Object.entries(states)) {
      if (activeIds.has(id)) result[id] = state;
    }
    return result;
  }, [states, activeIds]);
  return useMemo(() => ({ states: visible, onUpdate }), [visible, onUpdate]);
}
