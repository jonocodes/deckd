import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { StatsCell } from "./StatsCell";
import type { Widget } from "./protocol";
import type { MeterReading } from "./meter-store";

const SYSTEM_WIDGET: Widget = {
  id: "system",
  kind: "stats",
  label: "System",
  metrics: [
    { source: "cpu_percent", label: "CPU" },
    { source: "mem_percent" }, // label omitted -> derived
  ],
};

function renderStats(readings: Record<string, MeterReading>) {
  return render(<StatsCell widget={SYSTEM_WIDGET} readings={readings} />);
}

describe("StatsCell", () => {
  afterEach(cleanup);

  it("renders one row per metric with live values and units", () => {
    renderStats({
      cpu_percent: { value: 58, unit: "%", stale: false },
      mem_percent: { value: 41, unit: "%", stale: false },
    });
    expect(screen.getByText("58")).not.toBeNull();
    expect(screen.getByText("41")).not.toBeNull();
    expect(screen.getByText("CPU")).not.toBeNull();
  });

  it("derives a label from the source when none is given", () => {
    renderStats({ mem_percent: { value: 41, unit: "%", stale: false } });
    // mem_percent -> "MEM"
    expect(screen.getByText("MEM")).not.toBeNull();
  });

  it("shows the em-dash placeholder for a source with no reading", () => {
    renderStats({ cpu_percent: { value: 58, unit: "%", stale: false } });
    // mem row has no reading yet
    expect(screen.getByText("—")).not.toBeNull();
  });

  it("reads each metric from the shared store by source, not widget id", () => {
    // The widget id is "system"; values must resolve via the metric
    // sources, never the widget id — regression guard for the
    // source-keyed store.
    renderStats({
      system: { value: 999, unit: "x", stale: false }, // must be ignored
      cpu_percent: { value: 58, unit: "%", stale: false },
      mem_percent: { value: 41, unit: "%", stale: false },
    });
    expect(screen.queryByText("999")).toBeNull();
    expect(screen.getByText("58")).not.toBeNull();
    expect(screen.getByText("41")).not.toBeNull();
  });
});
