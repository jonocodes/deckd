import { useEffect, useRef, useState } from "react";
import type { ClientMessage, ServerMessage } from "./protocol";

type Status = "connecting" | "open" | "closed";

export function useDeckdSocket(onLayout: (m: Extract<ServerMessage, { type: "layout" }>) => void) {
  const [status, setStatus] = useState<Status>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(500);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;

    const connect = () => {
      if (stopped) return;
      const ws_url = resolve_ws_url();
      const ws = new WebSocket(ws_url);
      wsRef.current = ws;
      setStatus("connecting");

      ws.onopen = () => {
        setStatus("open");
        backoffRef.current = 500;
        const hello: ClientMessage = { type: "hello", client: "web" };
        ws.send(JSON.stringify(hello));
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as ServerMessage;
          if (msg.type === "layout") onLayout(msg);
        } catch {
          // ignore malformed
        }
      };

      ws.onclose = () => {
        setStatus("closed");
        if (stopped) return;
        const wait = Math.min(backoffRef.current, 8000);
        backoffRef.current = wait * 2;
        timer = window.setTimeout(connect, wait);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      wsRef.current?.close();
    };
  }, [onLayout]);

  const send = (msg: ClientMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  };

  return { status, send };
}

function resolve_ws_url(): string {
  const env = (import.meta.env.VITE_DECKD_WS ?? "") as string;
  if (env) return env;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws`;
}
