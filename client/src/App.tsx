import { useCallback, useState } from "react";
import { Settings as SettingsIcon } from "lucide-react";
import { PointerIcon } from "lucide-react";
import { useDeckdSocket } from "./socket";
import { ButtonGrid } from "./ButtonGrid";
import { JogStrip } from "./JogStrip";
import { ManualControl } from "./ManualControl";
import { Settings } from "./Settings";
import {
  useBottomScale,
  useContentScale,
  useJogWidth,
  useLabelScale,
  useScrollSettings,
  useTrackpadSettings,
  useWakeLockSetting,
} from "./settings-store";
import type { CSSProperties } from "react";
import { useWakeLock } from "./wake-lock";
import { getDemoLayout } from "./demo";
import { Icon } from "./Icon";
import type { JogHandle } from "./JogStrip";
import type { Icon as IconRef, ServerLayout } from "./protocol";

type View = "layout" | "trackpad" | "settings";
type SocketStatus = "connecting" | "open" | "closed";

/** Sentinel ids for the always-on chrome widgets. The daemon's pad / jog
 * paths ignore ids for emission (they're just book-keeping keys), so these
 * never collide with real layout widgets. */
const CHROME_JOG_ID = "__chrome__";
const TRACKPAD_ID = "__trackpad__";

const CHROME_JOG_HANDLE: JogHandle = { id: CHROME_JOG_ID };

const STATUS_LABEL: Record<SocketStatus, string> = {
  open: "live",
  connecting: "reconnecting",
  closed: "disconnected",
};

export function App() {
  // Demo mode (``?demo=<name>``): render a fixture layout with the socket
  // disabled, so the client can be viewed without a daemon. Null in normal
  // daemon-backed operation.
  const demoLayout = getDemoLayout();
  const [layout, setLayout] = useState<ServerLayout | null>(demoLayout);
  const [view, setView] = useState<View>("layout");
  const onLayout = useCallback((m: ServerLayout) => setLayout(m), []);
  const { status, send } = useDeckdSocket(onLayout, { enabled: !demoLayout });
  const scroll = useScrollSettings();
  const trackpad = useTrackpadSettings();
  const wakeLock = useWakeLockSetting();
  const contentScale = useContentScale();
  const jogWidth = useJogWidth();
  const bottomScale = useBottomScale();
  const labelScale = useLabelScale();
  // Hold the wake lock while the user wants it AND the socket is live;
  // a stale surface with no daemon behind it has no reason to keep the
  // screen on. Visibility is handled inside the hook.
  useWakeLock(wakeLock.enabled && status === "open");

  const press = (id: string) => send({ type: "press", id });
  const jog = (id: string, delta: number) => send({ type: "jog", id, delta });
  const jogEnd = (id: string, velocity: number) => send({ type: "jog_end", id, velocity });
  const pad = (dx: number, dy: number) => send({ type: "pad", id: TRACKPAD_ID, dx, dy });
  const padTap = (fingers: number) => send({ type: "pad_tap", id: TRACKPAD_ID, fingers });
  const padDrag = (state: "start" | "end") => send({ type: "pad_drag", id: TRACKPAD_ID, state });
  const typeText = (text: string) => send({ type: "type", text });
  const keyCombo = (combo: string) => send({ type: "key", combo });

  const jogstripEnabled = layout?.jogstrip_enabled ?? true;
  const statusLabel = STATUS_LABEL[status];

  // Chrome app-identity badge (ADR-0007): the daemon relays an
  // optional ``display_name`` / ``theme`` / ``icon`` per layout; the
  // client renders a branded pill in the always-on bottom strip from
  // them. The chrome keeps working with no schema present: an absent
  // display_name falls back to the raw match token (``app``), and an
  // absent theme leaves the badge on the default chrome treatment. A
  // layout declaring neither an icon nor a theme renders the chrome
  // unchanged (bold text, no pill) so existing layouts look identical.
  const appName = layout ? layout.display_name?.trim() || layout.app : "deckd";
  const appTheme = layout?.theme?.trim() || null;
  const appIcon: IconRef | null = layout?.icon ?? null;
  const hasBadge = appTheme !== null || appIcon !== null;
  const badgeClass = hasBadge ? `app-badge${appTheme ? " app-badge-themed" : ""}` : "app-name";
  const bottomVars = {
    "--bottom-scale": bottomScale.scale,
    ...(appTheme ? { "--badge-theme": appTheme } : {}),
  } as CSSProperties;

  return (
    <div className="app">
      <div className="chrome-page">
        {/* The content-scale var is set here on the layout area only, so grid
            content (buttons + in-grid jogstrip) scales while the persistent
            chrome — the sibling jogstrip and the bottom bar — stays fixed. */}
        <main
          className="surface"
          style={
            {
              "--content-scale": contentScale.scale,
              "--label-scale": labelScale.scale,
            } as CSSProperties
          }
        >
          {view === "trackpad" ? (
            <ManualControl
              onPad={pad}
              onTap={padTap}
              onDrag={padDrag}
              onType={typeText}
              onKey={keyCombo}
              sensitivity={trackpad.sensitivity}
            />
          ) : view === "settings" ? (
            <Settings
              layout={layout}
              status={status}
              scrollScale={scroll.scale}
              scrollInvert={scroll.invert}
              onScrollScaleChange={scroll.setScale}
              onScrollInvertChange={scroll.setInvert}
              trackpadSensitivity={trackpad.sensitivity}
              onTrackpadSensitivityChange={trackpad.setSensitivity}
              wakeLockEnabled={wakeLock.enabled}
              onWakeLockChange={wakeLock.setEnabled}
              contentScale={contentScale.scale}
              onContentScaleChange={contentScale.setScale}
              jogWidth={jogWidth.width}
              onJogWidthChange={jogWidth.setWidth}
              bottomScale={bottomScale.scale}
              onBottomScaleChange={bottomScale.setScale}
              labelScale={labelScale.scale}
              onLabelScaleChange={labelScale.setScale}
            />
          ) : layout?.error ? (
            <div className="layout-error" role="alert">
              <span className="layout-error-title">Layout error</span>
              <pre className="layout-error-body">{layout.error}</pre>
            </div>
          ) : layout ? (
            <ButtonGrid
              widgets={layout.widgets}
              onPress={press}
              onJog={jog}
              onJogEnd={jogEnd}
              scrollScale={scroll.scale}
              scrollInvert={scroll.invert}
            />
          ) : (
            <div className="empty">waiting for daemon…</div>
          )}
        </main>
        {jogstripEnabled && (
          <aside
            className="chrome-jogstrip"
            style={{ "--jog-width": jogWidth.width } as CSSProperties}
          >
            <JogStrip
              widget={CHROME_JOG_HANDLE}
              variant="chrome"
              scale={scroll.scale}
              invert={scroll.invert}
              onJog={jog}
              onJogEnd={jogEnd}
            />
          </aside>
        )}
      </div>
      <footer className="chrome-bottom" style={bottomVars}>
        <span className={badgeClass}>
          {appIcon ? <Icon icon={appIcon} className="app-badge-icon" /> : null}
          <span className="app-badge-name">{appName}</span>
        </span>
        <span className={`connection connection-${status}`}>
          <span className="connection-dot" />
          <span className="connection-label">{statusLabel}</span>
        </span>
        <button
          className={`chrome-btn${view === "trackpad" ? " chrome-btn-active" : ""}`}
          onPointerDown={() => setView(view === "trackpad" ? "layout" : "trackpad")}
        >
          <PointerIcon size={18} />
        </button>
        <button
          className={`chrome-btn${view === "settings" ? " chrome-btn-active" : ""}`}
          aria-label="settings"
          onPointerDown={() => setView(view === "settings" ? "layout" : "settings")}
        >
          <SettingsIcon size={18} />
        </button>
      </footer>
    </div>
  );
}
