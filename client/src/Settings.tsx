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
export function Settings({ layout, status }: Props) {
  const orientation = useOrientation();
  const standalone = useStandaloneMode();
  const viewport = useViewportSize();

  const rows: Array<[string, string]> = [
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
