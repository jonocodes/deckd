import { useCallback, useEffect, useMemo, useState } from "react";
import { Settings as SettingsIcon } from "lucide-react";
import { Music as MusicIcon, PointerIcon } from "lucide-react";
import { useDeckdSocket } from "./socket";
import { ButtonGrid } from "./ButtonGrid";
import { JogStrip } from "./JogStrip";
import { ManualControl } from "./ManualControl";
import { MediaBrowserCell } from "./MediaBrowserCell";
import { Tooltip } from "./Tooltip";
import { PasswordGate } from "./PasswordGate";
import { Settings } from "./Settings";
import { useMeterStore } from "./meter-store";
import { useMediaStore } from "./media-store";
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
import { getDemoLayout, getDemoView, MEDIA_DEMO_STATES, MPRIS_DEMO_STATES } from "./demo";
import { Icon } from "./Icon";
import type { JogHandle } from "./JogStrip";
import type { Icon as IconRef, ServerChromeMedia, ServerLayout } from "./protocol";
import { MPRIS_VIEW_ID } from "./protocol";

type View = "layout" | "trackpad" | "settings" | "mediabrowser";
type SocketStatus = "connecting" | "open" | "closed" | "unauthorized";

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
  unauthorized: "locked",
};

export function App() {
  // Demo mode (``?demo=<name>``): render a fixture layout with the socket
  // disabled, so the client can be viewed without a daemon. Null in normal
  // daemon-backed operation.
  const demoLayout = getDemoLayout();
  const [layout, setLayout] = useState<ServerLayout | null>(demoLayout);
  // A view demo (``?demo=settings`` / ``?demo=trackpad``) opens straight into
  // that chrome view; otherwise start on the layout grid.
  const [view, setView] = useState<View>(getDemoView);
  const onLayout = useCallback((m: ServerLayout) => setLayout(m), []);
  // Track every sensor source the active layout references (from ``meter``
  // widgets and each ``stats`` widget's metrics) so the meter store can drop
  // readings that are no longer on screen — without this, a source would
  // keep its last reading in memory forever, and a layout switch that hides
  // meters would still remember them across reloads.
  const activeMeterSources = useMemo(() => {
    const sources = new Set<string>();
    if (layout) {
      for (const w of layout.widgets) {
        if (w.kind === "meter" && w.source) sources.add(w.source);
        if (w.kind === "stats" && w.metrics) {
          for (const m of w.metrics) if (m.source) sources.add(m.source);
        }
      }
    }
    return sources;
  }, [layout]);
  const meter = useMeterStore(activeMeterSources);
  const activeMediaIds = useMemo(() => new Set((layout?.widgets ?? []).filter((w) => w.kind === "media").map((w) => w.id)), [layout]);
  // Mediabrowser rows arrive with ids of the form ``mpris.<suffix>`` —
  // the daemon enumerates them at runtime, so the client can't list
  // them up front. The media store accepts a set of prefixes alongside
  // the exact-id set; adding the bus-prefix here keeps the rows
  // visible to the browser cell without leaking the VLC media widget's
  // id into the browser.
  const activeMediaPrefixes = useMemo(
    () => new Set((layout?.widgets ?? []).filter((w) => w.kind === "mediabrowser").map(() => "mpris.")),
    [layout],
  );
  // The single mediabrowser widget in the active layout is the
  // configuration source for the chrome view; the chrome view has
  // nowhere else to learn about ``empty_state``. Hoist the lookup out
  // of the render path so the JSX stays declarative.
  const browserWidget = useMemo(
    () => (layout?.widgets ?? []).find((w) => w.kind === "mediabrowser") ?? null,
    [layout],
  );
  const media = useMediaStore(activeMediaIds, activeMediaPrefixes);
  // Pull out the store's ``onUpdate`` (a stable useCallback) and feed
  // widget_update frames straight to it. Depending on the whole ``meter``
  // object instead would be a bug: it gets a fresh identity on every render
  // (and on every 1Hz readings push), so any effect keyed on it — notably the
  // socket effect below — would re-fire and tear down + reconnect the
  // WebSocket in a tight loop. The connection would never stay open long
  // enough to authenticate, so the password gate would never show.
  const pushReading = meter.onUpdate;
  const onWidgetUpdate = pushReading;
  const onMediaState = media.onUpdate;
  // Chrome media icon passive playback indicator (issue #47). The
  // daemon pushes a ``chrome_media`` frame on event-type transitions
  // (NameOwnerChanged registration transitions and PlaybackStatus
  // boundary crossings) plus a snapshot on connect; we mirror the
  // latest snapshot in state and apply a ``chrome-btn-playing``
  // class on the media icon when ``playing`` flips true. The default
  // outlined state holds until the first frame arrives — matches the
  // daemon's "no players" default on a fresh session.
  const [chromeMedia, setChromeMedia] = useState<ServerChromeMedia | null>(null);
  const onChromeMedia = useCallback((m: ServerChromeMedia) => setChromeMedia(m), []);
  // Demo mode has no socket, so seed the media store once on mount with the
  // fixture readings — otherwise a media widget renders as "unavailable".
  const isDemo = demoLayout !== null;
  useEffect(() => {
    if (!isDemo) return;
    for (const state of MEDIA_DEMO_STATES) onMediaState(state);
    // The mpris demo seeds the same MPRIS rows the daemon would
    // push; the browser cell filters to ``mpris.*`` ids so the VLC
    // fixture doesn't leak into the browser.
    for (const state of MPRIS_DEMO_STATES) onMediaState(state);
  }, [isDemo, onMediaState]);
  const { status, send, authenticate, deauthenticate, hasPassword } =
    useDeckdSocket(onLayout, onWidgetUpdate, onMediaState, onChromeMedia, { enabled: !demoLayout });
  // Track whether we've already handed the socket a password this session, so
  const [attemptedAuth, setAttemptedAuth] = useState(false);
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
  const mediaCommand = (id: string, command: "volume" | "seek" | "rate", value: number) => send({ type: "media_command", id, command, value });
  // Mediabrowser per-row transport (issue #54): the browser sends
  // three value-less commands — ``play-pause`` / ``next`` / ``previous``
  // — keyed by the row's ``mpris.<suffix>`` id. The server routes the
  // ``mpris.`` prefix to the MPRIS backend and the rest of the
  // ``media_command`` family keeps going to the VLC path. This
  // callback is the only thing the browser cell needs to know about
  // the wire surface.
  const browserCommand = (id: string, command: "play-pause" | "next" | "previous") =>
    send({ type: "media_command", id, command });
  // Chrome view toggle (issue #51): the media icon mirrors the existing
  // trackpad / settings buttons. When opened it sends ``select_view``
  // so the daemon pushes the mpris layout; when closed it sends
  // ``clear_view`` so the daemon reverts to the focused-app layout.
  // The icon does not auto-close when the user picks another chrome view
  // (settings, trackpad) — that's intentional, mirroring how the
  // existing buttons don't reset each other, and keeps the daemon-side
  // view pinned across a brief settings detour.
  const toggleMediaBrowser = () => {
    if (view === "mediabrowser") {
      setView("layout");
      send({ type: "clear_view" });
    } else {
      setView("mediabrowser");
      send({ type: "select_view", view: MPRIS_VIEW_ID });
    }
  };

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

  if (status === "unauthorized") {
    return (
      <PasswordGate
        retry={attemptedAuth}
        onSubmit={(password) => {
          setAttemptedAuth(true);
          authenticate(password);
        }}
      />
    );
  }

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
          ) : view === "mediabrowser" ? (
            // Per-row MPRIS browser (issue #53). The cell filters the
            // shared media cache down to ``mpris.*`` ids in the order
            // the daemon reports them (session bus ``ListNames``
            // reply — matching GNOME Shell, issue #58), and gates the
            // prev/next transport on each row's capabilities. The
            // single mediabrowser widget in the active layout is the
            // configuration source; ``null`` falls back to the legacy
            // "no players" placeholder so the chrome view still
            // renders something when the daemon hasn't pushed a
            // mediabrowser layout (e.g. a transient race during a
            // view switch).
            <div className="mediabrowser" role="region" aria-label="media browser">
              {browserWidget ? (
                <MediaBrowserCell
                  widget={browserWidget}
                  states={media.states}
                  onCommand={browserCommand}
                />
              ) : (
                <div className="mediabrowser-empty">No media players detected</div>
              )}
            </div>
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
              canDeauthenticate={hasPassword}
              onDeauthenticate={() => {
                setAttemptedAuth(false);
                setView("layout");
                deauthenticate();
              }}
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
              meterReadings={meter.readings ?? undefined}
              mediaStates={media.states}
              onMediaCommand={mediaCommand}
              labelScale={labelScale.scale}
            />
          ) : (
            <div className="empty">waiting for daemon…</div>
          )}
        </main>
        {jogstripEnabled && view !== "settings" && view !== "mediabrowser" && (
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
        <Tooltip label="manual control">
          <button
            className={`chrome-btn${view === "trackpad" ? " chrome-btn-active" : ""}`}
            aria-label="manual control"
            onPointerDown={() => setView(view === "trackpad" ? "layout" : "trackpad")}
          >
            <PointerIcon size={18} />
          </button>
        </Tooltip>
        <Tooltip label="media browser">
          <button
            className={`chrome-btn${view === "mediabrowser" ? " chrome-btn-active" : ""}${chromeMedia?.playing ? " chrome-btn-playing" : ""}`}
            aria-label="media browser"
            onPointerDown={toggleMediaBrowser}
          >
            <MusicIcon size={18} />
          </button>
        </Tooltip>
        <Tooltip label="settings">
          <button
            className={`chrome-btn${view === "settings" ? " chrome-btn-active" : ""}`}
            aria-label="settings"
            onPointerDown={() => setView(view === "settings" ? "layout" : "settings")}
          >
            <SettingsIcon size={18} />
          </button>
        </Tooltip>
      </footer>
    </div>
  );
}
