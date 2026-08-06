import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

type Orientation = "portrait" | "landscape";

interface Shot {
  demo: string;
  label: string;
  orientation?: Orientation;
}

/** Configurable list of demo views to screenshot. Edit this to curate what
 * appears on the ``/screenshots.html`` page. Each entry renders as a phone-
 * framed iframe at 390×844. The iframe is scaled so the phone frame with
 * bezel stays within a 600 px max dimension. */
const SHOTS: Shot[] = [
  { demo: "firefox", label: "firefox", orientation: "landscape" },
  { demo: "trackpad", label: "trackpad", orientation: "landscape" },
  { demo: "meter", label: "meter", orientation: "landscape" },
  { demo: "showcase", label: "showcase", orientation: "landscape" },
  { demo: "vlc", label: "vlc" },
  { demo: "mpris", label: "now-playing", orientation: "landscape" },
];

const PHONE_W = 390;
const PHONE_H = 844;
const SCALE = 0.63;

function PhoneFrame({ label, landscape, children }: { label: string; landscape?: boolean; children?: ReactNode }) {
  return (
    <div className="shot" data-shot={label}>
      <div className={`phone-frame${landscape ? " landscape" : ""}`}>
        {!landscape && <div className="phone-notch" />}
        <div className="phone-screen">
          {children}
        </div>
      </div>
      <div className="shot-label">{label}</div>
    </div>
  );
}

function PhoneCard({ demo, label, orientation = "portrait" }: Shot) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const landscape = orientation === "landscape";

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onLoad = () => {
      const timeout = setTimeout(() => setReady(true), 800);
      return () => clearTimeout(timeout);
    };
    el.addEventListener("load", onLoad);
    return () => el.removeEventListener("load", onLoad);
  }, []);

  const src = `${import.meta.env.BASE_URL}?demo=${demo}`;
  const [w, h] = landscape ? [PHONE_H, PHONE_W] : [PHONE_W, PHONE_H];

  return (
    <PhoneFrame label={label} landscape={landscape}>
      <div style={{ width: w * SCALE, height: h * SCALE, position: "relative" }}>
        <iframe
          ref={ref}
          title={`${label} screenshot`}
          src={src}
          style={{
            width: w,
            height: h,
            border: "0",
            transform: `scale(${SCALE})`,
            transformOrigin: "top left",
            opacity: ready ? 1 : 0,
            transition: "opacity 0.3s",
          }}
        />
      </div>
    </PhoneFrame>
  );
}

export function Screenshots() {
  return (
    <div className="screenshots-page">
      {SHOTS.map((s) => (
        <PhoneCard key={`${s.demo}-${s.orientation ?? "portrait"}`} {...s} />
      ))}
    </div>
  );
}
