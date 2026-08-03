import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PropertiesPanel } from "./PropertiesPanel";
import type { Widget } from "./protocol";

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: vi.fn().mockImplementation(
    ({ count }: { count: number }) => {
      const items: { key: string; index: number; start: number; size: number }[] = [];
      const visible = Math.min(count, 10);
      for (let i = 0; i < visible; i++) {
        items.push({ key: `row-${i}`, index: i, start: i * 56, size: 56 });
      }
      return {
        getVirtualItems: () => items,
        getTotalSize: () => count * 56,
        measure: vi.fn(),
      };
    },
  ),
}));

const baseButton: Widget = {
  id: "btn-1",
  kind: "button",
  label: "Click me",
  color: "#1e3a8a",
  icon: { source: "lucide", name: "play" },
  size: [2, 1],
  action: { key: "ctrl+t" },
};

const baseMeter: Widget = {
  id: "meter-1",
  kind: "meter",
  label: "CPU",
  source: "cpu_percent",
  min: 0,
  max: 100,
  size: [2, 1],
};

const baseStats: Widget = {
  id: "stats-1",
  kind: "stats",
  label: "System",
  metrics: [
    { source: "cpu_percent", label: "CPU" },
    { source: "mem_percent", label: "MEM" },
  ],
};

const baseBlank: Widget = {
  id: "gap-1",
  kind: "blank",
  size: [1, 1],
};

const baseUnsupported: Widget = {
  id: "media-1",
  kind: "media",
  label: "VLC",
};

const layoutFields = {
  display_name: "My Layout",
  theme: "#ff7139",
  icon: { source: "lucide", name: "layout" } as const,
  jogstrip: true,
  overflow: "shrink-to-fit" as const,
};

describe("PropertiesPanel — layout-level fields", () => {
  afterEach(cleanup);

  it("renders layout fields when no widget is selected", () => {
    const onWidgetChange = vi.fn();
    const onLayoutChange = vi.fn();
    render(
      <PropertiesPanel
        widget={null}
        layoutFields={layoutFields}
        onWidgetChange={onWidgetChange}
        onLayoutFieldChange={onLayoutChange}
      />,
    );
    expect(screen.getByText("Layout")).toBeTruthy();
    expect(screen.getByText("Display name")).toBeTruthy();
    expect(screen.getByText("Theme")).toBeTruthy();
    expect(screen.getByText("Jogstrip")).toBeTruthy();
    expect(screen.getByText("Overflow")).toBeTruthy();
  });

  it("fires onLayoutFieldChange for display_name", () => {
    const onWidgetChange = vi.fn();
    const onLayoutChange = vi.fn();
    render(
      <PropertiesPanel
        widget={null}
        layoutFields={layoutFields}
        onWidgetChange={onWidgetChange}
        onLayoutFieldChange={onLayoutChange}
      />,
    );
    const input = screen.getByDisplayValue("My Layout");
    fireEvent.change(input, { target: { value: "New Name" } });
    expect(onLayoutChange).toHaveBeenCalledWith("display_name", "New Name");
  });

  it("fires onLayoutFieldChange for theme", () => {
    const onWidgetChange = vi.fn();
    const onLayoutChange = vi.fn();
    render(
      <PropertiesPanel
        widget={null}
        layoutFields={layoutFields}
        onWidgetChange={onWidgetChange}
        onLayoutFieldChange={onLayoutChange}
      />,
    );
    const input = screen.getByDisplayValue("#ff7139");
    fireEvent.change(input, { target: { value: "#ff0000" } });
    expect(onLayoutChange).toHaveBeenCalledWith("theme", "#ff0000");
  });

  it("toggles jogstrip checkbox", () => {
    const onWidgetChange = vi.fn();
    const onLayoutChange = vi.fn();
    render(
      <PropertiesPanel
        widget={null}
        layoutFields={layoutFields}
        onWidgetChange={onWidgetChange}
        onLayoutFieldChange={onLayoutChange}
      />,
    );
    const checkbox = screen.getByRole("checkbox");
    expect((checkbox as HTMLInputElement).checked).toBe(true);
    fireEvent.click(checkbox);
    expect(onLayoutChange).toHaveBeenCalledWith("jogstrip", false);
  });

  it("changes overflow select", () => {
    const onWidgetChange = vi.fn();
    const onLayoutChange = vi.fn();
    render(
      <PropertiesPanel
        widget={null}
        layoutFields={{ overflow: "shrink-to-fit" }}
        onWidgetChange={onWidgetChange}
        onLayoutFieldChange={onLayoutChange}
      />,
    );
    const combobox = screen.getByRole("combobox");
    fireEvent.change(combobox, { target: { value: "clip" } });
    expect(onLayoutChange).toHaveBeenCalledWith("overflow", "clip");
  });
});

describe("PropertiesPanel — button widget", () => {
  afterEach(cleanup);

  it("renders button fields", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseButton}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Button")).toBeTruthy();
    expect(screen.getByText("ID")).toBeTruthy();
    expect(screen.getByText("Kind")).toBeTruthy();
    expect(screen.getByText("Label")).toBeTruthy();
    expect(screen.getByText("Color")).toBeTruthy();
    expect(screen.getByText("Size")).toBeTruthy();
    expect(screen.getByText("Action")).toBeTruthy();
  });

  it("edits widget id", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseButton}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    const idInput = screen.getByDisplayValue("btn-1");
    fireEvent.change(idInput, { target: { value: "btn-2" } });
    expect(onChange).toHaveBeenCalledWith({ ...baseButton, id: "btn-2" });
  });

  it("edits widget label", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseButton}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    const labelInput = screen.getByDisplayValue("Click me");
    fireEvent.change(labelInput, { target: { value: "New label" } });
    expect(onChange).toHaveBeenCalledWith({ ...baseButton, label: "New label" });
  });

  it("clearing the label removes the key (deletion = omission, #89)", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseButton}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    const labelInput = screen.getByDisplayValue("Click me");
    fireEvent.change(labelInput, { target: { value: "" } });
    const changed = onChange.mock.calls[0][0];
    expect("label" in changed).toBe(false);
    expect(changed.color).toBe("#1e3a8a");
  });

  it("edits widget color", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseButton}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    const colorInput = screen.getByDisplayValue("#1e3a8a");
    fireEvent.change(colorInput, { target: { value: "#ff0000" } });
    expect(onChange).toHaveBeenCalledWith({ ...baseButton, color: "#ff0000" });
  });

  it("edits size fields", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseButton}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    const wInput = screen.getByDisplayValue("2");
    fireEvent.change(wInput, { target: { value: "3" } });
    expect(onChange).toHaveBeenCalledWith({ ...baseButton, size: [3, 1] });
  });

  it("shows delete button", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseButton}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
        onDeleteWidget={vi.fn()}
      />,
    );
    expect(screen.getByText("Delete widget")).toBeTruthy();
  });

  it("fires onDeleteWidget", () => {
    const onDelete = vi.fn();
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseButton}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
        onDeleteWidget={onDelete}
      />,
    );
    fireEvent.click(screen.getByText("Delete widget"));
    expect(onDelete).toHaveBeenCalled();
  });
});

describe("PropertiesPanel — meter widget", () => {
  afterEach(cleanup);

  it("renders meter-specific fields", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseMeter}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    expect(screen.getAllByText("Meter").length).toBeGreaterThanOrEqual(1);
    const sources = screen.getAllByText("Source");
    expect(sources.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Min")).toBeTruthy();
    expect(screen.getByText("Max")).toBeTruthy();
  });

  it("edits meter source", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseMeter}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    const sourceInput = screen.getByDisplayValue("cpu_percent");
    fireEvent.change(sourceInput, { target: { value: "mem_percent" } });
    expect(onChange).toHaveBeenCalledWith({ ...baseMeter, source: "mem_percent" });
  });

  it("edits meter min/max", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseMeter}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    const minInput = screen.getByDisplayValue("0");
    fireEvent.change(minInput, { target: { value: "10" } });
    expect(onChange).toHaveBeenCalledWith({ ...baseMeter, min: 10 });
  });
});

describe("PropertiesPanel — stats widget", () => {
  afterEach(cleanup);

  it("renders metrics editor", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseStats}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Stats")).toBeTruthy();
    expect(screen.getByText("Metrics")).toBeTruthy();
    expect(screen.getByDisplayValue("cpu_percent")).toBeTruthy();
    expect(screen.getByDisplayValue("CPU")).toBeTruthy();
  });

  it("adds a new metric", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseStats}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    const addButtons = screen.getAllByText("Add");
    const metricsAddBtn = addButtons.find((btn) => btn.closest(".prop-section")?.textContent?.includes("Metrics"));
    expect(metricsAddBtn).toBeTruthy();
    fireEvent.click(metricsAddBtn!);
    expect(onChange).toHaveBeenCalledWith({
      ...baseStats,
      metrics: [
        ...baseStats.metrics!,
        { source: "", label: null },
      ],
    });
  });

  it("removes a metric", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseStats}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    const removeButtons = screen.getAllByLabelText(/^remove metric/);
    fireEvent.click(removeButtons[0]);
    expect(onChange).toHaveBeenCalledWith({
      ...baseStats,
      metrics: [{ source: "mem_percent", label: "MEM" }],
    });
  });
});

describe("PropertiesPanel — blank widget", () => {
  afterEach(cleanup);

  it("does not show label/icon/color/action fields for blank widget", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseBlank}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Blank")).toBeTruthy();
    expect(screen.getByText("Size")).toBeTruthy();
    expect(screen.queryByText("Label")).toBeFalsy();
    expect(screen.queryByText("Color")).toBeFalsy();
    expect(screen.queryByText("Action")).toBeFalsy();
    expect(screen.queryByText("Delete widget")).toBeFalsy();
  });
});

describe("PropertiesPanel — unsupported widget", () => {
  afterEach(cleanup);

  it("shows read-only id and kind for media widget", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseUnsupported}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Reorder / delete only")).toBeTruthy();
    const idInput = screen.getByDisplayValue("media-1") as HTMLInputElement;
    expect(idInput.readOnly).toBe(true);
  });
});

describe("PropertiesPanel — opaque pass-through", () => {
  afterEach(cleanup);

  it("preserves unrendered fields on widget edit", () => {
    const onChange = vi.fn();
    const widgetWithPassThrough: Widget = {
      ...baseButton,
      macro: { steps: [{ type: "key", value: "ctrl+a" }], continue_on_error: false },
    };
    render(
      <PropertiesPanel
        widget={widgetWithPassThrough}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    const labelInput = screen.getByDisplayValue("Click me");
    fireEvent.change(labelInput, { target: { value: "Updated" } });
    const changed = onChange.mock.calls[0][0];
    expect(changed.label).toBe("Updated");
    expect(changed.macro).toEqual(widgetWithPassThrough.macro);
  });

  it("icon change opens picker and selects a new icon", () => {
    const onChange = vi.fn();
    render(
      <PropertiesPanel
        widget={baseButton}
        layoutFields={layoutFields}
        onWidgetChange={onChange}
        onLayoutFieldChange={vi.fn()}
      />,
    );
    const changeBtn = screen.getByLabelText("change icon");
    fireEvent.click(changeBtn);

    const searchInput = screen.getByPlaceholderText("Search Lucide icons…");
    fireEvent.change(searchInput, { target: { value: "pause" } });
    fireEvent.click(screen.getByLabelText("pause"));

    const changed = onChange.mock.calls[0][0];
    expect(changed.icon).toEqual({ source: "lucide", name: "pause" });
  });
});
