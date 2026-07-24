import type { CSSProperties } from "react";
import type { Widget } from "./protocol";
import type { MeterReading } from "./meter-store";

type Props = {
  widget: Widget;
  /** Live readings keyed by sensor source (the shared meter store map). */
  readings: Record<string, MeterReading>;
  style?: CSSProperties;
  labelScale?: number;
};

/**
 * Stats widget: a compact, bar-less cell that shows several sensor values
 * at once, one "LABEL value unit" row per metric. Deliberately simpler than
 * {@link MeterCell} — no bar, no colour grade — so it stays legible with 2–4
 * data points in a single grid cell, and takes new metrics without layout
 * churn (add another entry to the widget's ``metrics`` list).
 *
 * Each row reads its value from the shared store by the metric's ``source``.
 * A missing or stale reading renders "—" / dims the value, matching the
 * MeterCell freshness treatment so the two kinds feel consistent.
 */
export function StatsCell({ widget, readings, style, labelScale = 1 }: Props) {
  const metrics = widget.metrics ?? [];

  return (
    <div className="cell cell-stats" style={style}>
      {widget.label ? (
        <span
          className="stats-title label"
          style={{ fontSize: `calc(11px * ${labelScale})` }}
        >
          {widget.label}
        </span>
      ) : null}
      <div className="stats-rows">
        {metrics.map((m) => {
          const reading = readings[m.source] ?? null;
          const stale = !reading || reading.stale;
          const value = reading ? formatValue(reading.value) : "—";
          const unit = reading?.unit ?? "";
          return (
            <div className="stats-row" key={m.source}>
              <span className="stats-row-label">
                {m.label ?? deriveLabel(m.source)}
              </span>
              <span
                className="stats-row-value"
                style={{ color: stale ? "rgba(230, 233, 239, 0.6)" : "#e6e9ef" }}
              >
                {value}
                {unit ? <span className="stats-row-unit">{unit}</span> : null}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Compact number format: integers above 10, one decimal below (mirrors
 * MeterCell so CPU/MEM percentages read the same in both cells). */
function formatValue(v: number): string {
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 10) return Math.round(v).toString();
  return v.toFixed(1);
}

/** Derive a short caption from a source name when the metric omits ``label``:
 * ``cpu_percent`` → ``CPU``, ``mem_percent`` → ``MEM``. Falls back to the
 * whole source uppercased for single-word sources. */
function deriveLabel(source: string): string {
  const head = source.split("_")[0] || source;
  return head.toUpperCase();
}
