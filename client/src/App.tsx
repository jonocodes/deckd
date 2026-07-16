import { useCallback, useState } from "react";
import { useDeckdSocket } from "./socket";
import { ButtonGrid } from "./ButtonGrid";

type LayoutState = { app: string; page: string; widgets: ReturnType<typeof JSON.parse>["widgets"] };

export function App() {
  const [layout, setLayout] = useState<LayoutState | null>(null);
  const onLayout = useCallback((m: { app: string; page: string; widgets: any[] }) => {
    setLayout({ app: m.app, page: m.page, widgets: m.widgets });
  }, []);
  const { status, send } = useDeckdSocket(onLayout);

  const press = (id: string) => send({ type: "press", id });
  const jog = (id: string, delta: number) => send({ type: "jog", id, delta });
  const jogEnd = (id: string, velocity: number) => send({ type: "jog_end", id, velocity });

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">deckd</span>
        <span className="meta">
          {layout ? `${layout.app} / ${layout.page}` : "…"} ·{" "}
          <span className={`status status-${status}`}>{status}</span>
        </span>
      </header>
      <main className="surface">
        {layout ? (
          <ButtonGrid widgets={layout.widgets} onPress={press} onJog={jog} onJogEnd={jogEnd} />
        ) : (
          <div className="empty">waiting for daemon…</div>
        )}
      </main>
    </div>
  );
}
