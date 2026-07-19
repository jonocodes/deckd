import { useCallback, useState } from "react";
import { useDeckdSocket } from "./socket";
import { ButtonGrid } from "./ButtonGrid";
import { JogStrip } from "./JogStrip";
import { Trackpad } from "./Trackpad";
import { Settings } from "./Settings";
import {
  useScrollSettings,
  useTrackpadSettings,
  useWakeLockSetting,
} from "./settings-store";
import { useWakeLock } from "./wake-lock";
import { getDemoLayout } from "./demo";
import type { JogHandle } from "./JogStrip";
import type { ServerLayout } from "./protocol";

type View = "layout" | "trackpad" | "settings";
type SocketStatus = "connecting" | "open" | "closed";

/** Sentinel ids for the always-on chrome widgets. The daemon's pad / jog
 * paths ignore ids for emission (they're just book-keeping keys), so these
 * never collide with real layout widgets. */
const CHROME_JOG_ID = "__chrome__";
const TRACKPAD_ID = "__trackpad__";

const CHROME_JOG_HANDLE: JogHandle = { id: CHROME_JOG_ID };

const STATUS_LABEL: Record<SocketStatus, string> = {
  open: "live",
  connecting: "reconnecting",
  closed: "disconnected",
};

export function App() {
  // Demo mode (``?demo=<name>``): render a fixture layout with the socket
  // disabled, so the client can be viewed without a daemon. Null in normal
  // daemon-backed operation.
  const demoLayout = getDemoLayout();
  const [layout, setLayout] = useState<ServerLayout | null>(demoLayout);
  const [view, setView] = useState<View>("layout");
  const onLayout = useCallback((m: ServerLayout) => setLayout(m), []);
  const { status, send } = useDeckdSocket(onLayout, { enabled: !demoLayout });
  const scroll = useScrollSettings();
  const trackpad = useTrackpadSettings();
  const wakeLock = useWakeLockSetting();
  // Hold the wake lock while the user wants it AND the socket is live;
  // a stale surface with no daemon behind it has no reason to keep the
  // screen on. Visibility is handled inside the hook.
  useWakeLock(wakeLock.enabled && status === "open");

  const press = (id: string) => send({ type: "press", id });
  const jog = (id: string, delta: number) => send({ type: "jog", id, delta });
  const jogEnd = (id: string, velocity: number) => send({ type: "jog_end", id, velocity });
  const pad = (dx: number, dy: number) => send({ type: "pad", id: TRACKPAD_ID, dx, dy });
  const padTap = (fingers: number) => send({ type: "pad_tap", id: TRACKPAD_ID, fingers });
  const padDrag = (state: "start" | "end") =>
    send({ type: "pad_drag", id: TRACKPAD_ID, state });

  const jogstripEnabled = layout?.jogstrip_enabled ?? true;
  const statusLabel = STATUS_LABEL[status];

  return (
    <div className="app">
      <div className="chrome-page">
        <main className="surface">
          {view === "trackpad" ? (
            <Trackpad
              onPad={pad}
              onTap={padTap}
              onDrag={padDrag}
              sensitivity={trackpad.sensitivity}
            />
          ) : view === "settings" ? (
            <Settings
              layout={layout}
              status={status}
              scrollScale={scroll.scale}
              scrollInvert={scroll.invert}
              onScrollScaleChange={scroll.setScale}
              onScrollInvertChange={scroll.setInvert}
              trackpadSensitivity={trackpad.sensitivity}
              onTrackpadSensitivityChange={trackpad.setSensitivity}
              wakeLockEnabled={wakeLock.enabled}
              onWakeLockChange={wakeLock.setEnabled}
            />
          ) : layout?.error ? (
            <div className="layout-error" role="alert">
              <span className="layout-error-title">Layout error</span>
              <pre className="layout-error-body">{layout.error}</pre>
            </div>
          ) : layout ? (
            <ButtonGrid
              widgets={layout.widgets}
              onPress={press}
              onJog={jog}
              onJogEnd={jogEnd}
              scrollScale={scroll.scale}
              scrollInvert={scroll.invert}
            />
          ) : (
            <div className="empty">waiting for daemon…</div>
          )}
        </main>
        {jogstripEnabled && (
          <aside className="chrome-jogstrip">
            <JogStrip
              widget={CHROME_JOG_HANDLE}
              variant="chrome"
              scale={scroll.scale}
              invert={scroll.invert}
              onJog={jog}
              onJogEnd={jogEnd}
            />
          </aside>
        )}
      </div>
      <footer className="chrome-bottom">
        <span className="app-name">{layout ? layout.app : "deckd"}</span>
        <span className={`connection connection-${status}`}>
          <span className="connection-dot" />
          <span className="connection-label">{statusLabel}</span>
        </span>
        <button
          className={`chrome-btn${view === "trackpad" ? " chrome-btn-active" : ""}`}
          onPointerDown={(e) => {
            e.preventDefault();
            setView(view === "trackpad" ? "layout" : "trackpad");
          }}
        >
          trackpad
        </button>
        <button
          className={`chrome-btn${view === "settings" ? " chrome-btn-active" : ""}`}
          onPointerDown={(e) => {
            e.preventDefault();
            setView(view === "settings" ? "layout" : "settings");
          }}
        >
          settings
        </button>
      </footer>
    </div>
  );
}
