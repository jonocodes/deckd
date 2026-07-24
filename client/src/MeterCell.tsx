import { useMemo } from "react";
import type { CSSProperties } from "react";
import type { Widget } from "./protocol";
import { Icon } from "./Icon";
import type { MeterReading } from "./meter-store";

type Props = {
  widget: Widget;
  reading: MeterReading | null;
  style?: CSSProperties;
  labelScale?: number;
};

/**
 * Meter widget: a live numeric readout with a horizontal bar that fills
 * proportionally to the value. Color-graded cool → hot (blue → green →
 * yellow → red) so a glance at the bar conveys "is this OK or not" before
 * the user reads the number.
 *
 * Rendering rules:
 *   * No reading yet (or stale with no prior value): bar at 0%, value
 *     rendered as "—". Stays visible — the bar position holds the last
 *     known value, only the freshness label changes.
 *   * Reading stale with a prior value: bar stays where it was,
 *     numeric readout dimmed to 60% so it's clear the value is
 *     historical, not live.
 *   * Value out of range: bar clamps to its end. We intentionally do
 *     NOT cap the underlying reading — the daemon still receives the
 *     true value and the user sees the actual number; only the bar's
 *     visual fill clamps.
 *   * Color grade: derived from the bar's current fill fraction
 *     (clamped 0..1) so a meter with a non-default min/max still
 *     paints the same colors at the same fraction. The default
 *     0..100 °C range maps fraction 0.0 = cold, 1.0 = red; the same
 *     colors map to the same fractions for any other range.
 */
export function MeterCell({ widget, reading, style, labelScale = 1 }: Props) {
  const min = widget.min ?? 0;
  const max = widget.max ?? 100;
  // Range validity guard — the daemon validates this in layouts.py,
  // but a malformed fixture shouldn't crash rendering. If max <= min,
  // collapse the bar to 0% rather than NaN-ing the fill calculation.
  const range = max > min ? max - min : 1;
  const rawFraction = reading ? (reading.value - min) / range : 0;
  const fraction = Math.max(0, Math.min(1, rawFraction));

  // Color gradient sampled at three points so the CSS linear-gradient
  // interpolation stays smooth. Cool blue → green (mid) → red (full).
  // Hue/lightness tuned for the dark chrome background; saturations
  // are high enough to read as "alert" but not so high they clash with
  // themed buttons next door.
  const color = useMemo(() => interpolateMeterColor(fraction), [fraction]);

  const valueLabel = reading
    ? formatValue(reading.value)
    : "—";
  const unitLabel = reading?.unit ?? "";
  const stale = !reading || reading.stale;

  const numericStyle: CSSProperties = {
    color: stale ? "rgba(230, 233, 239, 0.6)" : "#e6e9ef",
  };

  return (
    <div
      className={`cell cell-meter${stale ? " cell-meter-stale" : ""}`}
      style={style}
    >
      {widget.icon ? (
        <Icon icon={widget.icon} className="icon" />
      ) : null}
      <div className="meter-readout">
        <span className="meter-value" style={numericStyle}>
          {valueLabel}
        </span>
        {unitLabel ? <span className="meter-unit">{unitLabel}</span> : null}
      </div>
      <div
        className="meter-bar"
        role="meter"
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={reading ? reading.value : undefined}
        aria-label={widget.label ?? widget.id}
      >
        <div
          className="meter-bar-fill"
          style={{
            width: `${fraction * 100}%`,
            background: color,
          }}
        />
      </div>
      {widget.label ? (
        <span className="meter-label label" style={{ fontSize: `calc(11px * ${labelScale})` }}>
          {widget.label}
        </span>
      ) : null}
    </div>
  );
}

function formatValue(v: number): string {
  if (!Number.isFinite(v)) return "—";
  // 0 decimals for typical 30-90 °C CPU temps; 1 decimal once we drop
  // below 10 to preserve precision. ``toFixed``-vs-``Math.round``
  // threshold is a stylistic call — picked 10 °C because that's where
  // the difference between "32" and "32.4" starts being noticeable.
  if (Math.abs(v) >= 10) return Math.round(v).toString();
  return v.toFixed(1);
}

/**
 * Map a 0..1 fill fraction to a CSS colour string along the
 * cool→warm gradient. We interpolate in HSL so the cool blue stays
 * blue rather than washing out to grey, and the warm end stays red
 * rather than going brown.
 *
 * Three stops (0.0 blue, 0.5 green, 1.0 red) split the hue range
 * evenly; saturation and lightness are held constant.
 */
function interpolateMeterColor(t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  // Stops: (hue, saturation, lightness)
  const stops: [number, number, number][] = [
    [210, 80, 55], // blue
    [140, 70, 50], // green
    [15, 85, 55], // red-orange
  ];
  if (clamped <= 0.5) {
    return mix(stops[0], stops[1], clamped / 0.5);
  }
  return mix(stops[1], stops[2], (clamped - 0.5) / 0.5);
}

function mix(
  a: [number, number, number],
  b: [number, number, number],
  t: number,
): string {
  const hue = a[0] + (b[0] - a[0]) * t;
  const sat = a[1] + (b[1] - a[1]) * t;
  const light = a[2] + (b[2] - a[2]) * t;
  return `hsl(${hue}, ${sat}%, ${light}%)`;
}
