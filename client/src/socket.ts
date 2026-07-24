import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientMessage, ServerMessage } from "./protocol";

type Status = "connecting" | "open" | "closed" | "unauthorized";

// localStorage key for the remote-client shared password (issue #16). The
// ``deckd.*`` namespace is shared with the per-device settings store.
const PASSWORD_KEY = "deckd.password";

function loadStoredPassword(): string {
  try {
    return window.localStorage.getItem(PASSWORD_KEY) ?? "";
  } catch {
    return "";
  }
}

function storePassword(value: string): void {
  try {
    if (value) window.localStorage.setItem(PASSWORD_KEY, value);
    else window.localStorage.removeItem(PASSWORD_KEY);
  } catch {
    // Private-mode / disabled storage: keep the value in memory only.
  }
}

export function useDeckdSocket(
  onLayout: (m: Extract<ServerMessage, { type: "layout" }>) => void,
  options: { enabled?: boolean } = {},
) {
  const { enabled = true } = options;
  // In demo mode the socket is disabled and reported as ``open`` so the
  // chrome connection indicator reads "live" against a fixture layout.
  const [status, setStatus] = useState<Status>(enabled ? "connecting" : "open");
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(500);
  // Held in a ref so a reconnect (bumping ``gen``) always sends the latest
  // password without re-subscribing every consumer of the hook.
  const passwordRef = useRef<string>(loadStoredPassword());
  // Reactive mirror of "do we have a stored password" so the Settings panel
  // can show/hide the log-out control.
  const [hasPassword, setHasPassword] = useState(() => !!passwordRef.current);
  // Latches when the daemon answers ``unauthorized`` so ``onclose`` stops the
  // reconnect loop — otherwise we'd hammer the daemon with bad credentials.
  const unauthorizedRef = useRef(false);
  // Bumped by ``authenticate`` to force the connect effect to re-run.
  const [gen, setGen] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let stopped = false;
    let timer: number | undefined;

    const connect = () => {
      if (stopped) return;
      const ws_url = resolve_ws_url();
      let ws: WebSocket;
      try {
        ws = new WebSocket(ws_url);
      } catch (err) {
        console.error("invalid deckd WebSocket URL", ws_url, err);
        setStatus("closed");
        timer = window.setTimeout(connect, Math.min(backoffRef.current, 8000));
        backoffRef.current *= 2;
        return;
      }
      wsRef.current = ws;
      setStatus("connecting");

      ws.onopen = () => {
        setStatus("open");
        backoffRef.current = 500;
        const password = passwordRef.current;
        const hello: ClientMessage = {
          type: "hello",
          client: "web",
          ...(password ? { password } : {}),
        };
        ws.send(JSON.stringify(hello));
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as ServerMessage;
          if (msg.type === "layout") onLayout(msg);
          else if (msg.type === "error" && msg.reason === "unauthorized") {
            // Wrong/absent password: stop reconnecting and prompt the user.
            unauthorizedRef.current = true;
            setStatus("unauthorized");
            ws.close();
          }
        } catch {
          // ignore malformed
        }
      };

      ws.onclose = () => {
        if (stopped || unauthorizedRef.current) {
          if (!unauthorizedRef.current) setStatus("closed");
          return;
        }
        setStatus("closed");
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
  }, [onLayout, enabled, gen]);

  const send = (msg: ClientMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  };

  // Store a new password and force an immediate reconnect that presents it.
  const authenticate = useCallback((password: string) => {
    passwordRef.current = password;
    storePassword(password);
    setHasPassword(!!password);
    unauthorizedRef.current = false;
    backoffRef.current = 500;
    setGen((g) => g + 1);
  }, []);

  // Forget the stored password and reconnect with none — the daemon (auth on)
  // then rejects and the gate reappears. A no-op-looking reconnect if the
  // daemon runs --no-auth (nothing to log out of).
  const deauthenticate = useCallback(() => {
    passwordRef.current = "";
    storePassword("");
    setHasPassword(false);
    unauthorizedRef.current = false;
    backoffRef.current = 500;
    setGen((g) => g + 1);
  }, []);

  return { status, send, authenticate, deauthenticate, hasPassword };
}

function resolve_ws_url(): string {
  const env = ((import.meta.env.VITE_DECKD_WS ?? "") as string).trim();
  if (env) {
    const url = parse_ws_url(env);
    if (url) return url;
    console.warn("Ignoring invalid VITE_DECKD_WS", env);
  }
  // Default to same-origin ``/ws``. When the client is loaded via Vite,
  // ``vite.config.ts`` proxies ``/ws`` to the daemon; when loaded directly
  // from the daemon (via --client-dist), this hits the daemon's own /ws.
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = new URL("/ws", window.location.href);
  url.protocol = proto;
  return url.toString();
}

function parse_ws_url(value: string): string | null {
  try {
    const url = new URL(value, window.location.href);
    if (url.protocol !== "ws:" && url.protocol !== "wss:") return null;
    return url.toString();
  } catch {
    return null;
  }
}
