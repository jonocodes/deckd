import { useCallback, useEffect, useState } from "react";
import { Check, ChevronDown, Save, X } from "lucide-react";
import type { ServerLayout, Widget } from "./protocol";
import { EDITOR_VIEW_ID } from "./protocol";

type LayoutEntry = {
  id: string;
  match: string[];
  display_name?: string | null;
  widgets: Widget[];
};

type LayoutListResponse = {
  ok: boolean;
  layouts: LayoutEntry[];
};

function resolveBaseUrl(): string {
  const env = ((import.meta.env.VITE_DECKD_WS ?? "") as string).trim();
  if (env) {
    try {
      const url = new URL(env);
      url.protocol = url.protocol === "wss:" ? "https:" : "http:";
      url.pathname = "";
      return url.toString().replace(/\/$/, "");
    } catch {
      // fall through
    }
  }
  return window.location.origin;
}

interface EditorProps {
  layout: ServerLayout | null;
  send: (msg: { type: "select_view"; view: string } | { type: "clear_view" }) => void;
  onExit: () => void;
  /** When provided, the editor skips the GET /layouts fetch and uses
   * these entries instead — used by the demo fixture. */
  mockLayouts?: LayoutEntry[];
}

export function Editor({ layout: activeLayout, send, onExit, mockLayouts }: EditorProps) {
  const initialSelectedId = activeLayout?.app ?? (mockLayouts ? (mockLayouts.find((l) => l.id !== EDITOR_VIEW_ID)?.id ?? mockLayouts[0]?.id ?? null) : null);
  const [layouts, setLayouts] = useState<LayoutEntry[]>(mockLayouts ?? []);
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  useEffect(() => {
    if (mockLayouts) return;
    const base = resolveBaseUrl();
    let cancelled = false;
    fetch(`${base}/layouts`)
      .then((r) => r.json())
      .then((data: LayoutListResponse) => {
        if (!cancelled && data.ok && Array.isArray(data.layouts)) {
          setLayouts(data.layouts);
          if (!selectedId && data.layouts.length > 0) {
            const firstReal = data.layouts.find((l) => l.id !== EDITOR_VIEW_ID) ?? data.layouts[0];
            setSelectedId(firstReal.id);
          }
        }
      })
      .catch((err) => {
        if (!cancelled) console.error("failed to fetch layouts", err);
      });
    return () => { cancelled = true; };
    // selectedId is intentionally excluded from deps: we only want the
    // initial auto-select on first fetch, not on every user pick change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mockLayouts]);

  const selectedLayout = layouts.find((l) => l.id === selectedId) ?? null;

  const handlePick = useCallback((id: string) => {
    setSelectedId(id);
    setPickerOpen(false);
    setSaveStatus("idle");
  }, []);

  const handleSave = useCallback(async () => {
    if (!selectedId) return;
    setSaveStatus("saving");
    try {
      const base = resolveBaseUrl();
      const res = await fetch(`${base}/layouts/${encodeURIComponent(selectedId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: selectedId }),
      });
      if (res.ok) {
        setSaveStatus("saved");
        setTimeout(() => setSaveStatus("idle"), 2000);
      } else {
        setSaveStatus("error");
      }
    } catch {
      setSaveStatus("error");
    }
  }, [selectedId]);

  const handleExit = useCallback(() => {
    send({ type: "clear_view" });
    onExit();
  }, [send, onExit]);

  return (
    <div className="editor" role="region" aria-label="layout editor">
      <header className="editor-header">
        <div className="editor-header-left">
          <button
            className="editor-exit-btn"
            aria-label="close editor"
            onClick={handleExit}
          >
            <X size={18} />
          </button>
          <h2 className="editor-title">Edit layout</h2>
        </div>
        <div className="editor-header-right">
          <div className="editor-picker">
            <button
              className="editor-picker-trigger"
              aria-label="select layout to edit"
              aria-haspopup="listbox"
              aria-expanded={pickerOpen}
              onClick={() => setPickerOpen((v) => !v)}
            >
              <span className="editor-picker-label">
                {selectedLayout
                  ? selectedLayout.display_name?.trim() || selectedLayout.id
                  : "Select layout"}
              </span>
              <ChevronDown size={14} />
            </button>
            {pickerOpen && (
              <ul className="editor-picker-list" role="listbox">
                {layouts.map((l) => (
                  <li
                    key={l.id}
                    role="option"
                    aria-selected={l.id === selectedId}
                    className={`editor-picker-option${l.id === selectedId ? " editor-picker-option-active" : ""}${l.id === EDITOR_VIEW_ID ? " editor-picker-option-view" : ""}`}
                    onClick={() => handlePick(l.id)}
                  >
                    <span>{l.display_name?.trim() || l.id}</span>
                    {l.id === EDITOR_VIEW_ID ? (
                      <span className="editor-picker-tag">chrome view</span>
                    ) : null}
                    {l.id === selectedId ? <Check size={14} /> : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button
            className="editor-save-btn"
            aria-label="save layout"
            disabled={saveStatus === "saving" || !selectedId}
            onClick={handleSave}
          >
            <Save size={16} />
            <span>
              {saveStatus === "saving"
                ? "Saving…"
                : saveStatus === "saved"
                  ? "Saved"
                  : saveStatus === "error"
                    ? "Error"
                    : "Save"}
            </span>
          </button>
        </div>
      </header>
      <div className="editor-panes">
        <aside className="editor-pane editor-palette" role="complementary" aria-label="widget palette">
          <h3 className="editor-pane-title">Palette</h3>
          <p className="editor-pane-placeholder">Widget palette — coming soon</p>
        </aside>
        <section className="editor-pane editor-canvas" aria-label="live grid canvas">
          {selectedLayout ? (
            <div className="editor-canvas-content">
              <div className="editor-canvas-header">
                <span className="editor-canvas-app">
                  {selectedLayout.display_name?.trim() || selectedLayout.id}
                </span>
                <span className="editor-canvas-match">
                  match: {selectedLayout.match.join(", ")}
                </span>
              </div>
              <div className="editor-canvas-widget-count">
                {selectedLayout.widgets.length} widget{selectedLayout.widgets.length !== 1 ? "s" : ""}
              </div>
              <div className="editor-canvas-grid">
                <p className="editor-pane-placeholder">Live canvas — coming soon</p>
              </div>
            </div>
          ) : (
            <p className="editor-pane-placeholder">No layout selected</p>
          )}
        </section>
        <aside className="editor-pane editor-properties" role="complementary" aria-label="properties panel">
          <h3 className="editor-pane-title">Properties</h3>
          <p className="editor-pane-placeholder">Properties panel — coming soon</p>
        </aside>
      </div>
    </div>
  );
}
