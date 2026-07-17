import { useCallback, useState } from "react";
import { useDeckdSocket } from "./socket";
import { ButtonGrid } from "./ButtonGrid";
import { JogStrip } from "./JogStrip";
import type { JogHandle } from "./JogStrip";
import type { ServerLayout } from "./protocol";

type View = "layout" | "trackpad";
type SocketStatus = "connecting" | "open" | "closed";

/** Sentinel id for the persistent chrome jogstrip. The daemon's ``jog``
 * path ignores the id for emission (only used as a momentum-task key), so
 * this never collides with real layout widgets. */
const CHROME_JOG_ID = "__chrome__";

const CHROME_JOG_HANDLE: JogHandle = { id: CHROME_JOG_ID };

const STATUS_LABEL: Record<SocketStatus, string> = {
  open: "live",
  connecting: "reconnecting",
  closed: "disconnected",
};

export function App() {
  const [layout, setLayout] = useState<ServerLayout | null>(null);
  const [view, setView] = useState<View>("layout");
  const onLayout = useCallback((m: ServerLayout) => setLayout(m), []);
  const { status, send } = useDeckdSocket(onLayout);

  const press = (id: string) => send({ type: "press", id });
  const jog = (id: string, delta: number) => send({ type: "jog", id, delta });
  const jogEnd = (id: string, velocity: number) => send({ type: "jog_end", id, velocity });

  const jogstripEnabled = layout?.jogstrip_enabled ?? true;
  const statusLabel = STATUS_LABEL[status];

  return (
    <div className="app">
      <div className="chrome-page">
        <main className="surface">
          {view === "trackpad" ? (
            <div className="trackpad-placeholder">
              <span className="trackpad-hint">trackpad</span>
            </div>
          ) : layout ? (
            <ButtonGrid widgets={layout.widgets} onPress={press} onJog={jog} onJogEnd={jogEnd} />
          ) : (
            <div className="empty">waiting for daemon…</div>
          )}
        </main>
        {jogstripEnabled && (
          <aside className="chrome-jogstrip">
            <JogStrip
              widget={CHROME_JOG_HANDLE}
              variant="chrome"
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
        <button className="chrome-btn" disabled>
          settings
        </button>
      </footer>
    </div>
  );
}
