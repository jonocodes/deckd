import { useEffect, useMemo, useState } from "react";
import { useOrientation } from "./orientation";
import { SCROLL_SCALE_MAX, SCROLL_SCALE_MIN } from "./settings-store";
import type { ServerLayout } from "./protocol";

type SocketStatus = "connecting" | "open" | "closed";

type Props = {
  layout: ServerLayout | null;
  status: SocketStatus;
  scrollScale: number;
  scrollInvert: boolean;
  onScrollScaleChange: (n: number) => void;
  onScrollInvertChange: (v: boolean) => void;
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
    ["User agent", navigator.userAgent],
  ];

  return (
    <div className="settings" role="region" aria-label="Settings">
      <h2 className="settings-title">Scroll</h2>
      <div className="settings-controls">
        <div className="settings-control">
          <span className="settings-control-label">Scale</span>
          <div className="stepper" role="group" aria-label="Scroll scale">
            <button
              type="button"
              className="stepper-btn"
              aria-label="Decrease scroll scale"
              disabled={scrollScale <= SCROLL_SCALE_MIN}
              onPointerDown={(e) => {
                e.preventDefault();
                onScrollScaleChange(scrollScale - 1);
              }}
            >
              −
            </button>
            <span className="stepper-value" aria-live="polite">{scrollScale}</span>
            <button
              type="button"
              className="stepper-btn"
              aria-label="Increase scroll scale"
              disabled={scrollScale >= SCROLL_SCALE_MAX}
              onPointerDown={(e) => {
                e.preventDefault();
                onScrollScaleChange(scrollScale + 1);
              }}
            >
              +
            </button>
          </div>
          <span className="settings-control-hint">px per wheel unit</span>
        </div>
        <div className="settings-control">
          <span className="settings-control-label">Invert</span>
          <button
            type="button"
            role="switch"
            aria-checked={scrollInvert}
            className={`toggle${scrollInvert ? " toggle-on" : ""}`}
            onPointerDown={(e) => {
              e.preventDefault();
              onScrollInvertChange(!scrollInvert);
            }}
          >
            <span className="toggle-track" />
            <span className="toggle-thumb" />
          </button>
          <span className="settings-control-hint">
            {scrollInvert ? "reversed" : "default"}
          </span>
        </div>
      </div>

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
