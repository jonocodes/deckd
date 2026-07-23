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
const CONTENT_SCALE_KEY = "deckd.contentScale";
const JOG_WIDTH_KEY = "deckd.jogWidth";
const BOTTOM_SCALE_KEY = "deckd.bottomScale";
const LABEL_SCALE_KEY = "deckd.labelScale";

const WAKE_LOCK_DEFAULT = true;

export const SCROLL_SCALE_MIN = 1;
export const SCROLL_SCALE_MAX = 10;
export const SCROLL_SCALE_DEFAULT = 3;

// Multiplier applied to grid content (button icon + label, in-grid jogstrip)
// on top of the responsive base size, so the user can dial readability per
// device. 1.0 reproduces the base look; range/step match the other sliders'
// conventions. See issue #37 / ADR-0006 (client-side per-device visual prefs).
export const CONTENT_SCALE_MIN = 0.75;
export const CONTENT_SCALE_MAX = 2.5;
export const CONTENT_SCALE_STEP = 0.1;
export const CONTENT_SCALE_DEFAULT = 1.0;

// Width multiplier for the persistent right-side scroll strip (the "scroll
// bar"). Applied on top of its responsive base width via a ``--jog-width``
// CSS var, so the user can make the strip narrower on a device where the
// default reads as too wide. 1.0 is the base width; max is capped at 1.0
// since the complaint the setting answers is "too wide", not "too narrow".
export const JOG_WIDTH_MIN = 0.4;
export const JOG_WIDTH_MAX = 1.0;
export const JOG_WIDTH_STEP = 0.05;
export const JOG_WIDTH_DEFAULT = 1.0;

// Size multiplier for the persistent bottom chrome bar (app badge, connection
// dot, trackpad + settings buttons). Applied on top of its base metrics via a
// ``--bottom-scale`` CSS var, so the user can make the bar shorter on a device
// where the default reads as too tall. 1.0 is the base size; capped at 1.0
// since the complaint the setting answers is "too big", not "too small".
export const BOTTOM_SCALE_MIN = 0.4;
export const BOTTOM_SCALE_MAX = 1.0;
export const BOTTOM_SCALE_STEP = 0.05;
export const BOTTOM_SCALE_DEFAULT = 1.0;

// Size multiplier for the button label (the text caption under each grid
// icon), applied on top of the content scale via a ``--label-scale`` CSS var,
// so the caption can be dialled down without shrinking the icon. 1.0 is the
// base size; the range allows both shrinking and modest growth.
export const LABEL_SCALE_MIN = 0.5;
export const LABEL_SCALE_MAX = 1.5;
export const LABEL_SCALE_STEP = 0.1;
export const LABEL_SCALE_DEFAULT = 1.0;

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

export function clampContentScale(n: number): number {
  if (!Number.isFinite(n)) return CONTENT_SCALE_DEFAULT;
  const clamped = Math.max(CONTENT_SCALE_MIN, Math.min(CONTENT_SCALE_MAX, n));
  return Math.round(clamped / CONTENT_SCALE_STEP) * CONTENT_SCALE_STEP;
}

export function clampJogWidth(n: number): number {
  if (!Number.isFinite(n)) return JOG_WIDTH_DEFAULT;
  const clamped = Math.max(JOG_WIDTH_MIN, Math.min(JOG_WIDTH_MAX, n));
  return Math.round(clamped / JOG_WIDTH_STEP) * JOG_WIDTH_STEP;
}

export function clampBottomScale(n: number): number {
  if (!Number.isFinite(n)) return BOTTOM_SCALE_DEFAULT;
  const clamped = Math.max(BOTTOM_SCALE_MIN, Math.min(BOTTOM_SCALE_MAX, n));
  return Math.round(clamped / BOTTOM_SCALE_STEP) * BOTTOM_SCALE_STEP;
}

export function clampLabelScale(n: number): number {
  if (!Number.isFinite(n)) return LABEL_SCALE_DEFAULT;
  const clamped = Math.max(LABEL_SCALE_MIN, Math.min(LABEL_SCALE_MAX, n));
  return Math.round(clamped / LABEL_SCALE_STEP) * LABEL_SCALE_STEP;
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

function readInitialContentScale(): number {
  try {
    const url = new URLSearchParams(window.location.search).get("contentScale");
    if (url !== null) return clampContentScale(Number(url));
    const stored = localStorage.getItem(CONTENT_SCALE_KEY);
    if (stored !== null) return clampContentScale(Number(stored));
  } catch {
    // see readInitialScale.
  }
  return CONTENT_SCALE_DEFAULT;
}


function readInitialJogWidth(): number {
  try {
    const url = new URLSearchParams(window.location.search).get("jogWidth");
    if (url !== null) return clampJogWidth(Number(url));
    const stored = localStorage.getItem(JOG_WIDTH_KEY);
    if (stored !== null) return clampJogWidth(Number(stored));
  } catch {
    // see readInitialScale.
  }
  return JOG_WIDTH_DEFAULT;
}

function readInitialBottomScale(): number {
  try {
    const url = new URLSearchParams(window.location.search).get("bottomScale");
    if (url !== null) return clampBottomScale(Number(url));
    const stored = localStorage.getItem(BOTTOM_SCALE_KEY);
    if (stored !== null) return clampBottomScale(Number(stored));
  } catch {
    // see readInitialScale.
  }
  return BOTTOM_SCALE_DEFAULT;
}

function readInitialLabelScale(): number {
  try {
    const url = new URLSearchParams(window.location.search).get("labelScale");
    if (url !== null) return clampLabelScale(Number(url));
    const stored = localStorage.getItem(LABEL_SCALE_KEY);
    if (stored !== null) return clampLabelScale(Number(stored));
  } catch {
    // see readInitialScale.
  }
  return LABEL_SCALE_DEFAULT;
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

/** Content-size multiplier for grid content (buttons + in-grid jogstrip),
 * applied on top of the responsive base via a ``--content-scale`` CSS var.
 * Same URL / localStorage / default read precedence as the other settings. */
export function useContentScale() {
  const [scale, setScaleState] = useState<number>(readInitialContentScale);

  const setScale = useCallback((n: number) => {
    const clamped = clampContentScale(n);
    setScaleState(clamped);
    safeSet(CONTENT_SCALE_KEY, String(clamped));
  }, []);

  return { scale, setScale };
}

/** Width multiplier for the persistent right-side scroll strip, applied on
 * top of its responsive base width via a ``--jog-width`` CSS var. Same URL /
 * localStorage / default read precedence as the other settings. */
export function useJogWidth() {
  const [width, setWidthState] = useState<number>(readInitialJogWidth);

  const setWidth = useCallback((n: number) => {
    const clamped = clampJogWidth(n);
    setWidthState(clamped);
    safeSet(JOG_WIDTH_KEY, String(clamped));
  }, []);

  return { width, setWidth };
}

/** Size multiplier for the persistent bottom chrome bar, applied on top of
 * its base metrics via a ``--bottom-scale`` CSS var. Same URL / localStorage
 * / default read precedence as the other settings. */
export function useBottomScale() {
  const [scale, setScaleState] = useState<number>(readInitialBottomScale);

  const setScale = useCallback((n: number) => {
    const clamped = clampBottomScale(n);
    setScaleState(clamped);
    safeSet(BOTTOM_SCALE_KEY, String(clamped));
  }, []);

  return { scale, setScale };
}

/** Size multiplier for the grid button label (the caption under each icon),
 * applied on top of the content scale via a ``--label-scale`` CSS var. Same
 * URL / localStorage / default read precedence as the other settings. */
export function useLabelScale() {
  const [scale, setScaleState] = useState<number>(readInitialLabelScale);

  const setScale = useCallback((n: number) => {
    const clamped = clampLabelScale(n);
    setScaleState(clamped);
    safeSet(LABEL_SCALE_KEY, String(clamped));
  }, []);

  return { scale, setScale };
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
