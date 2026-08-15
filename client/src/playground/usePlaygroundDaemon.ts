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
  ServerLayout,
  ServerRunningWindows,
  ServerWidgetUpdate,
} from "../protocol";
import { MockDaemon } from "./mock-daemon";

const noop = () => {};

export function usePlaygroundDaemon(
  onLayout: (m: ServerLayout) => void,
  _onWidgetUpdate: (m: ServerWidgetUpdate) => void,
  onMediaState: (m: MediaState) => void,
  onChromeMedia?: (m: ServerChromeMedia) => void,
  _onConfirmRequest?: (m: ServerConfirmRequest) => void,
  _onRunningWindows?: (m: ServerRunningWindows) => void,
  options: { enabled?: boolean } = {},
) {
  const { enabled = true } = options;
  const daemonRef = useRef<MockDaemon | null>(null);

  // Hold the latest callbacks in refs so the daemon effect keys only on
  // ``enabled`` — a fresh callback identity must not tear down and restart
  // the clock (that would reset playback on every render).
  const onLayoutRef = useRef(onLayout);
  const onMediaStateRef = useRef(onMediaState);
  const onChromeMediaRef = useRef(onChromeMedia);
  onLayoutRef.current = onLayout;
  onMediaStateRef.current = onMediaState;
  onChromeMediaRef.current = onChromeMedia;

  useEffect(() => {
    if (!enabled) return;
    const daemon = new MockDaemon({
      onLayout: (m) => onLayoutRef.current(m),
      onMediaState: (m) => onMediaStateRef.current(m),
      onChromeMedia: (m) => onChromeMediaRef.current?.(m),
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
  // how demo mode presents a fixture as a live surface.
  return {
    status: "open" as const,
    send,
    authenticate: noop,
    deauthenticate: noop,
    hasPassword: false,
  };
}
