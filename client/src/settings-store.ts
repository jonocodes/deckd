import { useCallback, useState } from "react";

/** Client-side, per-device settings persisted to ``localStorage``. All
 * ``deckd.*`` keys are namespaced so a shared origin (T10 token pairing
 * arrives on same-host) doesn't collide with anyone else's storage.
 *
 * Read precedence at hook init:
 *   URL query param   > localStorage > compiled-in default
 *
 * A URL param is a one-shot dev-time override (documented in the README).
 * Once the user edits a value via the settings UI, that value is written
 * to localStorage — the URL param still wins the *next* time the page
 * loads with the param present. */

const SCALE_KEY = "deckd.scrollScale";
const INVERT_KEY = "deckd.scrollInvert";

export const SCROLL_SCALE_MIN = 1;
export const SCROLL_SCALE_MAX = 10;
export const SCROLL_SCALE_DEFAULT = 3;

export function clampScale(n: number): number {
  if (!Number.isFinite(n)) return SCROLL_SCALE_DEFAULT;
  return Math.max(SCROLL_SCALE_MIN, Math.min(SCROLL_SCALE_MAX, Math.round(n)));
}

function readBoolQuery(name: string): boolean | null {
  const raw = new URLSearchParams(window.location.search).get(name);
  if (raw === null) return null;
  return ["1", "true", "yes", "on"].includes(raw.toLowerCase());
}

function readInitialScale(): number {
  try {
    const url = new URLSearchParams(window.location.search).get("scrollScale");
    if (url !== null) return clampScale(Number(url));
    const stored = localStorage.getItem(SCALE_KEY);
    if (stored !== null) return clampScale(Number(stored));
  } catch {
    // localStorage can throw (Safari private mode, disabled cookies).
    // Fall through to the default.
  }
  return SCROLL_SCALE_DEFAULT;
}

function readInitialInvert(): boolean {
  try {
    const fromUrl = readBoolQuery("scrollInvert");
    if (fromUrl !== null) return fromUrl;
    const stored = localStorage.getItem(INVERT_KEY);
    if (stored !== null) return stored === "true";
  } catch {
    // see readInitialScale.
  }
  return false;
}

function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Same failure modes as read; a runtime setting that survives just
    // the session is better than crashing the click handler.
  }
}

/** Scroll tuning shared between the JogStrip widgets and the Settings
 * view. State lives in this hook so a single source of truth drives both
 * the live behaviour and the stepper UI. */
export function useScrollSettings() {
  const [scale, setScaleState] = useState<number>(readInitialScale);
  const [invert, setInvertState] = useState<boolean>(readInitialInvert);

  const setScale = useCallback((n: number) => {
    const clamped = clampScale(n);
    setScaleState(clamped);
    safeSet(SCALE_KEY, String(clamped));
  }, []);

  const setInvert = useCallback((v: boolean) => {
    setInvertState(v);
    safeSet(INVERT_KEY, String(v));
  }, []);

  return { scale, invert, setScale, setInvert };
}
