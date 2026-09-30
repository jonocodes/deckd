import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Plus, Save, X } from "lucide-react";
import type { FocusedAppInfo, ServerDeck, Widget, Icon } from "./protocol";
import { EDITOR_VIEW_ID } from "./protocol";
import type { OverflowMode } from "./reflow";
import { EditorCanvas } from "./EditorCanvas";
import { EditorPalette } from "./EditorPalette";
import type { PaletteKind } from "./EditorPalette";
import { PropertiesPanel } from "./PropertiesPanel";

/** Mint a collision-free id for a new widget: ``<kind>-<n>`` with the
 * lowest free ``n`` (#87: "``button-<n>`` minted by the palette"). The id
 * is editable afterwards; the daemon's #85 uniqueness validator backstops
 * hand-edited duplicates at save time. */
function mintWidgetId(kind: PaletteKind, existing: Widget[]): string {
  const ids = new Set(existing.map((w) => w.id));
  let n = 1;
  while (ids.has(`${kind}-${n}`)) n += 1;
  return `${kind}-${n}`;
}

type DeckEntry = {
  id: string;
  match: string[];
  display_name?: string | null;
  theme?: string | null;
  icon?: Icon | null;
  jogstrip?: boolean;
  widgets: Widget[];
  overflow?: string | null;
};

type DeckListResponse = {
  ok: boolean;
  decks: DeckEntry[];
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
  deck: ServerDeck | null;
  send: (msg: { type: "select_view"; view: string } | { type: "clear_view" }) => void;
  onExit: () => void;
  /** When provided, the editor skips the GET /decks fetch and uses
   * these entries instead — used by the demo fixture. */
  mockDecks?: DeckEntry[];
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

const NEW_DECK_SENTINEL = "__new__";

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
      label: `No deck for ${browserDisplay} yet — create one?`,
      altMatch: titleToken,
      altDisplayName: titleDisplay,
    };
  }

  return {
    kind: "detect",
    match: identity,
    displayName: identity,
    label: `No deck for ${identity} yet — create one?`,
  };
}

export function Editor({ deck: activeDeck, send, onExit, mockDecks }: EditorProps) {
  const initialSelectedId =
    (activeDeck && activeDeck.app !== EDITOR_VIEW_ID)
      ? activeDeck.app
      : (mockDecks ? (mockDecks.find((entry) => entry.id !== EDITOR_VIEW_ID)?.id ?? mockDecks[0]?.id ?? null) : null);
  const [decks, setDecks] = useState<DeckEntry[]>(mockDecks ?? []);
  // ``initialSelectedId``'s ternary resolves to ``string | null | undefined``
  // (the ``mockDecks?.find(...)?.id`` branch is ``undefined`` when no
  // match exists); normalise to ``string | null`` so useState's setter
  // typechecks against the React setter contract.
  const [selectedId, setSelectedId] = useState<string | null>(initialSelectedId ?? null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<string>("");

  // Editable widget state: derived from the active deck on mount / selection.
  const [editWidgets, setEditWidgets] = useState<Widget[]>([]);
  const [editOverflow, setEditOverflow] = useState<OverflowMode>("shrink-to-fit");
  const initialisedRef = useRef(false);
  const pickerSkipRef = useRef(false);
  const dirtyRef = useRef(false);

  // Editable deck-level presentation fields.
  const [editDisplayName, setEditDisplayName] = useState<string>("");
  const [editTheme, setEditTheme] = useState<string>("");
  const [editIcon, setEditIcon] = useState<Icon | null>(null);
  const [editJogstrip, setEditJogstrip] = useState<boolean>(true);
  const [editMatch, setEditMatch] = useState<string[]>([]);

  // Widget selection: index into editWidgets, or null for deck-level.
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  // New-deck creation state (#104).
  const [draft, setDraft] = useState<{ match: string[]; displayName: string }>({ match: [], displayName: "" });

  // Detect-and-offer: when the editor opens and the resolved deck is
  // "default" (no real match), pre-seed the creation form from props.
  // Lazy initializer so it runs exactly once during the first render,
  // before the widget-initialization effect fires.
  const [creationForm, setCreationForm] = useState<CreationFormState | null>(() => {
    if (!activeDeck) return null;
    if (activeDeck.app !== "default") return null;
    return buildCreationForm(activeDeck.focused_app ?? null);
  });
  const [creationMatchInput, setCreationMatchInput] = useState(() => creationForm?.match ?? "");
  const [creationDisplayNameInput, setCreationDisplayNameInput] = useState(() => creationForm?.displayName ?? "");

  const isNewDeck = selectedId === NEW_DECK_SENTINEL;

  // Initialise editable state from the active deck when it first arrives
  // and no creation prompt is showing.
  useEffect(() => {
    if (initialisedRef.current) return;
    if (creationForm) return;
    if (!activeDeck || !activeDeck.widgets) return;
    if (activeDeck.app === EDITOR_VIEW_ID) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEditWidgets(deepCloneWidgets(activeDeck.widgets));
    setEditOverflow((activeDeck.overflow as OverflowMode) ?? "shrink-to-fit");
    setEditDisplayName(activeDeck.display_name ?? "");
    setEditTheme(activeDeck.theme ?? "");
    setEditIcon(activeDeck.icon ?? null);
    setEditJogstrip(activeDeck.jogstrip_enabled ?? true);
    setEditMatch([activeDeck.app ?? "default"]);
    initialisedRef.current = true;
    pickerSkipRef.current = true;
  }, [activeDeck, creationForm]);

  // Re-init when the user switches decks via the picker.
  // The first fire is skipped when activeDeck already supplied data
  // (first effect set pickerSkipRef = true). Subsequent fires when the
  // user picks a different deck are handled normally.
  useEffect(() => {
    if (creationForm) return;
    if (!selectedId || isNewDeck) return;
    if (pickerSkipRef.current) {
      pickerSkipRef.current = false;
      return;
    }
    const picked = decks.find((entry) => entry.id === selectedId);
    if (!picked) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEditWidgets(deepCloneWidgets(picked.widgets));
    setEditOverflow((picked.overflow as OverflowMode) ?? "shrink-to-fit");
    setEditDisplayName(picked.display_name ?? "");
    setEditTheme((picked as { theme?: string | null }).theme ?? "");
    setEditIcon((picked as { icon?: Icon | null }).icon ?? null);
    setEditJogstrip((picked as { jogstrip?: boolean }).jogstrip ?? true);
    setEditMatch(picked.match ?? []);
    setSelectedIndex(null);
    setSaveStatus("idle");
    setSaveError("");
    dirtyRef.current = false;
  }, [selectedId, decks, isNewDeck, creationForm]);

  useEffect(() => {
    if (mockDecks) return;
    const base = resolveBaseUrl();
    let cancelled = false;
    fetch(`${base}/decks`, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((data: DeckListResponse) => {
        if (!cancelled && data.ok && Array.isArray(data.decks)) {
          setDecks(data.decks);
          if (!selectedId && data.decks.length > 0) {
            const firstReal = data.decks.find((entry) => entry.id !== EDITOR_VIEW_ID) ?? data.decks[0];
            setSelectedId(firstReal.id);
          }
        }
      })
      .catch((err) => {
        if (!cancelled) console.error("failed to fetch decks", err);
      });
    return () => { cancelled = true; };
    // selectedId is intentionally excluded from deps: we only want the
    // initial auto-select on first fetch, not on every user pick change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mockDecks]);

  const selectedDeck = decks.find((entry) => entry.id === selectedId) ?? null;

  const handlePick = useCallback((id: string) => {
    setSelectedId(id);
    setPickerOpen(false);
    setSaveStatus("idle");
    setCreationForm(null);
  }, []);

  const handleSave = useCallback(async () => {
    if (isNewDeck) {
      if (!draft.match.length) return;
      setSaveStatus("saving");
      try {
        const base = resolveBaseUrl();
        const res = await fetch(`${base}/decks`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...getAuthHeaders() },
          body: JSON.stringify({
            match: draft.match,
            display_name: draft.displayName || undefined,
            widgets: editWidgets.map(stripReadOnly),
            overflow: editOverflow,
          }),
        });
        if (res.ok) {
          const data = (await res.json()) as { ok: boolean; deck?: { id: string; match: string[]; display_name?: string | null; widgets: Widget[]; overflow?: string | null } };
          if (data.ok && data.deck) {
            dirtyRef.current = false;
            setSaveStatus("saved");
            setDecks((prev) => {
              const entry: DeckEntry = {
                id: data.deck!.id,
                match: data.deck!.match,
                display_name: data.deck!.display_name,
                widgets: data.deck!.widgets,
                overflow: data.deck!.overflow,
              };
              return [...prev, entry];
            });
            setSelectedId(data.deck.id);
            setDraft({ match: [], displayName: "" });
            setTimeout(() => setSaveStatus("idle"), 2000);
          } else {
            setSaveStatus("error");
          }
        } else {
          const body = await res.json().catch(() => ({})) as { error?: string; details?: { loc: (string | number)[]; msg: string }[] };
          const msg = body.details?.length
            ? body.details.map((d) => `${d.loc.join(".")}: ${d.msg}`).join("; ")
            : body.error || `Status ${res.status}`;
          setSaveError(msg);
          setSaveStatus("error");
        }
      } catch (e) {
        setSaveError(String(e));
        setSaveStatus("error");
      }
      return;
    }

    if (!selectedId) return;
    setSaveStatus("saving");
    setSaveError("");
    try {
      const base = resolveBaseUrl();
      const body: Record<string, unknown> = {
        match: editMatch,
        widgets: editWidgets.map(stripReadOnly),
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
        `${base}/decks/${encodeURIComponent(selectedId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json", ...getAuthHeaders() },
          body: JSON.stringify(body),
        },
      );
      if (res.ok) {
        dirtyRef.current = false;
        setSaveStatus("saved");
        setTimeout(() => setSaveStatus("idle"), 2000);
      } else {
        const errBody = await res.json().catch(() => ({})) as { error?: string; details?: { loc: (string | number)[]; msg: string }[] };
        const msg = errBody.details?.length
          ? errBody.details.map((d) => `${d.loc.join(".")}: ${d.msg}`).join("; ")
          : errBody.error || `Status ${res.status}`;
        setSaveError(msg);
        setSaveStatus("error");
      }
    } catch (e) {
      setSaveError(String(e));
      setSaveStatus("error");
    }
  }, [isNewDeck, selectedId, draft, editWidgets, editOverflow, editDisplayName, editTheme, editIcon, editJogstrip, editMatch]);

  const handleExit = useCallback(() => {
    if (isNewDeck) {
      if (!window.confirm("Abandon this new deck? Nothing is saved yet.")) {
        return;
      }
      send({ type: "clear_view" });
      onExit();
      return;
    }
    if (dirtyRef.current && !window.confirm("You have unsaved changes. Leave anyway?")) {
      return;
    }
    send({ type: "clear_view" });
    onExit();
  }, [send, onExit, isNewDeck]);

  // Open the manual "new deck" creation form from the picker.
  const handleNewDeckClick = useCallback(() => {
    setPickerOpen(false);
    setCreationForm({
      kind: "manual",
      match: "",
      displayName: "",
      label: "New deck",
    });
    setCreationMatchInput("");
    setCreationDisplayNameInput("");
  }, []);

  // Confirm creation: enter new-deck editing mode with the entered tokens.
  // Reset the deck-level edit state so the properties panel doesn't show
  // stale values from a previously-loaded deck (#88: a brand-new deck
  // has no theme/icon/jogstrip override — the panel must reflect that),
  // and prefill the display_name to match the draft (#88 "prefilled
  // display_name").
  const handleCreateConfirm = useCallback(() => {
    const match = creationMatchInput.trim();
    if (!match) return;
    const displayName = creationDisplayNameInput.trim() || match;
    setDraft({ match: [match], displayName });
    setSelectedId(NEW_DECK_SENTINEL);
    setEditWidgets([]);
    setEditOverflow("shrink-to-fit");
    setEditDisplayName(displayName);
    setEditTheme("");
    setEditIcon(null);
    setEditJogstrip(true);
    setSelectedIndex(null);
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
    dirtyRef.current = true;
    setSaveStatus("idle");
  }, []);

  const handleOverflowChange = useCallback((mode: OverflowMode) => {
    dirtyRef.current = true;
    setEditOverflow(mode);
    setSaveStatus("idle");
  }, []);

  const handleDeckFieldChange = useCallback((field: string, value: unknown) => {
    dirtyRef.current = true;
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
      case "overflow":
        setEditOverflow(value as OverflowMode);
        break;
    }
  }, []);

  const handleSelectWidget = useCallback((index: number | null) => {
    setSelectedIndex(index);
  }, []);

  const handleWidgetChange = useCallback((index: number, widget: Widget) => {
    dirtyRef.current = true;
    setEditWidgets((prev) => {
      const next = [...prev];
      next[index] = widget;
      return next;
    });
    setSaveStatus("idle");
  }, []);

  const handleDeleteWidget = useCallback((index: number) => {
    dirtyRef.current = true;
    setEditWidgets((prev) => prev.filter((_, i) => i !== index));
    setSelectedIndex(null);
    setSaveStatus("idle");
  }, []);

  // Palette insert (#103): append the minted widget and select it so its
  // id is immediately editable in the properties panel. New widgets are
  // bare — no default icon/color/label (#83); a meter's ``source`` and a
  // stats widget's ``metrics`` are filled in via the properties panel,
  // with the daemon's validators backstopping an early save.
  const handleAddWidget = useCallback((kind: PaletteKind) => {
    dirtyRef.current = true;
    setSaveStatus("idle");
    setEditWidgets([...editWidgets, { id: mintWidgetId(kind, editWidgets), kind }]);
    setSelectedIndex(editWidgets.length);
  }, [editWidgets]);

  const widgetCount = editWidgets.length;

  // The label shown in the picker trigger.
  const pickerLabel = useMemo(() => {
    if (isNewDeck) {
      return draft.displayName || draft.match[0] || "New deck";
    }
    if (selectedDeck) {
      return selectedDeck.display_name?.trim() || selectedDeck.id;
    }
    return "Select deck";
  }, [isNewDeck, selectedDeck, draft]);

  // The metadata row data for the canvas header.
  const canvasMeta = useMemo(() => {
    if (isNewDeck) {
      return {
        app: draft.displayName || draft.match[0] || "New deck",
        match: `match: ${draft.match.join(", ") || "(none)"}`,
      };
    }
    if (selectedDeck) {
      return {
        app: selectedDeck.display_name?.trim() || selectedDeck.id,
        match: `match: ${selectedDeck.match.join(", ")}`,
      };
    }
    return null;
  }, [isNewDeck, selectedDeck, draft]);

  const canSave = isNewDeck ? draft.match.length > 0 : !!selectedId;

  return (
    <div className="editor" role="region" aria-label="deck editor">
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
            {isNewDeck ? "New deck" : "Edit deck"}
          </h2>
        </div>
        <div className="editor-header-right">
          <div className="editor-picker">
            <button
              className="editor-picker-trigger"
              aria-label="select deck to edit"
              aria-haspopup="listbox"
              aria-expanded={pickerOpen}
              onClick={() => setPickerOpen((v) => !v)}
            >
              <span className="editor-picker-label">{pickerLabel}</span>
              <ChevronDown size={14} />
            </button>
            {pickerOpen && (
              <ul className="editor-picker-list" role="listbox">
                {decks.map((entry) => (
                  <li
                    key={entry.id}
                    role="option"
                    aria-selected={entry.id === selectedId}
                    className={`editor-picker-option${entry.id === selectedId ? " editor-picker-option-active" : ""}${entry.id === EDITOR_VIEW_ID ? " editor-picker-option-view" : ""}`}
                    onClick={() => handlePick(entry.id)}
                  >
                    <span>{entry.display_name?.trim() || entry.id}</span>
                    {entry.id === EDITOR_VIEW_ID ? (
                      <span className="editor-picker-tag">chrome view</span>
                    ) : null}
                    {entry.id === selectedId ? <Check size={14} /> : null}
                  </li>
                ))}
                <li className="editor-picker-separator" role="separator" />
                <li
                  role="option"
                  className="editor-picker-option editor-picker-option-new"
                  onClick={handleNewDeckClick}
                >
                  <Plus size={14} />
                  <span>New deck</span>
                </li>
              </ul>
            )}
          </div>
        </div>
        <div className="editor-save-group">
          <button
            className="editor-save-btn"
            aria-label="save deck"
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
          {saveError && (
            <p className="editor-save-error">{saveError}</p>
          )}
        </div>
      </header>
      <div className="editor-panes">
        <aside className="editor-pane editor-palette" role="complementary" aria-label="widget palette">
          <h3 className="editor-pane-title">Palette</h3>
          <EditorPalette
            onAdd={handleAddWidget}
            disabled={!!creationForm || (!selectedDeck && !isNewDeck)}
          />
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
          ) : selectedDeck || isNewDeck ? (
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
            <p className="editor-pane-placeholder">No deck selected</p>
          )}
        </section>
        <aside className="editor-pane editor-properties" role="complementary" aria-label="properties panel">
          <PropertiesPanel
            widget={selectedIndex != null ? editWidgets[selectedIndex] ?? null : null}
            deckFields={{
              display_name: editDisplayName || null,
              theme: editTheme || null,
              icon: editIcon,
              jogstrip: editJogstrip,
              overflow: editOverflow,
            }}
            onWidgetChange={(w) => {
              if (selectedIndex != null) handleWidgetChange(selectedIndex, w);
            }}
            onDeckFieldChange={handleDeckFieldChange}
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
 * and manual new-deck entry. */
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
            Deck for {form.altDisplayName}
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
          Create deck
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

/** Strip GET-read-only keys from a widget before sending in a PUT/POST body.
 * ``has_action`` and ``kind_specific`` are diagnostics-only fields not in the
 * daemon's Widget model (extra="forbid"). The authenticated editor receives
 * full ``action`` and ``macro`` bodies — those are NOT stripped. */
function stripReadOnly(widget: Widget): Record<string, unknown> {
  const { has_action: _has_action, kind_specific: _kind_specific, ...rest } = widget as Widget & { has_action?: boolean; kind_specific?: Record<string, unknown> };
  return rest as Record<string, unknown>;
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
