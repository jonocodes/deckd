/* Playground spike (#149): a drop-in sibling of ``useDeckdSocket``.
 *
 * Same signature, same return shape — but instead of a WebSocket it drives
 * an in-browser ``MockDaemon``. ``App`` picks between the two hooks on a
 * ``?playground`` flag; both are always called (rules of hooks), and only
 * the enabled one does any work.
 */
import { useCallback, useEffect, useRef } from "react";
import type {
  ClientMessage,
  MediaState,
  ServerChromeMedia,
  ServerConfirmRequest,
  ServerDeck,
  ServerRunningWindows,
  ServerWidgetUpdate,
} from "../protocol";
import { MockDaemon } from "./mock-daemon";

const noop = () => {};

export function usePlaygroundDaemon(
  onDeck: (m: ServerDeck) => void,
  onWidgetUpdate: (m: ServerWidgetUpdate) => void,
  onMediaState: (m: MediaState) => void,
  onChromeMedia?: (m: ServerChromeMedia) => void,
  _onConfirmRequest?: (m: ServerConfirmRequest) => void,
  onRunningWindows?: (m: ServerRunningWindows) => void,
  options: { enabled?: boolean } = {},
) {
  const { enabled = true } = options;
  const daemonRef = useRef<MockDaemon | null>(null);

  // Hold the latest callbacks in refs so the daemon effect keys only on
  // ``enabled`` — a fresh callback identity must not tear down and restart
  // the clock (that would reset playback on every render).
  const onDeckRef = useRef(onDeck);
  const onWidgetUpdateRef = useRef(onWidgetUpdate);
  const onMediaStateRef = useRef(onMediaState);
  const onChromeMediaRef = useRef(onChromeMedia);
  const onRunningWindowsRef = useRef(onRunningWindows);
  onDeckRef.current = onDeck;
  onWidgetUpdateRef.current = onWidgetUpdate;
  onMediaStateRef.current = onMediaState;
  onChromeMediaRef.current = onChromeMedia;
  onRunningWindowsRef.current = onRunningWindows;

  useEffect(() => {
    if (!enabled) return;
    const daemon = new MockDaemon({
      onDeck: (m) => onDeckRef.current(m),
      onMediaState: (m) => onMediaStateRef.current(m),
      onWidgetUpdate: (m) => onWidgetUpdateRef.current(m),
      onChromeMedia: (m) => onChromeMediaRef.current?.(m),
      onRunningWindows: (m) => onRunningWindowsRef.current?.(m),
    });
    daemonRef.current = daemon;
    daemon.start();
    return () => {
      daemon.stop();
      daemonRef.current = null;
    };
  }, [enabled]);

  const send = useCallback((msg: ClientMessage) => {
    daemonRef.current?.send(msg);
  }, []);

  // Report "open" so the chrome connection indicator reads "live", matching
  // how demo mode presents a fixture as a live surface. The reconnect
  // telemetry (issue #64) is inert — the MockDaemon can't disconnect.
  return {
    status: "open" as const,
    send,
    authenticate: noop,
    deauthenticate: noop,
    hasPassword: false,
    attempt: 0,
    lastError: "",
    cancelled: false,
    retrying: false,
    cancelReconnect: noop,
    retryNow: noop,
  };
}
