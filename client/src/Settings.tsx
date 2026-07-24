import { useEffect, useMemo, useState } from "react";
import { useOrientation } from "./orientation";
import {
  BOTTOM_SCALE_MAX,
  BOTTOM_SCALE_MIN,
  BOTTOM_SCALE_STEP,
  CONTENT_SCALE_MAX,
  CONTENT_SCALE_MIN,
  CONTENT_SCALE_STEP,
  JOG_WIDTH_MAX,
  JOG_WIDTH_MIN,
  JOG_WIDTH_STEP,
  LABEL_SCALE_MAX,
  LABEL_SCALE_MIN,
  LABEL_SCALE_STEP,
  PAD_SENS_MAX,
  PAD_SENS_MIN,
  PAD_SENS_STEP,
  SCROLL_SCALE_MAX,
  SCROLL_SCALE_MIN,
} from "./settings-store";
import type { ServerLayout } from "./protocol";

type SocketStatus = "connecting" | "open" | "closed";

type Props = {
  layout: ServerLayout | null;
  status: SocketStatus;
  scrollScale: number;
  scrollInvert: boolean;
  onScrollScaleChange: (n: number) => void;
  onScrollInvertChange: (v: boolean) => void;
  trackpadSensitivity: number;
  onTrackpadSensitivityChange: (n: number) => void;
  wakeLockEnabled: boolean;
  onWakeLockChange: (v: boolean) => void;
  contentScale: number;
  onContentScaleChange: (n: number) => void;
  jogWidth: number;
  onJogWidthChange: (n: number) => void;
  bottomScale: number;
  onBottomScaleChange: (n: number) => void;
  labelScale: number;
  onLabelScaleChange: (n: number) => void;
  /** True when a password is stored, so the log-out control is worth showing. */
  canDeauthenticate?: boolean;
  /** Forget the stored password and drop back to the gate. */
  onDeauthenticate?: () => void;
};

type Health = {
  hostname?: string;
  os?: string;
  desktop?: string;
};

/** Editable client settings (scroll tuning) plus a read-only diagnostics
 * dump. State for the editable half lives one level up in ``App`` so the
 * jogstrip widgets and the settings UI see the same values live. */
export function Settings({
  layout,
  status,
  scrollScale,
  scrollInvert,
  onScrollScaleChange,
  onScrollInvertChange,
  trackpadSensitivity,
  onTrackpadSensitivityChange,
  wakeLockEnabled,
  onWakeLockChange,
  contentScale,
  onContentScaleChange,
  jogWidth,
  onJogWidthChange,
  bottomScale,
  onBottomScaleChange,
  labelScale,
  onLabelScaleChange,
  canDeauthenticate,
  onDeauthenticate,
}: Props) {
  const orientation = useOrientation();
  const standalone = useStandaloneMode();
  const viewport = useViewportSize();
  const health = useDaemonHealth();

  const rows: Array<[string, string]> = [
    ["Host", health?.hostname ?? "…"],
    ["Host OS", health?.os ?? "…"],
    ["Desktop", health?.desktop ?? "…"],
    ["PWA / standalone", standalone ? "yes" : "no"],
    ["Connection", status],
    ["App", layout?.app ?? "—"],
    ["Widgets", layout ? String(layout.widgets.length) : "—"],
    ["Chrome jogstrip", layout ? (layout.jogstrip_enabled ? "on" : "off") : "—"],
    ["Layout error", layout?.error ? "yes" : "no"],
    ["Orientation", orientation],
    ["Viewport", `${viewport[0]} × ${viewport[1]}`],
    ["Device pixel ratio", String(window.devicePixelRatio ?? 1)],
    ["WebSocket URL", currentWsUrl()],
    ["Origin", window.location.origin],
    ["Secure context", String(window.isSecureContext)],
    ["Wake lock supported", "wakeLock" in navigator ? "yes" : "no"],
    ["User agent", navigator.userAgent],
  ];

  return (
    <div className="settings" role="region" aria-label="Settings">
      <h2 className="settings-title">Scroll</h2>
      <div className="settings-controls">
        <div className="settings-control">
          <span className="settings-control-label">Scale</span>
          <input
            type="range"
            className="slider"
            aria-label="Scroll scale"
            min={SCROLL_SCALE_MIN}
            max={SCROLL_SCALE_MAX}
            step={1}
            value={scrollScale}
            onChange={(e) => onScrollScaleChange(Number(e.target.value))}
          />
          <span className="settings-control-value" aria-live="polite">
            {scrollScale}
          </span>
        </div>
        <div className="settings-control">
          <span className="settings-control-label">Bar width</span>
          <input
            type="range"
            className="slider"
            aria-label="Scroll bar width"
            min={JOG_WIDTH_MIN}
            max={JOG_WIDTH_MAX}
            step={JOG_WIDTH_STEP}
            value={jogWidth}
            onChange={(e) => onJogWidthChange(Number(e.target.value))}
          />
          <span className="settings-control-value" aria-live="polite">
            {Math.round(jogWidth * 100)}%
          </span>
        </div>
        <SettingToggle
          label="Invert"
          value={scrollInvert}
          onChange={onScrollInvertChange}
        />
      </div>

      <h2 className="settings-title settings-title-sub">Trackpad</h2>
      <div className="settings-controls">
        <div className="settings-control">
          <span className="settings-control-label">Sensitivity</span>
          <input
            type="range"
            className="slider"
            aria-label="Trackpad sensitivity"
            min={PAD_SENS_MIN}
            max={PAD_SENS_MAX}
            step={PAD_SENS_STEP}
            value={trackpadSensitivity}
            onChange={(e) => onTrackpadSensitivityChange(Number(e.target.value))}
          />
          <span className="settings-control-value" aria-live="polite">
            {trackpadSensitivity.toFixed(1)}×
          </span>
        </div>
      </div>

      <h2 className="settings-title settings-title-sub">Display</h2>
      <div className="settings-controls">
        <div className="settings-control">
          <span className="settings-control-label">Content size</span>
          <input
            type="range"
            className="slider"
            aria-label="Content size"
            min={CONTENT_SCALE_MIN}
            max={CONTENT_SCALE_MAX}
            step={CONTENT_SCALE_STEP}
            value={contentScale}
            onChange={(e) => onContentScaleChange(Number(e.target.value))}
          />
          <span className="settings-control-value" aria-live="polite">
            {contentScale.toFixed(1)}×
          </span>
        </div>
        <div className="settings-control">
          <span className="settings-control-label">Text size</span>
          <input
            type="range"
            className="slider"
            aria-label="Text size"
            min={LABEL_SCALE_MIN}
            max={LABEL_SCALE_MAX}
            step={LABEL_SCALE_STEP}
            value={labelScale}
            onChange={(e) => onLabelScaleChange(Number(e.target.value))}
          />
          <span className="settings-control-value" aria-live="polite">
            {labelScale.toFixed(1)}×
          </span>
        </div>
        <div className="settings-control">
          <span className="settings-control-label">Bottom bar</span>
          <input
            type="range"
            className="slider"
            aria-label="Bottom bar size"
            min={BOTTOM_SCALE_MIN}
            max={BOTTOM_SCALE_MAX}
            step={BOTTOM_SCALE_STEP}
            value={bottomScale}
            onChange={(e) => onBottomScaleChange(Number(e.target.value))}
          />
          <span className="settings-control-value" aria-live="polite">
            {Math.round(bottomScale * 100)}%
          </span>
        </div>
        <SettingToggle
          label="Keep screen awake"
          value={wakeLockEnabled}
          onChange={onWakeLockChange}
        />
      </div>

      {canDeauthenticate && onDeauthenticate ? (
        <>
          <h2 className="settings-title settings-title-sub">Connection</h2>
          <div className="settings-controls">
            <button
              type="button"
              className="settings-logout"
              onClick={onDeauthenticate}
            >
              Log out (forget password)
            </button>
          </div>
        </>
      ) : null}

      <h2 className="settings-title settings-title-sub">Diagnostics</h2>
      <dl className="settings-list">
        {rows.map(([k, v]) => (
          <div className="settings-row" key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function SettingToggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="settings-control">
      <span className="settings-control-label">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={value}
        aria-label={label}
        className={`toggle${value ? " toggle-on" : ""}`}
        onClick={() => onChange(!value)}
      >
        <span className="toggle-track" />
        <span className="toggle-thumb" />
      </button>
      <span className="settings-control-value">{value ? "on" : "off"}</span>
    </div>
  );
}

/** ``true`` when the page is running as an installed PWA. Covers both the
 * standard ``display-mode: standalone`` media query (Chrome, Edge, modern
 * Safari) and iOS Safari's legacy ``navigator.standalone`` flag. */
function useStandaloneMode(): boolean {
  return useMemo(() => {
    if (typeof window === "undefined") return false;
    if (window.matchMedia?.("(display-mode: standalone)").matches) return true;
    if ((window.navigator as { standalone?: boolean }).standalone === true) return true;
    return false;
  }, []);
}

function useViewportSize(): [number, number] {
  const [size, setSize] = useState<[number, number]>(() => [
    window.innerWidth,
    window.innerHeight,
  ]);
  useEffect(() => {
    const onResize = () => setSize([window.innerWidth, window.innerHeight]);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return size;
}

/** One-shot fetch of the daemon's ``/health`` when the settings panel
 * mounts. The response carries hostname / OS / desktop-env identity that
 * the browser can't discover on its own. Failures fall through silently:
 * the settings panel just shows ``…`` for those rows. */
function useDaemonHealth(): Health | null {
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(daemonHttpUrl("/health"), { cache: "no-store" });
        if (!r.ok) return;
        const body = (await r.json()) as Health;
        if (!cancelled) setHealth(body);
      } catch {
        // Network or CORS error — leave the placeholder rows blank.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);
  return health;
}

/** Resolve an HTTP URL for a daemon endpoint. Same-origin by default —
 * ``vite.config.ts`` proxies ``/health`` to the daemon during dev, and the
 * daemon serves it directly when the built client is loaded via
 * --client-dist. The ``VITE_DECKD_WS`` env override lets a caller point
 * at an off-origin daemon; the http host is derived from the ws URL. */
function daemonHttpUrl(path: string): string {
  const env = ((import.meta.env.VITE_DECKD_WS ?? "") as string).trim();
  if (env) {
    try {
      const ws = new URL(env);
      const proto = ws.protocol === "wss:" ? "https:" : "http:";
      return `${proto}//${ws.host}${path}`;
    } catch {
      // fall through to same-origin resolution
    }
  }
  return new URL(path, window.location.href).toString();
}

function currentWsUrl(): string {
  try {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = new URL("/ws", window.location.href);
    url.protocol = proto;
    return url.toString();
  } catch {
    return "?";
  }
}
