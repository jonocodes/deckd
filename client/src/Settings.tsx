import { useEffect, useMemo, useState } from "react";
import { useOrientation } from "./orientation";
import { SCROLL_UNITS_PER_PX, SCROLL_DIRECTION } from "./JogStrip";
import type { ServerLayout } from "./protocol";

type SocketStatus = "connecting" | "open" | "closed";

type Props = {
  layout: ServerLayout | null;
  status: SocketStatus;
};

/** Read-only diagnostics view. Editable settings (scroll tuning etc.)
 * are T13; this ships enough of the settings surface for a user to check
 * "why isn't PWA install working" / "is the socket really open" / "which
 * layout am I on right now" without opening devtools on the phone. */
type Health = {
  hostname?: string;
  os?: string;
  desktop?: string;
};

export function Settings({ layout, status }: Props) {
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
    ["Scroll scale", `${SCROLL_UNITS_PER_PX} px/unit`],
    ["Scroll invert", SCROLL_DIRECTION < 0 ? "yes" : "no"],
    ["User agent", navigator.userAgent],
  ];

  return (
    <div className="settings" role="region" aria-label="Diagnostics">
      <h2 className="settings-title">Diagnostics</h2>
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

/** Resolve an HTTP URL for a daemon endpoint. Mirrors socket.ts's
 * WebSocket resolution so a Vite dev server at :5173 correctly forwards
 * fetches to the daemon at :8765, and the ``VITE_DECKD_WS`` env override
 * used for LAN phone testing points fetches at the same host as the
 * WebSocket. */
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
  const url = new URL(path, window.location.href);
  if (window.location.port === "5173") url.port = "8765";
  return url.toString();
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
