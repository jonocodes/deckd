import { useCallback } from "react";
import { Trash2 } from "lucide-react";

export type ActionFields = {
  key?: string | null;
  shell?: string | null;
  dbus?: string | null;
  terminal?: boolean | null;
  url?: string | null;
  text?: string | null;
  text_mode?: "simulate" | "paste" | null;
  restore_clipboard?: boolean;
  restore_clipboard_delay_ms?: number;
};

type Props = {
  action: ActionFields | null | undefined;
  onChange: (action: ActionFields | null) => void;
};

function fieldVal(action: ActionFields | null | undefined, k: keyof ActionFields): string {
  const v = action?.[k];
  if (v === null || v === undefined || v === false) return "";
  return String(v);
}

function setAction<K extends keyof ActionFields>(
  field: K,
  action: ActionFields | null | undefined,
  value: ActionFields[K],
): ActionFields | null {
  const next = { ...(action ?? {}), [field]: value };
  if (value === null || value === undefined || value === "" || value === false) {
    delete next[field];
  }
  if (field === "terminal" && value === true) {
    delete next.text;
    delete next.text_mode;
    delete next.restore_clipboard;
    delete next.restore_clipboard_delay_ms;
  }
  if ((field === "text" || field === "text_mode") && (next.text || next.text_mode)) {
    delete next.terminal;
  }
  const nonOpt = Object.keys(next).filter(
    (k) => k !== "restore_clipboard" && k !== "restore_clipboard_delay_ms" && k !== "text_mode",
  );
  const hasPayload = nonOpt.some(
    (k) => next[k as keyof ActionFields] != null && next[k as keyof ActionFields] !== false,
  );
  if (!hasPayload && !next.text && !next.terminal) return null;
  return next;
}

function hasAction(action: ActionFields | null | undefined): boolean {
  if (!action) return false;
  return Object.keys(action).some(
    (k) =>
      k !== "restore_clipboard" &&
      k !== "restore_clipboard_delay_ms" &&
      k !== "text_mode" &&
      (action[k as keyof ActionFields] != null) &&
      (action[k as keyof ActionFields] !== false),
  ) || Object.keys(action).length === 0;
}

export function ActionEditor({ action, onChange }: Props) {
  const handleRemove = useCallback(() => onChange(null), [onChange]);

  if (!hasAction(action)) {
    return (
      <div className="prop-section">
        <div className="prop-section-header">
          <span className="prop-section-title">Action</span>
          <button
            type="button"
            className="prop-field-btn prop-field-btn-add"
            onClick={() => onChange({})}
          >
            Add
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="prop-section">
      <div className="prop-section-header">
        <span className="prop-section-title">Action</span>
        <button
          type="button"
          className="prop-field-btn prop-field-btn-remove"
          aria-label="remove action"
          onClick={handleRemove}
        >
          <Trash2 size={14} />
        </button>
      </div>
      <label className="prop-field">
        <span className="prop-field-label">Key combo</span>
        <input
          className="prop-field-input"
          type="text"
          value={fieldVal(action, "key")}
          onChange={(e) => onChange(setAction("key", action, e.target.value || null))}
          placeholder="e.g. ctrl+t"
        />
      </label>
      <label className="prop-field">
        <span className="prop-field-label">Shell</span>
        <input
          className="prop-field-input"
          type="text"
          value={fieldVal(action, "shell")}
          onChange={(e) => onChange(setAction("shell", action, e.target.value || null))}
          placeholder="e.g. firefox"
        />
      </label>
      <label className="prop-field">
        <span className="prop-field-label">D-Bus</span>
        <input
          className="prop-field-input"
          type="text"
          value={fieldVal(action, "dbus")}
          onChange={(e) => onChange(setAction("dbus", action, e.target.value || null))}
          placeholder="method call string"
        />
      </label>
      <label className="prop-field">
        <span className="prop-field-label">URL</span>
        <input
          className="prop-field-input"
          type="text"
          value={fieldVal(action, "url")}
          onChange={(e) => onChange(setAction("url", action, e.target.value || null))}
          placeholder="https://..."
          disabled={action?.terminal === true}
        />
      </label>
      <label className="prop-field">
        <span className="prop-field-label">Text</span>
        <input
          className="prop-field-input"
          type="text"
          value={fieldVal(action, "text")}
          onChange={(e) => onChange(setAction("text", action, e.target.value || null))}
          placeholder="type a string"
          disabled={action?.terminal === true}
        />
      </label>
      <label className="prop-field prop-field-check">
        <input
          type="checkbox"
          checked={action?.terminal === true}
          onChange={(e) => onChange(setAction("terminal", action, e.target.checked || null))}
        />
        <span className="prop-field-label">Open terminal</span>
      </label>
    </div>
  );
}
