import { useState } from "react";
import type { CSSProperties } from "react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { Icon } from "./Icon";
import type { MediaReading } from "./media-store";
import type { Widget } from "./protocol";

type Props = {
  widget: Widget;
  state: MediaReading | null;
  style?: CSSProperties;
  onPress: (id: string) => void;
  onCommand: (id: string, command: "volume" | "seek" | "rate", value: number) => void;
};

// Fallback shown in the art slot when the current item has no cover art (or
// it fails to load): the VLC brand logo (Simple Icons).
const ART_ICON = { source: "simple-icons" as const, name: "vlcmediaplayer" };

/** The album-art slot. When the daemon reports an ``art_token`` we point an
 * <img> at its art proxy (``/media/<id>/art``), cache-busted by the token so
 * it refetches only when the track changes; anything missing/broken falls
 * back to the VLC cone. */
function MediaArt({ widgetId, token }: { widgetId: string; token: string | null | undefined }) {
  const [failedToken, setFailedToken] = useState<string | null>(null);
  if (!token || failedToken === token) {
    return <Icon icon={ART_ICON} className="media-art-icon" />;
  }
  return (
    <img
      className="media-art-img"
      alt=""
      src={`/media/${encodeURIComponent(widgetId)}/art?token=${encodeURIComponent(token)}`}
      onError={() => setFailedToken(token)}
    />
  );
}

export function MediaCell({ widget, state, style, onPress, onCommand }: Props) {
  const controls = widget.controls ?? ["play", "volume", "position"];
  const duration = state?.duration ?? 0;
  const position = state?.position ?? 0;
  const unavailable = !state?.available || state.stale;
  return (
    <div className={`cell cell-media${unavailable ? " cell-media-unavailable" : ""}`} style={style}>
      <div className="media-inner">
        <div className="media-art" aria-hidden>
          <MediaArt widgetId={widget.id} token={state?.art_token} />
        </div>
        <div className="media-body">
          <div className="media-meta">
            <div className="media-title">{state?.title ?? "—"}</div>
            <div className="media-subtitle">{state?.artist ?? state?.album ?? "—"}</div>
          </div>
          {controls.includes("position") ? (
            <label className="media-range media-range-position">
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
          {controls.includes("play") ? (
            <div className="media-transport">
              {controls.includes("previous") ? (
                <button
                  className="media-skip"
                  aria-label="Previous"
                  onPointerDown={() => onPress(`${widget.id}:previous`)}
                >
                  <SkipBack fill="currentColor" />
                </button>
              ) : null}
              <button
                className="media-play"
                aria-label={state?.playing ? "Pause" : "Play"}
                onPointerDown={() => onPress(widget.id)}
              >
                {state?.playing ? <Pause fill="currentColor" /> : <Play fill="currentColor" />}
              </button>
              {controls.includes("next") ? (
                <button
                  className="media-skip"
                  aria-label="Next"
                  onPointerDown={() => onPress(`${widget.id}:next`)}
                >
                  <SkipForward fill="currentColor" />
                </button>
              ) : null}
            </div>
          ) : null}
          {controls.includes("volume") ? (
            <label className="media-range media-range-volume">
              <span>Vol</span>
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
      </div>
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
