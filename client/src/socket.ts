import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientMessage, ServerChromeMedia, ServerConfirmRequest, ServerDeck, ServerMediaError, ServerMessage, ServerRunningWindows, ServerState, ServerWidgetUpdate, MediaState } from "./protocol";
import { wireDeckToServer, wireWindowsToServer } from "./protocol";

type Status = "connecting" | "open" | "closed" | "unauthorized";

// localStorage key for the remote-client shared password (issue #16). The
// ``deckd.*`` namespace is shared with the per-device settings store.
const PASSWORD_KEY = "deckd.password";

// Application-defined WebSocket close code the daemon uses to signal an auth
// rejection (must match server.py WS_CLOSE_UNAUTHORIZED). Keying off the close
// code makes the gate robust to browsers dropping the rejection data frame.
const UNAUTHORIZED_CLOSE_CODE = 4401;

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

// Demo pin: ``?deck=<name>`` forces this client to a named daemon deck
// regardless of host focus (see demo.ts for the backend-free ``?demo=``
// sibling). Read once at load; the daemon ignores an unknown name.
function readPinnedDeck(): string {
  try {
    return new URLSearchParams(window.location.search).get("deck") ?? "";
  } catch {
    return "";
  }
}

/** Human-readable one-liner for a socket close, shown in the reconnect
 * overlay (issue #64). Keyed off the WebSocket close code so a dropped
 * daemon reads differently from a deliberate close. */
function describeClose(code: number, reason: string): string {
  if (code === 1006) return "daemon not reachable";
  if (code === 1000) return "connection closed";
  const suffix = reason ? ` — ${reason}` : "";
  return `connection lost (code ${code})${suffix}`;
}

export function useDeckdSocket(
  onDeck: (m: ServerDeck) => void,
  onWidgetUpdate: (m: ServerWidgetUpdate) => void,
  onMediaState: (m: MediaState) => void,
  onChromeMedia?: (m: ServerChromeMedia) => void,
  onConfirmRequest?: (m: ServerConfirmRequest) => void,
  onRunningWindows?: (m: ServerRunningWindows) => void,
  onSessionState?: (m: ServerState) => void,
  onMediaError?: (m: ServerMediaError) => void,
  options: { enabled?: boolean } = {},
) {
  const { enabled = true } = options;
  // In demo mode the socket is disabled and reported as ``open`` so the
  // chrome connection indicator reads "live" against a fixture deck.
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
  // Reconnect feedback (issue #64). ``attempt`` counts connect attempts
  // since the last successful open; ``lastError`` is the human-readable
  // reason for the latest failure; ``cancelled`` is true after the user
  // presses Cancel and pauses the auto-retry loop. All three drive the
  // reconnecting overlay.
  const [attempt, setAttempt] = useState(0);
  const [lastError, setLastError] = useState("");
  const [cancelled, setCancelled] = useState(false);
  // True while the auto-retry loop is in flight (dialing or waiting out the
  // backoff) and not cancelled. Distinguishes "actively reconnecting" from
  // "given up" for the overlay: a drop parks in ``closed`` for the whole
  // backoff, so ``status`` alone would mislabel the wait as Disconnected.
  const [retrying, setRetrying] = useState(false);
  const attemptRef = useRef(0);
  // Read inside the effect's scheduler; a plain ref so a Cancel can stop
  // a pending timer without re-running the effect (which would tear down
  // the socket that's already gone).
  const cancelledRef = useRef(false);

  useEffect(() => {
    if (!enabled) return;
    if (cancelledRef.current) {
      setStatus("closed");
      return;
    }
    let stopped = false;
    let timer: number | undefined;

    const connect = () => {
      if (stopped || cancelledRef.current) return;
      attemptRef.current += 1;
      setAttempt(attemptRef.current);
      const ws_url = resolve_ws_url();
      let ws: WebSocket;
      try {
        ws = new WebSocket(ws_url);
      } catch (err) {
        console.error("invalid deckd WebSocket URL", ws_url, err);
        setStatus("closed");
        setLastError("could not open a connection");
        setRetrying(true);
        timer = window.setTimeout(connect, Math.min(backoffRef.current, 8000));
        backoffRef.current *= 2;
        return;
      }
      wsRef.current = ws;
      setStatus("connecting");

      ws.onopen = () => {
        setStatus("open");
        setRetrying(false);
        backoffRef.current = 500;
        attemptRef.current = 0;
        setAttempt(0);
        setLastError("");
        const password = passwordRef.current;
        const pinnedDeck = readPinnedDeck();
        const hello: ClientMessage = {
          type: "hello",
          client: "web",
          ...(password ? { password } : {}),
          ...(pinnedDeck ? { deck: pinnedDeck } : {}),
        };
        ws.send(JSON.stringify(hello));
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as ServerMessage;
          if (msg.type === "deck") onDeck(wireDeckToServer(msg));
          else if (msg.type === "widget_update") onWidgetUpdate(msg);
          else if (msg.type === "media_state") onMediaState(msg);
          // Issue #47: the daemon may push ``chrome_media`` to every
          // connected client (the indicator is global chrome) even
          // when a particular client doesn't render the media icon
          // or hasn't wired a listener yet. The handler is optional
          // so a test or a future client that doesn't care about
          // chrome-media state can drop the param without breaking
          // the dispatch. The defensive guard costs nothing and
          // keeps the wire surface forward-compatible.
          else if (msg.type === "chrome_media" && onChromeMedia) onChromeMedia(msg);
          else if (msg.type === "confirm_request" && onConfirmRequest) onConfirmRequest(msg);
          // Issue #126 / stage 2: the daemon broadcasts ``running_windows``
          // globally (chrome-media-style) so every connected session
          // holds a fresh snapshot regardless of view pin. The handler is
          // optional for the same forward-compat reason as the other
          // chrome-side frames — a client that doesn't render the list can
          // drop the param without breaking the dispatch.
          else if (msg.type === "running_windows" && onRunningWindows) {
            const cast: ServerRunningWindows = { ...msg, windows: wireWindowsToServer(msg.windows) ?? [] };
            onRunningWindows(cast);
          }
          // Issue #160: the two-state session screen awareness. Pushed
          // on every locked/blanked transition and replayed in the
          // connect snapshot, so a late joiner isn't stalled on a
          // stale deck. The handler is optional for the same
          // forward-compat reason as the other chrome-side frames.
          else if (msg.type === "state" && onSessionState) {
            onSessionState(msg);
          }
          // Issue #64: a media command this session issued failed. Surface
          // it so the client can name the player and offer a retry.
          else if (msg.type === "media_error" && onMediaError) {
            onMediaError(msg);
          }
          else if (msg.type === "error" && msg.reason === "unauthorized") {
            // Wrong/absent password: stop reconnecting and prompt the user.
            unauthorizedRef.current = true;
            setStatus("unauthorized");
            ws.close();
          }
          else if (msg.type === "error" && msg.reason === "screen_locked") {
            // A client that missed the state transition (issue #160):
            // the press was refused daemon-side; surface the lock state
            // locally so the takeover still appears. The connection
            // itself is fine — do NOT close or stop reconnecting.
            onSessionState?.({ type: "state", locked: true, blanked: false });
          }
        } catch {
          // ignore malformed
        }
      };

      ws.onclose = (ev) => {
        // Dedicated "unauthorized" close code (see daemon WS_CLOSE_UNAUTHORIZED).
        // Browsers can drop the app-level rejection frame when the daemon closes
        // right after sending it, so the onmessage handler above may never fire;
        // the close code survives that race, so treat it as the gate trigger too.
        if (ev.code === UNAUTHORIZED_CLOSE_CODE) {
          unauthorizedRef.current = true;
          setStatus("unauthorized");
          return;
        }
        if (stopped || unauthorizedRef.current || cancelledRef.current) {
          if (!unauthorizedRef.current) setStatus("closed");
          return;
        }
        setStatus("closed");
        setLastError(describeClose(ev.code, ev.reason));
        setRetrying(true);
        const wait = Math.min(backoffRef.current, 8000);
        backoffRef.current = wait * 2;
        timer = window.setTimeout(connect, wait);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    // Gate the first WebSocket attempt on a /health check so the browser
    // doesn't log a connection error when the daemon is still starting up
    // (the `just dev` recipe starts daemon and Vite simultaneously).
    const healthUrl = resolve_health_url();
    setStatus("connecting");
    fetch(healthUrl)
      .then(() => connect())
      .catch(() => {
        if (!stopped && !cancelledRef.current) {
          setStatus("closed");
          setLastError("daemon not reachable");
          setRetrying(true);
          timer = window.setTimeout(() => connect(), 1000);
        }
      });
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      wsRef.current?.close();
    };
  }, [onDeck, onWidgetUpdate, onMediaState, onChromeMedia, onConfirmRequest, onRunningWindows, onSessionState, onMediaError, enabled, gen]);

  const send = (msg: ClientMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  };

  // Clear the reconnect latches and kick off a fresh connect. Shared by the
  // password actions and by the overlay's Retry so the flag/backoff/gen reset
  // lives in exactly one place.
  const restartConnection = useCallback(() => {
    cancelledRef.current = false;
    setCancelled(false);
    backoffRef.current = 500;
    setGen((g) => g + 1);
  }, []);

  // Store a new password and force an immediate reconnect that presents it.
  const authenticate = useCallback((password: string) => {
    passwordRef.current = password;
    storePassword(password);
    setHasPassword(!!password);
    unauthorizedRef.current = false;
    restartConnection();
  }, [restartConnection]);

  // Forget the stored password and reconnect with none — the daemon (auth on)
  // then rejects and the gate reappears. A no-op-looking reconnect if the
  // daemon runs --no-auth (nothing to log out of).
  const deauthenticate = useCallback(() => {
    passwordRef.current = "";
    storePassword("");
    setHasPassword(false);
    unauthorizedRef.current = false;
    restartConnection();
  }, [restartConnection]);

  // Pause the automatic reconnect loop (issue #64). The pending retry
  // timer bails on ``cancelledRef``, so the loop stops without needing to
  // reach into the effect's local timer handle.
  const cancelReconnect = useCallback(() => {
    cancelledRef.current = true;
    setCancelled(true);
    setRetrying(false);
    setStatus("closed");
    wsRef.current?.close();
  }, []);

  // Resume immediately from a cancelled or closed state (issue #64). The
  // generation bump tears down the old effect and starts a fresh connect
  // (including the /health gate) right away.
  const retryNow = useCallback(() => {
    attemptRef.current = 0;
    setAttempt(0);
    setLastError("");
    restartConnection();
  }, [restartConnection]);

  return {
    status,
    send,
    authenticate,
    deauthenticate,
    hasPassword,
    attempt,
    lastError,
    cancelled,
    retrying,
    cancelReconnect,
    retryNow,
  };
}

function resolve_health_url(): string {
  return new URL("/health", window.location.href).toString();
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
