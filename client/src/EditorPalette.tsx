import { BarChart3, Gauge, MousePointerClick, Square } from "lucide-react";

/** Widget kinds the palette can insert (#89): the v1 field-editable kinds
 * plus ``blank`` (the ADR-0010 gap primitive). The media family is
 * deliberately excluded — media widgets are opaque placeholders,
 * reorder/delete only, never insertable. */
export type PaletteKind = "button" | "meter" | "stats" | "blank";

const ITEMS: {
  kind: PaletteKind;
  label: string;
  hint: string;
  ItemIcon: typeof Gauge;
}[] = [
  { kind: "button", label: "Button", hint: "Key / shell / D-Bus action", ItemIcon: MousePointerClick },
  { kind: "meter", label: "Meter", hint: "Live sensor bar", ItemIcon: Gauge },
  { kind: "stats", label: "Stats", hint: "Sensor readout list", ItemIcon: BarChart3 },
  { kind: "blank", label: "Blank", hint: "Deliberate gap", ItemIcon: Square },
];

export function EditorPalette({
  onAdd,
  disabled = false,
}: {
  onAdd: (kind: PaletteKind) => void;
  disabled?: boolean;
}) {
  return (
    <div className="editor-palette-items">
      {ITEMS.map(({ kind, label, hint, ItemIcon }) => (
        <button
          key={kind}
          type="button"
          className="editor-palette-item"
          aria-label={`add ${label.toLowerCase()}`}
          title={disabled ? undefined : `Add a ${label.toLowerCase()} widget`}
          disabled={disabled}
          onClick={() => onAdd(kind)}
        >
          <ItemIcon size={16} className="editor-palette-item-icon" />
          <span className="editor-palette-item-text">
            <span className="editor-palette-item-label">{label}</span>
            <span className="editor-palette-item-hint">{hint}</span>
          </span>
        </button>
      ))}
    </div>
  );
}
