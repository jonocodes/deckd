import { useState } from "react";
import { DEMO_NAMES } from "./demo";
import {
  CELL_SIZE_MIN,
  CELL_SIZE_MAX,
  CELL_SIZE_DEFAULT,
  CELL_SIZE_STEP,
} from "./settings-store";

/** Dev-only responsive gallery. Renders the real client (via ``?demo=``) in
 * a set of device-sized iframes side by side, so a layout can be eyeballed
 * across phone / tablet sizes and orientations without a daemon. Not part of
 * the production build — served by ``vite dev`` at ``/gallery.html``. */

type Device = { label: string; w: number; h: number };

// Portrait base dimensions (CSS px); landscape swaps w/h.
const DEVICES: Device[] = [
  { label: "Phone", w: 390, h: 844 },
  { label: "Large phone", w: 430, h: 932 },
  { label: '7" tablet', w: 600, h: 1024 },
  { label: '10" tablet', w: 834, h: 1194 },
];

// Scale each frame down to fit a legible tile while the content still renders
// at its true device pixel size (so orientation / breakpoints behave for real).
const MAX_W = 460;
const MAX_H = 360;

type Orientation = "landscape" | "portrait";

function Frame({
  device,
  demo,
  orientation,
  keyHints,
  cellSize,
}: {
  device: Device;
  demo: string;
  orientation: Orientation;
  keyHints: boolean;
  cellSize: number;
}) {
  const [w, h] = orientation === "landscape" ? [device.h, device.w] : [device.w, device.h];
  const scale = Math.min(1, MAX_W / w, MAX_H / h);
  const params = new URLSearchParams({ demo });
  if (keyHints) params.set("showKeyHints", "1");
  params.set("cellSize", String(cellSize));
  const src = `${import.meta.env.BASE_URL}?${params}`;
  return (
    <figure className="frame">
      <div className="frame-box" style={{ width: w * scale, height: h * scale }}>
        <iframe
          title={`${device.label} ${orientation}`}
          src={src}
          style={{
            width: w,
            height: h,
            border: "0",
            transform: `scale(${scale})`,
            transformOrigin: "top left",
          }}
        />
      </div>
      <figcaption>
        {device.label} · {w}×{h}
      </figcaption>
    </figure>
  );
}

export function Gallery() {
  const [demo, setDemo] = useState(DEMO_NAMES[0] ?? "firefox");
  const [orientation, setOrientation] = useState<Orientation>("landscape");
  const [keyHints, setKeyHints] = useState(false);
  const [cellSize, setCellSize] = useState(CELL_SIZE_DEFAULT);

  return (
    <div className="gallery">
      <header className="gallery-bar">
        <span className="gallery-title">deckd · responsive gallery</span>
        <div className="gallery-group">
          {DEMO_NAMES.map((name) => (
            <button
              key={name}
              className={`gallery-btn${name === demo ? " on" : ""}`}
              onClick={() => setDemo(name)}
            >
              {name}
            </button>
          ))}
        </div>
        <div className="gallery-group">
          {(["landscape", "portrait"] as Orientation[]).map((o) => (
            <button
              key={o}
              className={`gallery-btn${o === orientation ? " on" : ""}`}
              onClick={() => setOrientation(o)}
            >
              {o}
            </button>
          ))}
        </div>
        <div className="gallery-group">
          <button
            className={`gallery-btn${keyHints ? " on" : ""}`}
            onClick={() => setKeyHints((v) => !v)}
          >
            key hints
          </button>
        </div>
      </header>
      <div className="gallery-band">
        <div className="gallery-band-control">
          <label htmlFor="gallery-cell-size">
            cell size <span className="gallery-band-val">{cellSize}px</span>
          </label>
          <input
            id="gallery-cell-size"
            type="range"
            min={CELL_SIZE_MIN}
            max={CELL_SIZE_MAX}
            step={CELL_SIZE_STEP}
            value={cellSize}
            onChange={(e) => setCellSize(Number(e.target.value))}
          />
        </div>
      </div>
      <div className="gallery-grid">
        {DEVICES.map((d) => (
          <Frame
            key={d.label}
            device={d}
            demo={demo}
            orientation={orientation}
            keyHints={keyHints}
            cellSize={cellSize}
          />
        ))}
      </div>
    </div>
  );
}
