import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Minimize, Maximize, Columns2, Plus, Minus } from "lucide-react";
import { computeReflow } from "./reflow";
import type { OverflowMode } from "./reflow";
import type { Widget, WidgetSize } from "./protocol";
import { CELL_SIZE_DEFAULT } from "./settings-store";
import { Icon } from "./Icon";

const GRID_GAP = 8;
const MAX_SPAN = 4;

type Props = {
  widgets: Widget[];
  overflow: OverflowMode;
  selectedIndex: number | null;
  onReorder: (from: number, to: number) => void;
  onWidgetChange: (index: number, widget: Widget) => void;
  onOverflowChange: (mode: OverflowMode) => void;
  onSelectWidget: (index: number | null) => void;
  cellSize?: number;
};

function useMeasuredSize(): [
  React.RefObject<HTMLDivElement>,
  { width: number; height: number },
] {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const update = () =>
      setSize({ width: el.clientWidth, height: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size];
}

function spanOf(w: Widget): [number, number] {
  if (w.size == null || w.size === "full") return [1, 1];
  const [cw, ch] = w.size;
  return [Math.max(1, cw), Math.max(1, ch)];
}

function widgetLabel(w: Widget): string {
  if (w.label) return w.label;
  if (w.kind === "blank") return "gap";
  return w.id;
}

function widgetIcon(w: Widget): string {
  if (w.kind === "blank") return "⊡";
  if (w.kind === "meter") return "📊";
  if (w.kind === "stats") return "📈";
  if (w.kind === "jogstrip") return "↕";
  if (w.kind === "media" || w.kind === "mediabrowser") return "🎬";
  if (w.kind === "trackpad") return "✋";
  if (w.icon) return "";
  return "⬛";
}

const UNSUPPORTED_KINDS = new Set(["media", "mediabrowser"]);

function adjustSpan(widget: Widget, dw: number, dh: number): Widget {
  const isFull = widget.size === "full";
  if (isFull) {
    const newSize: WidgetSize = [Math.max(1, dw), Math.max(1, dh)];
    return { ...widget, size: newSize };
  }
  const [cw, ch] = spanOf(widget);
  const nw = Math.max(1, Math.min(MAX_SPAN, cw + dw));
  const nh = Math.max(1, Math.min(MAX_SPAN, ch + dh));
  const newSize: WidgetSize = [nw, nh];
  return { ...widget, size: newSize };
}

function toggleFull(widget: Widget): Widget {
  if (widget.size === "full") {
    return { ...widget, size: undefined };
  }
  return { ...widget, size: "full" };
}

function spanLabel(widget: Widget): string {
  if (widget.size === "full") return "full";
  const [cw, ch] = spanOf(widget);
  return `${cw}\u00d7${ch}`;
}

function SortableCell({
  widget,
  index,
  colSpan,
  selected,
  onSelect,
  onWidgetChange,
}: {
  widget: Widget;
  index: number;
  colSpan: number;
  selected: boolean;
  onSelect?: (index: number | null) => void;
  onWidgetChange?: (idx: number, w: Widget) => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: widget.id });

  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    gridColumn: `span ${Math.min(spanOf(widget)[0], colSpan)}`,
    opacity: isDragging ? 0.5 : undefined,
    zIndex: isDragging ? 10 : undefined,
    ...(widget.color ? { backgroundColor: widget.color } : {}),
  };

  const isUnsupported = UNSUPPORTED_KINDS.has(widget.kind);
  const hasIcon = widget.icon && !isUnsupported;

  const handleSpanInc = useCallback(
    (dw: number, dh: number, e: React.MouseEvent) => {
      e.stopPropagation();
      onWidgetChange?.(index, adjustSpan(widget, dw, dh));
    },
    [widget, index, onWidgetChange],
  );

  const handleFullToggle = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onWidgetChange?.(index, toggleFull(widget));
    },
    [widget, index, onWidgetChange],
  );

  const handleSelect = useCallback(
    (e: React.MouseEvent) => {
      if ((e.target as HTMLElement).closest("button")) return;
      onSelect?.(index);
    },
    [index, onSelect],
  );

  return (
    <div
      ref={setNodeRef}
      className={`editor-canvas-cell${widget.kind === "blank" ? " editor-canvas-cell-blank" : ""}${isUnsupported ? " editor-canvas-cell-unsupported" : ""}${selected ? " editor-canvas-cell-selected" : ""}`}
      style={style}
      data-widget-id={widget.id}
      onClick={handleSelect}
    >
      <button
        className="editor-canvas-cell-drag"
        aria-label={`drag to reorder ${widgetLabel(widget)}`}
        {...attributes}
        {...listeners}
      >
        <GripVertical size={14} />
      </button>
      <div className="editor-canvas-cell-body">
        <div className="editor-canvas-cell-icon">
          {hasIcon && widget.icon ? (
            <Icon icon={widget.icon} className="icon" />
          ) : (
            <span className="editor-canvas-cell-glyph">{widgetIcon(widget)}</span>
          )}
        </div>
        <span className="editor-canvas-cell-label">{widgetLabel(widget)}</span>
      </div>
      {isUnsupported && (
        <span className="editor-canvas-cell-unsupported-badge">placeholder</span>
      )}
      <div className="editor-canvas-cell-kind">{widget.kind}</div>
      {onWidgetChange && (
        <div className="editor-canvas-cell-span">
          <div className="editor-canvas-cell-span-controls">
            <button
              className="editor-canvas-cell-span-btn"
              aria-label={`decrease width of ${widgetLabel(widget)}`}
              title="Narrower"
              onClick={(e) => handleSpanInc(-1, 0, e)}
              disabled={widget.size === "full"}
            >
              <Minus size={10} />
            </button>
            <button
              className="editor-canvas-cell-span-full-btn"
              aria-label={`toggle full surface for ${widgetLabel(widget)}`}
              title={widget.size === "full" ? "Revert to span" : "Make full-surface"}
              onClick={handleFullToggle}
            >
              {spanLabel(widget)}
            </button>
            <button
              className="editor-canvas-cell-span-btn"
              aria-label={`increase width of ${widgetLabel(widget)}`}
              title="Wider"
              onClick={(e) => handleSpanInc(1, 0, e)}
              disabled={widget.size === "full"}
            >
              <Plus size={10} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Viewport-preview widths: common device viewport widths in CSS px. */
const PREVIEW_WIDTHS = [
  { label: "Full", value: 0 },
  { label: "1024", value: 1024 },
  { label: "768", value: 768 },
  { label: "480", value: 480 },
  { label: "360", value: 360 },
];

export function EditorCanvas({
  widgets,
  overflow,
  selectedIndex,
  onReorder,
  onWidgetChange,
  onOverflowChange,
  onSelectWidget,
  cellSize = CELL_SIZE_DEFAULT,
}: Props) {
  const [gridRef, size] = useMeasuredSize();
  const [previewWidth, setPreviewWidth] = useState(0);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;
      const oldIndex = widgets.findIndex((w) => w.id === active.id);
      const newIndex = widgets.findIndex((w) => w.id === over.id);
      if (oldIndex === -1 || newIndex === -1) return;
      onReorder(oldIndex, newIndex);
      if (selectedIndex === oldIndex) {
        onSelectWidget(newIndex);
      }
    },
    [widgets, onReorder, selectedIndex, onSelectWidget],
  );

  const totalUnits = useMemo(
    () =>
      widgets.reduce((sum, w) => {
        if (w.size === "full") return sum;
        const [cw, ch] = spanOf(w);
        return sum + cw * ch;
      }, 0),
    [widgets],
  );

  const displayWidth = previewWidth > 0 ? previewWidth : size.width;

  const { cols, cellPx } = computeReflow({
    containerWidth: displayWidth,
    containerHeight: size.height,
    cellSize,
    gap: GRID_GAP,
    totalUnits,
    mode: overflow,
  });

  const gridStyle: CSSProperties = {
    gridTemplateColumns: `repeat(${cols}, ${cellPx}px)`,
    gridAutoRows: `${cellPx}px`,
  };

  const previewActive = previewWidth > 0;

  const handleGridClick = useCallback(
    (e: React.MouseEvent) => {
      if ((e.target as HTMLElement).closest('[data-widget-id]')) return;
      onSelectWidget(null);
    },
    [onSelectWidget],
  );

  return (
    <div className="editor-canvas-content">
      <div className="editor-canvas-toolbar">
        <div className="editor-canvas-toolbar-group">
          <span className="editor-canvas-toolbar-label">Overflow</span>
          <button
            className={`editor-canvas-toolbar-btn${overflow === "shrink-to-fit" ? " editor-canvas-toolbar-btn-active" : ""}`}
            aria-label="shrink to fit"
            aria-pressed={overflow === "shrink-to-fit"}
            title="Shrink cells so every widget fits the viewport"
            onClick={() => onOverflowChange("shrink-to-fit")}
          >
            <Minimize size={14} />
            <span>shrink-to-fit</span>
          </button>
          <button
            className={`editor-canvas-toolbar-btn${overflow === "clip" ? " editor-canvas-toolbar-btn-active" : ""}`}
            aria-label="clip"
            aria-pressed={overflow === "clip"}
            title="Clip trailing widgets that exceed viewport height"
            onClick={() => onOverflowChange("clip")}
          >
            <Maximize size={14} />
            <span>clip</span>
          </button>
        </div>
        <div className="editor-canvas-toolbar-group">
          <span className="editor-canvas-toolbar-label">Viewport</span>
          {PREVIEW_WIDTHS.map((pw) => (
            <button
              key={pw.label}
              className={`editor-canvas-toolbar-btn${previewWidth === pw.value ? " editor-canvas-toolbar-btn-active" : ""}`}
              aria-label={`preview at ${pw.label.toLowerCase()} width`}
              aria-pressed={previewWidth === pw.value}
              onClick={() => setPreviewWidth(pw.value)}
            >
              {pw.value === 0 ? (
                <Columns2 size={14} />
              ) : null}
              <span>{pw.label}</span>
            </button>
          ))}
        </div>
      </div>
      <div
        ref={gridRef}
        className={`editor-canvas-grid${previewActive ? " editor-canvas-grid-preview" : ""}`}
        style={previewActive ? { maxWidth: previewWidth } : undefined}
        onClick={handleGridClick}
      >
        {widgets.length === 0 ? (
          <div className="editor-canvas-grid-empty">
            No widgets. Drag from the palette or add a new widget.
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={widgets.map((w) => w.id)}
              strategy={undefined}
            >
              <div className="grid" style={gridStyle}>
                {widgets.map((w, i) => (
                  <SortableCell
                    key={w.id}
                    widget={w}
                    index={i}
                    colSpan={cols}
                    selected={selectedIndex === i}
                    onSelect={onSelectWidget}
                    onWidgetChange={onWidgetChange}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        )}
      </div>
    </div>
  );
}
