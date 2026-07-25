import type { CSSProperties } from "react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import type { MediaReading } from "./media-store";
import type { Widget } from "./protocol";

type Props = {
  widget: Widget;
  state: MediaReading | null;
  style?: CSSProperties;
  onPress: (id: string) => void;
  onCommand: (id: string, command: "volume" | "seek" | "rate", value: number) => void;
};

export function MediaCell({ widget, state, style, onPress, onCommand }: Props) {
  const controls = widget.controls ?? ["play", "volume", "position"];
  const duration = state?.duration ?? 0;
  const position = state?.position ?? 0;
  const unavailable = !state?.available || state.stale;
  return (
    <div className={`cell cell-media${unavailable ? " cell-media-unavailable" : ""}`} style={style}>
      <div className="media-title">{state?.title ?? "—"}</div>
      <div className="media-subtitle">{state?.artist ?? state?.album ?? "—"}</div>
      {controls.includes("play") ? (
        <div className="media-transport">
          {controls.includes("previous") ? (
            <button
              className="media-skip"
              aria-label="Previous"
              onPointerDown={() => onPress(`${widget.id}:previous`)}
            >
              <SkipBack fill="#c0c0c0" />
            </button>
          ) : null}
          <button
            className="media-play"
            aria-label={state?.playing ? "Pause" : "Play"}
            onPointerDown={() => onPress(widget.id)}
          >
            {state?.playing ? <Pause fill="#c0c0c0" /> : <Play fill="#c0c0c0" />}
          </button>
          {controls.includes("next") ? (
            <button
              className="media-skip"
              aria-label="Next"
              onPointerDown={() => onPress(`${widget.id}:next`)}
            >
              <SkipForward fill="#c0c0c0" />
            </button>
          ) : null}
        </div>
      ) : null}
      {controls.includes("position") ? (
        <label className="media-range">
          <span>{formatTime(position)}</span>
          <input
            aria-label="Playback position"
            type="range"
            min={0}
            max={duration || 1}
            value={Math.min(position, duration || 1)}
            onChange={(event) => onCommand(widget.id, "seek", Number(event.target.value))}
            disabled={unavailable || !duration}
          />
          <span>{formatTime(duration)}</span>
        </label>
      ) : null}
      {controls.includes("volume") ? (
        <label className="media-range">
          <span>Volume</span>
          <input
            aria-label="Volume"
            className="media-volume-input"
            type="range"
            min={0}
            max={100}
            value={state?.volume ?? 0}
            onChange={(event) => onCommand(widget.id, "volume", Number(event.target.value))}
            disabled={unavailable}
          />
        </label>
      ) : null}
      {controls.includes("speed") ? (
        <label className="media-speed">
          <span>Speed</span>
          <button
            type="button"
            aria-label="Decrease speed"
            onPointerDown={() =>
              onCommand(widget.id, "rate", Math.max(0.25, (state?.rate ?? 1) - 0.25))
            }
          >
            −
          </button>
          <output>{(state?.rate ?? 1).toFixed(2)}×</output>
          <button
            type="button"
            aria-label="Increase speed"
            onPointerDown={() => onCommand(widget.id, "rate", (state?.rate ?? 1) + 0.25)}
          >
            +
          </button>
        </label>
      ) : null}
    </div>
  );
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60)
    .toString()
    .padStart(2, "0");
  return `${minutes}:${remainder}`;
}
