import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Plus, Save, X } from "lucide-react";
import type { FocusedAppInfo, ServerLayout, Widget, Icon } from "./protocol";
import { EDITOR_VIEW_ID } from "./protocol";
import type { OverflowMode } from "./reflow";
import { EditorCanvas } from "./EditorCanvas";
import { PropertiesPanel } from "./PropertiesPanel";

type LayoutEntry = {
  id: string;
  match: string[];
  display_name?: string | null;
  theme?: string | null;
  icon?: Icon | null;
  jogstrip?: boolean;
  widgets: Widget[];
  overflow?: string | null;
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

function getAuthHeaders(): Record<string, string> {
  try {
    const pw = window.localStorage.getItem("deckd.password") ?? "";
    if (!pw) return {};
    return { "X-Deckd-Password": pw };
  } catch {
    return {};
  }
}

interface EditorProps {
  layout: ServerLayout | null;
  send: (msg: { type: "select_view"; view: string } | { type: "clear_view" }) => void;
  onExit: () => void;
  /** When provided, the editor skips the GET /layouts fetch and uses
   * these entries instead — used by the demo fixture. */
  mockLayouts?: LayoutEntry[];
}

type CreationFormKind = "detect" | "browser" | "manual";

interface CreationFormState {
  kind: CreationFormKind;
  match: string;
  displayName: string;
  /** The second prefilled option for the browser branch. */
  altMatch?: string;
  altDisplayName?: string;
  label: string;
}

const NEW_LAYOUT_SENTINEL = "__new__";

/** Derive a display name from a match token: title-prefix tokens get the
 * window title part; plain identity tokens are used as-is. */
function displayNameFromMatch(match: string): string {
  if (match.startsWith("title:")) {
    const pattern = match.slice("title:".length);
    return pattern.replace(/^\*|\*$/g, "").trim() || match;
  }
  return match;
}

/** Build a creation-form state for an automatic detect-and-offer prompt
 * based on the focused app info. Returns null when there is nothing to
 * prefill (no app identity available). */
function buildCreationForm(
  focusedApp: FocusedAppInfo | null | undefined,
): CreationFormState | null {
  if (!focusedApp) return null;
  const identity = focusedApp.wm_class || focusedApp.app_id;
  if (!identity) return null;

  if (focusedApp.is_browser) {
    const browserName = identity;
    const browserDisplay = displayNameFromMatch(browserName);
    const titleToken = focusedApp.title
      ? `title:*${focusedApp.title}*`
      : "title:*";
    const titleDisplay = focusedApp.title || "this site";

    return {
      kind: "browser",
      match: browserName,
      displayName: browserDisplay,
      label: `No layout for ${browserDisplay} yet — create one?`,
      altMatch: titleToken,
      altDisplayName: titleDisplay,
    };
  }

  return {
    kind: "detect",
    match: identity,
    displayName: identity,
    label: `No layout for ${identity} yet — create one?`,
  };
}

export function Editor({ layout: activeLayout, send, onExit, mockLayouts }: EditorProps) {
  const initialSelectedId = activeLayout?.app ?? (mockLayouts ? (mockLayouts.find((l) => l.id !== EDITOR_VIEW_ID)?.id ?? mockLayouts[0]?.id ?? null) : null);
  const [layouts, setLayouts] = useState<LayoutEntry[]>(mockLayouts ?? []);
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");

  // Editable widget state: derived from the active layout on mount / selection.
  const [editWidgets, setEditWidgets] = useState<Widget[]>([]);
  const [editOverflow, setEditOverflow] = useState<OverflowMode>("shrink-to-fit");
  const initialisedRef = useRef(false);
  const pickerSkipRef = useRef(false);

  // Editable layout-level presentation fields.
  const [editDisplayName, setEditDisplayName] = useState<string>("");
  const [editTheme, setEditTheme] = useState<string>("");
  const [editIcon, setEditIcon] = useState<Icon | null>(null);
  const [editJogstrip, setEditJogstrip] = useState<boolean>(true);

  // Widget selection: index into editWidgets, or null for layout-level.
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  // New-layout creation state (#104).
  const [draft, setDraft] = useState<{ match: string[]; displayName: string }>({ match: [], displayName: "" });

  // Detect-and-offer: when the editor opens and the resolved layout is
  // "default" (no real match), pre-seed the creation form from props.
  // Lazy initializer so it runs exactly once during the first render,
  // before the widget-initialization effect fires.
  const [creationForm, setCreationForm] = useState<CreationFormState | null>(() => {
    if (!activeLayout) return null;
    if (activeLayout.app !== "default") return null;
    return buildCreationForm(activeLayout.focused_app ?? null);
  });
  const [creationMatchInput, setCreationMatchInput] = useState(() => creationForm?.match ?? "");
  const [creationDisplayNameInput, setCreationDisplayNameInput] = useState(() => creationForm?.displayName ?? "");

  const isNewLayout = selectedId === NEW_LAYOUT_SENTINEL;

  // Initialise editable state from the active layout when it first arrives
  // and no creation prompt is showing.
  useEffect(() => {
    if (initialisedRef.current) return;
    if (creationForm) return;
    if (!activeLayout || !activeLayout.widgets) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEditWidgets(deepCloneWidgets(activeLayout.widgets));
    setEditOverflow((activeLayout.overflow as OverflowMode) ?? "shrink-to-fit");
    setEditDisplayName(activeLayout.display_name ?? "");
    setEditTheme(activeLayout.theme ?? "");
    setEditIcon(activeLayout.icon ?? null);
    setEditJogstrip(activeLayout.jogstrip_enabled);
    initialisedRef.current = true;
    pickerSkipRef.current = true;
  }, [activeLayout, creationForm]);

  // Re-init when the user switches layouts via the picker.
  // The first fire is skipped when activeLayout already supplied data
  // (first effect set pickerSkipRef = true). Subsequent fires when the
  // user picks a different layout are handled normally.
  useEffect(() => {
    if (creationForm) return;
    if (!selectedId || isNewLayout) return;
    if (pickerSkipRef.current) {
      pickerSkipRef.current = false;
      return;
    }
    const picked = layouts.find((l) => l.id === selectedId);
    if (!picked) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEditWidgets(deepCloneWidgets(picked.widgets));
    setEditOverflow((picked.overflow as OverflowMode) ?? "shrink-to-fit");
    setEditDisplayName(picked.display_name ?? "");
    setEditTheme((picked as { theme?: string | null }).theme ?? "");
    setEditIcon((picked as { icon?: Icon | null }).icon ?? null);
    setEditJogstrip((picked as { jogstrip?: boolean }).jogstrip ?? true);
    setSelectedIndex(null);
    setSaveStatus("idle");
  }, [selectedId, layouts, isNewLayout, creationForm]);

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
    setCreationForm(null);
  }, []);

  const handleSave = useCallback(async () => {
    if (isNewLayout) {
      if (!draft.match.length) return;
      setSaveStatus("saving");
      try {
        const base = resolveBaseUrl();
        const res = await fetch(`${base}/layouts`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...getAuthHeaders() },
          body: JSON.stringify({
            match: draft.match,
            display_name: draft.displayName || undefined,
            widgets: editWidgets,
            overflow: editOverflow,
          }),
        });
        if (res.ok) {
          const data = (await res.json()) as { ok: boolean; layout?: { id: string; match: string[]; display_name?: string | null; widgets: Widget[]; overflow?: string | null } };
          if (data.ok && data.layout) {
            setSaveStatus("saved");
            setLayouts((prev) => {
              const entry: LayoutEntry = {
                id: data.layout!.id,
                match: data.layout!.match,
                display_name: data.layout!.display_name,
                widgets: data.layout!.widgets,
                overflow: data.layout!.overflow,
              };
              return [...prev, entry];
            });
            setSelectedId(data.layout.id);
            setDraft({ match: [], displayName: "" });
            setTimeout(() => setSaveStatus("idle"), 2000);
          } else {
            setSaveStatus("error");
          }
        } else {
          const body = await res.json().catch(() => ({})) as { error?: string };
          console.error("create layout failed:", res.status, body.error || "");
          setSaveStatus("error");
        }
      } catch {
        setSaveStatus("error");
      }
      return;
    }

    if (!selectedId) return;
    setSaveStatus("saving");
    try {
      const base = resolveBaseUrl();
      const body: Record<string, unknown> = {
        id: selectedId,
        widgets: editWidgets,
        overflow: editOverflow,
      };
      if (editDisplayName) body.display_name = editDisplayName;
      else body.display_name = null;
      if (editTheme) body.theme = editTheme;
      else body.theme = null;
      if (editIcon) body.icon = editIcon;
      else body.icon = null;
      body.jogstrip = editJogstrip;
      const res = await fetch(
        `${base}/layouts/${encodeURIComponent(selectedId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json", ...getAuthHeaders() },
          body: JSON.stringify(body),
        },
      );
      if (res.ok) {
        setSaveStatus("saved");
        setTimeout(() => setSaveStatus("idle"), 2000);
      } else {
        setSaveStatus("error");
      }
    } catch {
      setSaveStatus("error");
    }
  }, [isNewLayout, selectedId, draft, editWidgets, editOverflow, editDisplayName, editTheme, editIcon, editJogstrip]);

  const handleExit = useCallback(() => {
    if (isNewLayout) {
      if (!window.confirm("Abandon this new layout? Nothing is saved yet.")) {
        return;
      }
      setSelectedId(null);
      setDraft({ match: [], displayName: "" });
      setCreationForm(null);
      setEditWidgets([]);
    }
    send({ type: "clear_view" });
    onExit();
  }, [send, onExit, isNewLayout]);

  // Open the manual "new layout" creation form from the picker.
  const handleNewLayoutClick = useCallback(() => {
    setPickerOpen(false);
    setCreationForm({
      kind: "manual",
      match: "",
      displayName: "",
      label: "New layout",
    });
    setCreationMatchInput("");
    setCreationDisplayNameInput("");
  }, []);

  // Confirm creation: enter new-layout editing mode with the entered tokens.
  const handleCreateConfirm = useCallback(() => {
    const match = creationMatchInput.trim();
    if (!match) return;
    setDraft({ match: [match], displayName: creationDisplayNameInput.trim() || match });
    setSelectedId(NEW_LAYOUT_SENTINEL);
    setEditWidgets([]);
    setEditOverflow("shrink-to-fit");
    setCreationForm(null);
    setSaveStatus("idle");
    initialisedRef.current = true;
  }, [creationMatchInput, creationDisplayNameInput]);

  const handleCreationCancel = useCallback(() => {
    setCreationForm(null);
  }, []);

  const handleReorder = useCallback((from: number, to: number) => {
    setEditWidgets((prev) => {
      const next = [...prev];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
    setSaveStatus("idle");
  }, []);

  const handleOverflowChange = useCallback((mode: OverflowMode) => {
    setEditOverflow(mode);
    setSaveStatus("idle");
  }, []);

  const handleLayoutFieldChange = useCallback((field: string, value: unknown) => {
    setSaveStatus("idle");
    switch (field) {
      case "display_name":
        setEditDisplayName(String(value ?? ""));
        break;
      case "theme":
        setEditTheme(String(value ?? ""));
        break;
      case "icon":
        setEditIcon(value as Icon | null);
        break;
      case "jogstrip":
        setEditJogstrip(Boolean(value));
        break;
    }
  }, []);

  const handleSelectWidget = useCallback((index: number | null) => {
    setSelectedIndex(index);
  }, []);

  const handleWidgetChange = useCallback((index: number, widget: Widget) => {
    setEditWidgets((prev) => {
      const next = [...prev];
      next[index] = widget;
      return next;
    });
    setSaveStatus("idle");
  }, []);

  const handleDeleteWidget = useCallback((index: number) => {
    setEditWidgets((prev) => prev.filter((_, i) => i !== index));
    setSelectedIndex(null);
    setSaveStatus("idle");
  }, []);

  const widgetCount = editWidgets.length;

  // The label shown in the picker trigger.
  const pickerLabel = useMemo(() => {
    if (isNewLayout) {
      return draft.displayName || draft.match[0] || "New layout";
    }
    if (selectedLayout) {
      return selectedLayout.display_name?.trim() || selectedLayout.id;
    }
    return "Select layout";
  }, [isNewLayout, selectedLayout, draft]);

  // The metadata row data for the canvas header.
  const canvasMeta = useMemo(() => {
    if (isNewLayout) {
      return {
        app: draft.displayName || draft.match[0] || "New layout",
        match: `match: ${draft.match.join(", ") || "(none)"}`,
      };
    }
    if (selectedLayout) {
      return {
        app: selectedLayout.display_name?.trim() || selectedLayout.id,
        match: `match: ${selectedLayout.match.join(", ")}`,
      };
    }
    return null;
  }, [isNewLayout, selectedLayout, draft]);

  const canSave = isNewLayout ? draft.match.length > 0 : !!selectedId;

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
          <h2 className="editor-title">
            {isNewLayout ? "New layout" : "Edit layout"}
          </h2>
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
              <span className="editor-picker-label">{pickerLabel}</span>
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
                <li className="editor-picker-separator" role="separator" />
                <li
                  role="option"
                  className="editor-picker-option editor-picker-option-new"
                  onClick={handleNewLayoutClick}
                >
                  <Plus size={14} />
                  <span>New layout</span>
                </li>
              </ul>
            )}
          </div>
          <button
            className="editor-save-btn"
            aria-label="save layout"
            disabled={saveStatus === "saving" || !canSave}
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
          {creationForm ? (
            <CreationFormView
              form={creationForm}
              matchInput={creationMatchInput}
              displayNameInput={creationDisplayNameInput}
              onMatchChange={setCreationMatchInput}
              onDisplayNameChange={setCreationDisplayNameInput}
              onConfirm={handleCreateConfirm}
              onCancel={handleCreationCancel}
            />
          ) : selectedLayout || isNewLayout ? (
            <>
              {canvasMeta && (
                <div className="editor-canvas-meta">
                  <span className="editor-canvas-app">{canvasMeta.app}</span>
                  <span className="editor-canvas-match">{canvasMeta.match}</span>
                  <span className="editor-canvas-widget-count">
                    {widgetCount} widget{widgetCount !== 1 ? "s" : ""}
                  </span>
                </div>
              )}
              <EditorCanvas
                widgets={editWidgets}
                overflow={editOverflow}
                selectedIndex={selectedIndex}
                onReorder={handleReorder}
                onWidgetChange={handleWidgetChange}
                onOverflowChange={handleOverflowChange}
                onSelectWidget={handleSelectWidget}
              />
            </>
          ) : (
            <p className="editor-pane-placeholder">No layout selected</p>
          )}
        </section>
        <aside className="editor-pane editor-properties" role="complementary" aria-label="properties panel">
          <PropertiesPanel
            widget={selectedIndex != null ? editWidgets[selectedIndex] ?? null : null}
            layoutFields={{
              display_name: editDisplayName || null,
              theme: editTheme || null,
              icon: editIcon,
              jogstrip: editJogstrip,
              overflow: editOverflow,
            }}
            onWidgetChange={(w) => {
              if (selectedIndex != null) handleWidgetChange(selectedIndex, w);
            }}
            onLayoutFieldChange={handleLayoutFieldChange}
            onDeleteWidget={
              selectedIndex != null
                ? () => handleDeleteWidget(selectedIndex)
                : undefined
            }
          />
        </aside>
      </div>
    </div>
  );
}

/** The inline creation form shown in the canvas area for detect-and-offer
 * and manual new-layout entry. */
function CreationFormView({
  form,
  matchInput,
  displayNameInput,
  onMatchChange,
  onDisplayNameChange,
  onConfirm,
  onCancel,
}: {
  form: CreationFormState;
  matchInput: string;
  displayNameInput: string;
  onMatchChange: (v: string) => void;
  onDisplayNameChange: (v: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const canConfirm = matchInput.trim().length > 0;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && canConfirm) {
      e.preventDefault();
      onConfirm();
    }
    if (e.key === "Escape") {
      onCancel();
    }
  };

  return (
    <div className="editor-creation-form" onKeyDown={handleKeyDown}>
      <p className="editor-creation-prompt">{form.label}</p>
      <label className="editor-creation-field">
        <span className="editor-creation-field-label">Match token</span>
        <input
          className="editor-creation-input"
          type="text"
          value={matchInput}
          onChange={(e) => onMatchChange(e.target.value)}
          placeholder="e.g. firefox or title:*YouTube*"
          autoFocus
        />
      </label>
      <label className="editor-creation-field">
        <span className="editor-creation-field-label">Display name</span>
        <input
          className="editor-creation-input"
          type="text"
          value={displayNameInput}
          onChange={(e) => onDisplayNameChange(e.target.value)}
          placeholder="(optional, derived from match)"
        />
      </label>
      {form.kind === "browser" && form.altMatch && (
        <div className="editor-creation-alt">
          <span className="editor-creation-alt-label">or</span>
          <button
            type="button"
            className="editor-creation-alt-btn"
            onClick={() => {
              onMatchChange(form.altMatch!);
              onDisplayNameChange(form.altDisplayName!);
            }}
          >
            Layout for {form.altDisplayName}
            <code className="editor-creation-alt-code">{form.altMatch}</code>
          </button>
        </div>
      )}
      <div className="editor-creation-actions">
        <button
          className="editor-creation-btn editor-creation-btn-primary"
          onClick={onConfirm}
          disabled={!canConfirm}
        >
          Create layout
        </button>
        <button
          className="editor-creation-btn editor-creation-btn-cancel"
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Shallow-deep clone of the widget array so edits are independent of the
 * props. We need a fresh mutable copy — `structuredClone` is fine here. */
function deepCloneWidgets(widgets: Widget[]): Widget[] {
  try {
    return structuredClone(widgets);
  } catch {
    return widgets.map((w) => ({ ...w }));
  }
}
