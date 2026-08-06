import { useCallback, useState } from "react";
import { Search, Trash2 } from "lucide-react";
import type { Widget, Icon as IconRef } from "./protocol";
import { ActionEditor } from "./ActionEditor";
import type { ActionFields } from "./ActionEditor";
import { Icon as IconGlyph } from "./Icon";
import { IconPicker } from "./IconPicker";

interface LayoutFields {
  display_name?: string | null;
  theme?: string | null;
  icon?: IconRef | null;
  jogstrip?: boolean;
  overflow?: "clip" | "shrink-to-fit";
}

type Props = {
  widget: Widget | null;
  layoutFields: LayoutFields;
  onWidgetChange: (widget: Widget) => void;
  onLayoutFieldChange: (field: string, value: unknown) => void;
  onDeleteWidget?: () => void;
};

function updateField<K extends keyof Widget>(
  widget: Widget,
  field: K,
  value: Widget[K],
): Widget {
  const next = { ...widget, [field]: value };
  if (value === null || value === undefined || value === "") {
    delete next[field];
  }
  return next;
}

function iconFromWidget(widget: Widget): IconRef | null | undefined {
  return widget.icon;
}

function iconFromLayout(lf: LayoutFields): IconRef | null | undefined {
  return lf.icon;
}

export function PropertiesPanel({
  widget,
  layoutFields,
  onWidgetChange,
  onLayoutFieldChange,
  onDeleteWidget,
}: Props) {
  if (!widget) {
    return (
      <div className="prop-panel">
        <h3 className="editor-pane-title">Layout</h3>
        <label className="prop-field">
          <span className="prop-field-label">Display name</span>
          <input
            className="prop-field-input"
            type="text"
            value={layoutFields.display_name ?? ""}
            onChange={(e) => onLayoutFieldChange("display_name", e.target.value || null)}
            placeholder="(derived from match)"
          />
        </label>
        <label className="prop-field">
          <span className="prop-field-label">Theme</span>
          <input
            className="prop-field-input"
            type="text"
            value={layoutFields.theme ?? ""}
            onChange={(e) => onLayoutFieldChange("theme", e.target.value || null)}
            placeholder="e.g. #ff7139 or hsl(...)"
          />
        </label>
        <IconField
          icon={iconFromLayout(layoutFields)}
          onChange={(icon) => onLayoutFieldChange("icon", icon)}
        />
        <label className="prop-field prop-field-check">
          <input
            type="checkbox"
            checked={layoutFields.jogstrip !== false}
            onChange={(e) => onLayoutFieldChange("jogstrip", e.target.checked)}
          />
          <span className="prop-field-label">Jogstrip</span>
        </label>
        <label className="prop-field">
          <span className="prop-field-label">Overflow</span>
          <select
            className="prop-field-input"
            value={layoutFields.overflow ?? "shrink-to-fit"}
            onChange={(e) => onLayoutFieldChange("overflow", e.target.value)}
          >
            <option value="shrink-to-fit">Shrink to fit</option>
            <option value="clip">Clip</option>
          </select>
        </label>
      </div>
    );
  }

  const isUnsupported = widget.kind === "media" || widget.kind === "nowplaying";

  if (isUnsupported) {
    return (
      <div className="prop-panel">
        <h3 className="editor-pane-title">
          {widget.kind === "media" ? "Media" : "Media Browser"}
        </h3>
        <label className="prop-field">
          <span className="prop-field-label">ID</span>
          <input className="prop-field-input" type="text" value={widget.id} readOnly />
        </label>
        <label className="prop-field">
          <span className="prop-field-label">Kind</span>
          <input className="prop-field-input" type="text" value={widget.kind} readOnly />
        </label>
        <p className="prop-field-note">Reorder / delete only</p>
      </div>
    );
  }

  return (
    <div className="prop-panel">
      <h3 className="editor-pane-title">
        {widget.kind.charAt(0).toUpperCase() + widget.kind.slice(1)}
      </h3>

      <label className="prop-field">
        <span className="prop-field-label">ID</span>
        <input
          className="prop-field-input"
          type="text"
          value={widget.id}
          onChange={(e) => {
            const v = e.target.value;
            if (v) onWidgetChange(updateField(widget, "id", v));
          }}
          placeholder={widget.id}
        />
      </label>

      <label className="prop-field">
        <span className="prop-field-label">Kind</span>
        <input className="prop-field-input" type="text" value={widget.kind} readOnly />
      </label>

      {widget.kind !== "blank" && (
        <>
          <label className="prop-field">
            <span className="prop-field-label">Label</span>
            <input
              className="prop-field-input"
              type="text"
              value={widget.label ?? ""}
              onChange={(e) => onWidgetChange(updateField(widget, "label", e.target.value || null))}
              placeholder="(optional)"
            />
          </label>

          <IconField
            icon={iconFromWidget(widget)}
            onChange={(icon) => onWidgetChange(updateField(widget, "icon", icon))}
          />

          <label className="prop-field">
            <span className="prop-field-label">Color</span>
            <input
              className="prop-field-input"
              type="text"
              value={widget.color ?? ""}
              onChange={(e) => onWidgetChange(updateField(widget, "color", e.target.value || null))}
              placeholder="e.g. #1e3a8a"
            />
          </label>
        </>
      )}

      {(widget.kind === "button" || widget.kind === "blank" || widget.kind === "meter" || widget.kind === "stats") && (
        <label className="prop-field">
          <span className="prop-field-label">Size</span>
          <div className="prop-field-size-row">
            <label className="prop-field-size-item">
              <input
                className="prop-field-input prop-field-input-num"
                type="number"
                min={1}
                max={4}
                value={sizeW(widget)}
                onChange={(e) => onWidgetChange(updateSize(widget, Math.max(1, Number(e.target.value) || 1), sizeH(widget)))}
              />
              <span className="prop-field-size-label">w</span>
            </label>
            <span className="prop-field-size-sep">x</span>
            <label className="prop-field-size-item">
              <input
                className="prop-field-input prop-field-input-num"
                type="number"
                min={1}
                max={4}
                value={sizeH(widget)}
                onChange={(e) => onWidgetChange(updateSize(widget, sizeW(widget), Math.max(1, Number(e.target.value) || 1)))}
              />
              <span className="prop-field-size-label">h</span>
            </label>
          </div>
        </label>
      )}

      {(widget.kind === "button" || widget.kind === "meter" || widget.kind === "stats") && (
        <ActionEditor
          action={widget.action as ActionFields | null | undefined}
          onChange={(action) => onWidgetChange(updateField(widget, "action", action))}
        />
      )}

      {widget.kind === "meter" && (
        <div className="prop-section">
          <div className="prop-section-header">
            <span className="prop-section-title">Meter</span>
          </div>
          <label className="prop-field">
            <span className="prop-field-label">Source</span>
            <input
              className="prop-field-input"
              type="text"
              value={widget.source ?? ""}
              onChange={(e) => onWidgetChange(updateField(widget, "source", e.target.value || null))}
              placeholder="e.g. cpu_percent"
            />
          </label>
          <label className="prop-field">
            <span className="prop-field-label">Min</span>
            <input
              className="prop-field-input"
              type="number"
              value={widget.min ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                onWidgetChange(updateField(widget, "min", v === "" ? null : Number(v)));
              }}
              placeholder="0"
            />
          </label>
          <label className="prop-field">
            <span className="prop-field-label">Max</span>
            <input
              className="prop-field-input"
              type="number"
              value={widget.max ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                onWidgetChange(updateField(widget, "max", v === "" ? null : Number(v)));
              }}
              placeholder="100"
            />
          </label>
        </div>
      )}

      {widget.kind === "stats" && (
        <MetricsEditor
          metrics={widget.metrics ?? []}
          onChange={(metrics) => onWidgetChange(updateField(widget, "metrics", metrics))}
        />
      )}

      {onDeleteWidget && widget.kind !== "blank" && (
        <div className="prop-section">
          <button
            type="button"
            className="prop-field-btn prop-field-btn-delete"
            onClick={onDeleteWidget}
          >
            <Trash2 size={14} />
            <span>Delete widget</span>
          </button>
        </div>
      )}
    </div>
  );
}

function sizeW(widget: Widget): number {
  if (widget.size == null || widget.size === "full") return 1;
  return widget.size[0];
}
function sizeH(widget: Widget): number {
  if (widget.size == null || widget.size === "full") return 1;
  return widget.size[1];
}
function updateSize(widget: Widget, w: number, h: number): Widget {
  return { ...widget, size: [w, h] };
}

function IconField({
  icon,
  onChange,
}: {
  icon: IconRef | null | undefined;
  onChange: (icon: IconRef | null) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const handleClear = useCallback(() => onChange(null), [onChange]);

  return (
    <div className="prop-section">
      <div className="prop-section-header">
        <span className="prop-section-title">Icon</span>
        {icon && (
          <button
            type="button"
            className="prop-field-btn prop-field-btn-remove"
            aria-label="remove icon"
            onClick={handleClear}
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
      {icon ? (
        <div className="prop-field-icon-preview">
          <IconGlyph icon={icon} className="prop-field-icon-glyph" />
          <span className="prop-field-icon-name">
            {icon.source}/{icon.name}
          </span>
          <button
            type="button"
            className="prop-field-btn icon-picker-trigger"
            aria-label="change icon"
            onClick={() => setPickerOpen(true)}
          >
            <Search size={14} />
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="prop-field-btn prop-field-btn-add icon-picker-trigger"
          onClick={() => setPickerOpen(true)}
        >
          <Search size={14} />
          <span>Browse icons…</span>
        </button>
      )}
      <IconPicker
        value={icon ?? null}
        onChange={onChange}
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
      />
    </div>
  );
}

function MetricsEditor({
  metrics,
  onChange,
}: {
  metrics: { source: string; label?: string | null }[];
  onChange: (metrics: { source: string; label?: string | null }[]) => void;
}) {
  const handleMetricChange = useCallback(
    (index: number, field: "source" | "label", value: string) => {
      const next = [...metrics];
      next[index] = { ...next[index], [field]: value || null };
      onChange(next);
    },
    [metrics, onChange],
  );

  const handleAdd = useCallback(() => {
    onChange([...metrics, { source: "", label: null }]);
  }, [metrics, onChange]);

  const handleRemove = useCallback(
    (index: number) => {
      onChange(metrics.filter((_, i) => i !== index));
    },
    [metrics, onChange],
  );

  return (
    <div className="prop-section">
      <div className="prop-section-header">
        <span className="prop-section-title">Metrics</span>
        <button
          type="button"
          className="prop-field-btn prop-field-btn-add"
          onClick={handleAdd}
        >
          Add
        </button>
      </div>
      {metrics.map((m, i) => (
        <div key={i} className="prop-field-metric-row">
          <div className="prop-field-metric-fields">
            <input
              className="prop-field-input"
              type="text"
              value={m.source}
              onChange={(e) => handleMetricChange(i, "source", e.target.value)}
              placeholder="source"
            />
            <input
              className="prop-field-input"
              type="text"
              value={m.label ?? ""}
              onChange={(e) => handleMetricChange(i, "label", e.target.value)}
              placeholder="label"
            />
          </div>
          <button
            type="button"
            className="prop-field-btn prop-field-btn-remove"
            aria-label={`remove metric ${m.source || i}`}
            onClick={() => handleRemove(i)}
          >
            <Trash2 size={12} />
          </button>
        </div>
      ))}
      {metrics.length === 0 && (
        <p className="prop-field-note">No metrics yet.</p>
      )}
    </div>
  );
}
