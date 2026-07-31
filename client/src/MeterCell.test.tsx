import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MeterCell } from "./MeterCell";
import type { Widget } from "./protocol";
import type { MeterReading } from "./meter-store";

const CPU_WIDGET: Widget = {
  id: "cpu_percent",
  kind: "meter",
  label: "CPU",
  source: "cpu_percent",
  min: 0,
  max: 100,
};

function renderMeter(widget: Widget, reading: MeterReading | null) {
  return render(<MeterCell widget={widget} reading={reading} />);
}

describe("MeterCell", () => {
  afterEach(cleanup);

  it("renders the empty-state when no reading has arrived", () => {
    renderMeter(CPU_WIDGET, null);
    // Em-dash placeholder so the cell still has a number-shaped mark
    // to align against — better than a blank space when neighbouring
    // buttons are showing live values.
    expect(screen.getByText("—")).not.toBeNull();
    expect(screen.getByRole("meter")).not.toBeNull();
  });

  it("renders the value and unit when a reading is present", () => {
    renderMeter(CPU_WIDGET, {
      value: 58,
      unit: "°C",
      stale: false,
    });
    expect(screen.getByText("58")).not.toBeNull();
    expect(screen.getByText("°C")).not.toBeNull();
  });

  it("formats sub-10 values with one decimal place", () => {
    renderMeter(CPU_WIDGET, {
      value: 8.4,
      unit: "°C",
      stale: false,
    });
    expect(screen.getByText("8.4")).not.toBeNull();
  });

  it("clamps the bar fill fraction to 0..1", () => {
    // Above max: bar should be 100% (clamped). Below min: 0%.
    renderMeter(CPU_WIDGET, { value: 150, unit: "°C", stale: false });
    const fill = screen.getByRole("meter").firstElementChild as HTMLElement;
    expect(fill.style.width).toBe("100%");

    cleanup();

    renderMeter(CPU_WIDGET, { value: -20, unit: "°C", stale: false });
    const fill2 = screen.getByRole("meter").firstElementChild as HTMLElement;
    expect(fill2.style.width).toBe("0%");
  });

  it("marks the cell stale when the reading is stale", () => {
    renderMeter(CPU_WIDGET, { value: 42, unit: "°C", stale: true });
    const meter = screen.getByRole("meter");
    // Walk up to the parent cell so the test is robust to refactors
    // of the inner DOM (the class lives on the .cell-meter element).
    const cell = meter.closest(".cell-meter") as HTMLElement;
    expect(cell.classList.contains("cell-meter-stale")).toBe(true);
  });

  it("does not crash when min == max", () => {
    // Defensive guard against a malformed fixture or future config
    // that drops the min/max pair. Should render something — not
    // throw.
    const bad: Widget = { ...CPU_WIDGET, min: 50, max: 50 };
    expect(() => renderMeter(bad, { value: 50, unit: "°C", stale: false })).not.toThrow();
  });

  it("falls back to a 0..100 range when min/max are unset", () => {
    const openRange: Widget = {
      ...CPU_WIDGET,
      min: undefined,
      max: undefined,
    };
    renderMeter(openRange, { value: 50, unit: "°C", stale: false });
    const fill = screen.getByRole("meter").firstElementChild as HTMLElement;
    expect(fill.style.width).toBe("50%");
  });
});
