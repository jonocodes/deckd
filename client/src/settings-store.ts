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
const PAD_SENS_KEY = "deckd.trackpadSensitivity";
const WAKE_LOCK_KEY = "deckd.wakeLock";

const WAKE_LOCK_DEFAULT = true;

export const SCROLL_SCALE_MIN = 1;
export const SCROLL_SCALE_MAX = 10;
export const SCROLL_SCALE_DEFAULT = 3;

// Trackpad sensitivity is a floating multiplier: 1.0 = raw (1 CSS pixel of
// finger travel = 1 uinput REL_X/Y unit), 0.5 = slower, 3.0 = fast. Range
// is set for phone-thumb-in-hand comfort — feet-away media-room use might
// want higher, we'll widen if someone asks.
export const PAD_SENS_MIN = 0.5;
export const PAD_SENS_MAX = 3.0;
export const PAD_SENS_STEP = 0.1;
export const PAD_SENS_DEFAULT = 1.0;

export function clampScale(n: number): number {
  if (!Number.isFinite(n)) return SCROLL_SCALE_DEFAULT;
  return Math.max(SCROLL_SCALE_MIN, Math.min(SCROLL_SCALE_MAX, Math.round(n)));
}

export function clampPadSensitivity(n: number): number {
  if (!Number.isFinite(n)) return PAD_SENS_DEFAULT;
  const clamped = Math.max(PAD_SENS_MIN, Math.min(PAD_SENS_MAX, n));
  // Round to the slider step so the persisted value stays representable
  // when the user tunes with the discrete slider stops.
  return Math.round(clamped / PAD_SENS_STEP) * PAD_SENS_STEP;
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

function readInitialBool(
  queryName: string,
  storageKey: string,
  fallback: boolean,
): boolean {
  try {
    const fromUrl = readBoolQuery(queryName);
    if (fromUrl !== null) return fromUrl;
    const stored = localStorage.getItem(storageKey);
    if (stored !== null) return stored === "true";
  } catch {
    // see readInitialScale.
  }
  return fallback;
}

function readInitialPadSensitivity(): number {
  try {
    const url = new URLSearchParams(window.location.search).get("padSensitivity");
    if (url !== null) return clampPadSensitivity(Number(url));
    const stored = localStorage.getItem(PAD_SENS_KEY);
    if (stored !== null) return clampPadSensitivity(Number(stored));
  } catch {
    // see readInitialScale.
  }
  return PAD_SENS_DEFAULT;
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
 * the live behaviour and the slider UI. */
export function useScrollSettings() {
  const [scale, setScaleState] = useState<number>(readInitialScale);
  const [invert, setInvertState] = useState<boolean>(() =>
    readInitialBool("scrollInvert", INVERT_KEY, false),
  );

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

/** Trackpad sensitivity for the pointer-move path. Same URL / localStorage
 * / default read precedence as the scroll settings. */
export function useTrackpadSettings() {
  const [sensitivity, setSensitivityState] = useState<number>(readInitialPadSensitivity);

  const setSensitivity = useCallback((n: number) => {
    const clamped = clampPadSensitivity(n);
    setSensitivityState(clamped);
    safeSet(PAD_SENS_KEY, String(clamped));
  }, []);

  return { sensitivity, setSensitivity };
}

/** User preference for the Screen Wake Lock. Defaults to true (spec:
 * acquire unconditionally); the toggle in the settings view lets a user
 * opt out if their device battery policy prefers it. */
export function useWakeLockSetting() {
  const [enabled, setEnabledState] = useState<boolean>(() =>
    readInitialBool("wakeLock", WAKE_LOCK_KEY, WAKE_LOCK_DEFAULT),
  );

  const setEnabled = useCallback((v: boolean) => {
    setEnabledState(v);
    safeSet(WAKE_LOCK_KEY, String(v));
  }, []);

  return { enabled, setEnabled };
}
