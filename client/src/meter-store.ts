import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ServerWidgetUpdate } from "./protocol";

/** Latest reading for one widget id, or ``null`` if no reading has arrived
 * yet (or the widget was just hidden by a layout change). Unit lives on
 * the reading because it's the sensor's, not the widget's, and different
 * sources could (in principle) bind to the same widget id over time. */
export type MeterReading = {
  value: number;
  unit: string;
  stale: boolean;
};

const METER_KEY_PREFIX = "deckd.meter.";
// Stale the stored value on reconnect after this many seconds without a
// fresh push. The daemon normally re-pushes on the first poll after a
// session opens; if it doesn't (e.g. a sensor was never available), the
// UI shouldn't claim an ancient value is current forever.
const STALE_AFTER_S = 10;

/** Read the persisted last-known readings from localStorage. Used as a
 * ``useState`` lazy initializer so the initial render already shows
 * the last value rather than flashing "—" before an effect fires. */
function loadInitial(): Record<string, MeterReading> {
  if (typeof window === "undefined") return {};
  const initial: Record<string, MeterReading> = {};
  for (let i = 0; i < window.localStorage.length; i++) {
    const key = window.localStorage.key(i);
    if (!key || !key.startsWith(METER_KEY_PREFIX)) continue;
    try {
      const parsed = JSON.parse(window.localStorage.getItem(key) ?? "null");
      if (
        parsed &&
        typeof parsed.value === "number" &&
        typeof parsed.unit === "string"
      ) {
        initial[key.slice(METER_KEY_PREFIX.length)] = {
          value: parsed.value,
          unit: parsed.unit,
          stale: true,
        };
      }
    } catch {
      // ignore corrupted entries
    }
  }
  return initial;
}

/**
 * Hook: hold a map of widget-id -> latest reading, fed by
 * ``widget_update`` WebSocket frames.
 *
 * Returned API:
 *   ``readings`` — current map (id -> reading). Render-time consumers
 *     read this directly; ``MeterCell`` filters by its own widget id.
 *   ``onUpdate(frame)`` — feed in a server frame.
 *
 * One shared instance is held at the ``App`` level so every meter cell
 * subscribes to the same map without prop-drilling. Entries whose ids
 * are not in ``activeWidgetIds`` are filtered out at render time so a
 * removed meter doesn't leave ghost values on screen, and re-adding
 * the same id later reads the cached value back from localStorage.
 */
export function useMeterStore(activeWidgetIds: ReadonlySet<string>) {
  const [readings, setReadings] = useState<Record<string, MeterReading>>(loadInitial);
  // Ref-mirror so the stale-detection interval (which calls setState)
  // doesn't need to depend on the readings state — otherwise every push
  // would tear down and re-create the timer.
  const readingsRef = useRef(readings);
  readingsRef.current = readings;

  const onUpdate = useCallback((m: ServerWidgetUpdate) => {
    setReadings((prev) => {
      // Skip the state update + storage write entirely if the value
      // hasn't changed. A 1Hz push of an unchanged CPU temp would
      // otherwise mean a re-render of every meter on every tick, which
      // (a) wastes work and (b) re-fires the meter-cell's transition
      // animation. We compare on the three fields the UI actually
      // renders: value, stale flag, and unit.
      const existing = prev[m.id];
      if (
        existing &&
        existing.value === m.value &&
        existing.stale === m.stale &&
        existing.unit === m.unit
      ) {
        return prev;
      }
      const next = {
        ...prev,
        [m.id]: { value: m.value, unit: m.unit, stale: m.stale },
      };
      try {
        // Persist the most recent reading so a page reload doesn't
        // flash a blank meter until the next push lands. The full set
        // is small (a handful of widgets per layout), so a single
        // JSON blob per id keeps writes cheap and survives quota
        // pressure better than one key per push.
        window.localStorage.setItem(
          `${METER_KEY_PREFIX}${m.id}`,
          JSON.stringify({ value: m.value, unit: m.unit, stale: m.stale, source: m.source }),
        );
      } catch {
        // Private mode / quota: stay in memory only.
      }
      return next;
    });
  }, []);

  // Mark everything stale after ``STALE_AFTER_S`` of no updates. This
  // is the reconnect-with-no-push case: a fresh page open that hasn't
  // seen a server frame yet should NOT show the last value as fresh.
  // The interval is registered once (no deps) and reads the latest
  // readings via a ref so it doesn't tear itself down on every push.
  useEffect(() => {
    const id = window.setInterval(() => {
      const cur = readingsRef.current;
      let changed = false;
      const next: Record<string, MeterReading> = { ...cur };
      for (const [wid, r] of Object.entries(cur)) {
        if (!r.stale) {
          next[wid] = { ...r, stale: true };
          changed = true;
        }
      }
      if (changed) setReadings(next);
    }, STALE_AFTER_S * 1000);
    return () => window.clearInterval(id);
  }, []);

  // Filter the live map down to just the ids the active layout
  // references. Done as a render-time memo (not an effect) so React
  // schedules a single render when both the readings map and the
  // active-id set change; an effect-based reap would render once
  // with stale entries, then again after the effect fires.
  const visibleReadings = useMemo(() => {
    if (readings === EMPTY_RECORD) return readings;
    let filtered: Record<string, MeterReading> | null = null;
    for (const id of Object.keys(readings)) {
      if (!activeWidgetIds.has(id)) {
        filtered = filtered ?? { ...readings };
        delete filtered[id];
      }
    }
    return filtered ?? readings;
  }, [readings, activeWidgetIds]);

  const reading = useCallback(
    (id: string): MeterReading | null => readings[id] ?? null,
    [readings],
  );

  // Memoise the returned object so its identity only changes when one of
  // its members actually changes. Consumers that put the store in an effect
  // dependency array (e.g. App's demo-seed effect) then don't re-run on
  // unrelated renders. ``onUpdate`` is independently stable, so callers that
  // only need it (the socket's widget_update handler) can — and must — depend
  // on ``meter.onUpdate`` rather than the whole object to avoid reconnecting.
  return useMemo(
    () => ({ reading, readings: visibleReadings, onUpdate }),
    [reading, visibleReadings, onUpdate],
  );
}

// Sentinel empty record used to skip the filter pass when nothing has
// been pushed yet. ``useMemo``'s identity stability depends on the
// return value, so a fresh ``{}`` literal every render would force the
// memo to recompute even when there's nothing to filter.
const EMPTY_RECORD: Record<string, MeterReading> = Object.freeze({});

export const _INTERNAL = { METER_KEY_PREFIX };
