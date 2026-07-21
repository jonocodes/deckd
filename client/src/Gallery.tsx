import { useState } from "react";
import { DEMO_NAMES } from "./demo";

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

function Frame({ device, demo, orientation }: { device: Device; demo: string; orientation: Orientation }) {
  const [w, h] = orientation === "landscape" ? [device.h, device.w] : [device.w, device.h];
  const scale = Math.min(1, MAX_W / w, MAX_H / h);
  return (
    <figure className="frame">
      <div className="frame-box" style={{ width: w * scale, height: h * scale }}>
        <iframe
          title={`${device.label} ${orientation}`}
          src={`${import.meta.env.BASE_URL}?demo=${demo}`}
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
      </header>
      <div className="gallery-grid">
        {DEVICES.map((d) => (
          <Frame key={d.label} device={d} demo={demo} orientation={orientation} />
        ))}
      </div>
    </div>
  );
}
