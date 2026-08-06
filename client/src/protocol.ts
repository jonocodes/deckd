/** An icon reference: ``source`` picks a client-side renderer (e.g.
 * "lucide", "simple-icons"), ``name`` is resolved within it. The daemon
 * relays this opaquely (ADR-0006); the client owns the source registry and
 * renders a placeholder for an unknown source. */
export type Icon = { source: string; name: string };

/** One data point of a ``stats`` widget: a sensor ``source`` plus an
 * optional short caption. When ``label`` is absent the client derives one
 * from the source name (``cpu_percent`` → ``CPU``). */
export type Metric = { source: string; label?: string | null };

export type MediaHttp = { host?: string; port?: number; password_ref?: string | null };
export type MediaControl = "play" | "previous" | "next" | "volume" | "position" | "speed";
export type MediaBrowserEmptyState = "show" | "hide";
export type MediaState = {
  type: "media_state";
  id: string;
  available: boolean;
  stale: boolean;
  playing?: boolean | null;
  position?: number | null;
  duration?: number | null;
  volume?: number | null;
  rate?: number | null;
  title?: string | null;
  artist?: string | null;
  album?: string | null;
  /** Changes when the current item's album art changes (null when none), so
   * the client can point an <img> at the daemon art proxy and cache-bust. */
  art_token?: string | null;
  /** MPRIS-only fields populated only for ``id == "mpris.<suffix>"`` rows
   * (issue #52). VLC's path leaves them ``null``. The browser uses
   * ``desktop_entry`` as a key into its app-icon registry; the two booleans
   * mirror MPRIS ``CanGoNext`` / ``CanGoPrevious`` so the browser can gate
   * the matching transport buttons. */
  desktop_entry?: string | null;
  can_go_next?: boolean | null;
  can_go_previous?: boolean | null;
  /** The player's human-readable name from the MPRIS root interface's
   * ``Identity`` (e.g. "Firefox", "VLC media player"). The browser renders
   * it as a per-row header, matching GNOME. ``null`` for the VLC path. */
  app_name?: string | null;
};
/** A widget's extent in the reflow (ADR-0010). ``[w, h]`` is a column/row
 * span (default ``[1, 1]``); the literal ``"full"`` opts the widget out of
 * the flow to take the whole chrome-excluded surface. There is no position —
 * widgets pack in list order, left-to-right, wrapping down. */
export type WidgetSize = [number, number] | "full";
export type Widget = {
  id: string;
  kind: "button" | "blank" | "jogstrip" | "trackpad" | "meter" | "stats" | "media" | "mediabrowser";
  label?: string | null;
  icon?: Icon | null;
  /** Reflow extent (ADR-0010). Absent means a ``[1, 1]`` single cell. */
  size?: WidgetSize | null;
  color?: string | null;
  action?: Record<string, unknown> | null;
  /** Macro steps: an ordered list of key/shell/dbus/delay actions that the
   * daemon executes sequentially on press (issue #68). When present,
   * ``action`` is ignored. */
  macro?: { steps: { type: string; value: string }[]; continue_on_error?: boolean } | null;
  source?: string | null;
  min?: number | null;
  max?: number | null;
  metrics?: Metric[] | null;
  controls?: MediaControl[] | null;
  media_http?: MediaHttp | null;
  previous_action?: Record<string, unknown> | null;
  next_action?: Record<string, unknown> | null;
  volume_up_action?: Record<string, unknown> | null;
  volume_down_action?: Record<string, unknown> | null;
  /** ``mediabrowser`` knob (issue #50): whether the cell still renders
   * a placeholder row when no MPRIS player is discovered. ``show``
   * keeps the chrome's icon reachable; ``hide`` collapses the cell.
   * Row order follows the daemon's ``row_ids`` (the session bus's
   * ``ListNames`` reply order — matching GNOME Shell — issue #58). */
  empty_state?: MediaBrowserEmptyState | null;
  /** Confirmation opt-in (issues #69 / #108). When ``true``, pressing
   * the widget withholds execution on the daemon; the daemon mints a
   * ``confirm_id``, sends a ``confirm_request`` to this client, and
   * only runs the action / macro on a matching ``confirm_response``
   * with ``decision: "confirm"``. Valid only on widgets that carry
   * an ``action`` or a ``macro``; the daemon emits the field on
   * every widget (`confirm: false` is the default). Optional in the
   * TS shape for the same reason ``empty_state`` is: real daemon
   * layouts always carry it, but mock / test fixtures routinely
   * omit it; consumers use ``=== true`` so an absent field falls
   * back to ``false`` at the comparison. */
  confirm?: boolean;
};

export type FocusedAppInfo = {
  app_id?: string | null;
  wm_class?: string | null;
  title?: string | null;
  is_browser: boolean;
};

export type ServerLayout = {
  type: "layout";
  app: string;
  /** Optional chrome view identifier; null for focus-driven layouts. */
  view?: string | null;
  widgets: Widget[];
  /** What happens when the defined widgets exceed the capacity the cell-size
   * band yields at the current viewport (ADR-0010). ``clip`` (default) leaves
   * trailing widgets off-surface; ``shrink-to-fit`` allows cells below the
   * band's floor so every widget fits. The one genuinely per-layout sizing
   * knob — everything else about cell size is a client-side device pref. */
  overflow?: "clip" | "shrink-to-fit";
  jogstrip_enabled: boolean;
  /** Human-readable name for the bottom-chrome app badge; falls back to
   * ``app`` (the raw match token) when null. Relayed opaquely by the
   * daemon (ADR-0007). */
  display_name?: string | null;
  /** CSS colour string the browser accepts (hex, ``hsl(...)``, named); the
   * client tints the app badge with it. Opaque relay — same rule as the
   * per-widget ``color`` (ADR-0006), applied to the chrome badge. */
  theme?: string | null;
  /** Optional brand icon rendered alongside the app name. Same
   * ``{source, name}`` dispatch widgets use (ADR-0006). */
  icon?: Icon | null;
  /** True when the layout was resolved as a web app: the focused browser's
   * window title matched a ``title:`` token. The client shows a small globe
   * on the badge. Daemon-derived, never authored in YAML. */
  web_app?: boolean;
  /** Non-null when the daemon failed to load layouts; the client renders this
   * in place of the grid until the on-disk config is fixed. */
  error?: string | null;
  /** The currently focused app's identity, populated when the daemon has a
   * focus backend. ``null`` before the first focus event. The editor's
   * new-layout creation flow (#104) uses this to prefill match tokens. */
  focused_app?: FocusedAppInfo | null;
  /** True only on a genuine focus-driven fallback to the default layout
   * (issues #116 / #123, stage 1). The client renders a ``(program)``
   * suffix alongside the layout name when set. Forced false on any
   * pinned view — demo or chrome ``select_view`` — so a pin never
   * leaks the underlying program. */
  is_default?: boolean;
};

export type ServerState = { type: "state"; locked: boolean };
export type ServerBrightness = { type: "brightness"; value: number };
/** Live value for a meter widget (issue #40). Pushed at the sensor's
 * poll cadence; the client renders the bar + numeric readout from
 * ``value`` / ``unit``. ``stale=true`` means the source could not
 * refresh — the UI keeps the last known position but stops claiming
 * the value is fresh. */
export type ServerWidgetUpdate = {
  type: "widget_update";
  id: string;
  source: string;
  value: number;
  unit: string;
  stale: boolean;
};
/** Daemon -> client push: the chrome media icon's passive playback-state
 * snapshot (issue #47). Sent on event-type transitions
 * (``NameOwnerChanged`` registration transitions and ``PlaybackStatus``
 * boundary crossings) plus a snapshot on connect. The client tints the
 * media icon when ``playing`` is true and leaves it outlined otherwise. */
export type ServerChromeMedia = {
  type: "chrome_media";
  available: boolean;
  playing: boolean;
  playing_count: number;
};
/** Sent by the daemon to a non-loopback client whose ``hello`` omitted or
 * got the shared password wrong (issue #16); the socket is closed straight
 * after. The client swaps in the password prompt. */
export type ServerError = { type: "error"; reason: string };
/** Sent by the daemon after a macro completes. ``outcome`` is ``ok`` when
 * every step ran; ``failed-at-step`` means a step failed and the macro
 * stopped (``continue_on_error`` was false, or there is no more steps).
 * ``failed_step`` is the zero-based index of the step that failed, or
 * ``null`` on success. */
export type ServerMacroResult = {
  type: "macro_result";
  id: string;
  outcome: "ok" | "failed-at-step";
  failed_step: number | null;
  error: string | null;
};
/** Daemon -> client push: ask for a confirmation before running an action
 * (issues #69 / #107). Fires on a ``confirm: true`` press instead of
 * running the action. The client renders a modal naming the widget
 * (label / icon), then sends a ``ConfirmResponse`` with its verdict.
 * ``widget_id`` lets the client look up its own display copy (label,
 * icon) from the last ``ServerLayout`` — the daemon never sends
 * command text on the wire. Unknown / expired ``confirm_id`` is a
 * silent no-op on the daemon. */
export type ServerConfirmRequest = {
  type: "confirm_request";
  confirm_id: string;
  widget_id: string;
};
export type ServerMessage =
  | ServerLayout
  | ServerState
  | ServerBrightness
  | ServerWidgetUpdate
  | MediaState
  | ServerChromeMedia
  | ServerMacroResult
  | ServerConfirmRequest
  | ServerError;

export type ClientHello = {
  type: "hello";
  client: "web";
  token?: string;
  /** Shared password for remote clients; omitted on loopback (issue #16). */
  password?: string;
  /** Demo pin from the ``?layout=<name>`` URL param: forces this session to
   * the named daemon layout regardless of host focus. Omitted when absent. */
  layout?: string;
};
export type ClientPress = { type: "press"; id: string };
export type ClientJog = { type: "jog"; id: string; delta: number };
export type ClientJogEnd = { type: "jog_end"; id: string; velocity: number };
export type ClientPad = { type: "pad"; id: string; dx: number; dy: number };
export type ClientPadTap = { type: "pad_tap"; id: string; fingers: number };
export type ClientPadDrag = { type: "pad_drag"; id: string; state: "start" | "end" };
export type ClientType = { type: "type"; text: string };
export type ClientKey = { type: "key"; combo: string };
export type ClientMediaCommand =
  | { type: "media_command"; id: string; command: "volume" | "seek" | "rate"; value: number }
  | { type: "media_command"; id: string; command: "play-pause" | "next" | "previous"; value?: null };
/** Ask the daemon to render a chrome view by name (issue #50). The name
 * resolves to a layout id; the server pushes the resolved layout with
 * ``view`` set. An unknown name pushes ``view: <name>`` with
 * ``error: "view not found"`` so the client can show the failure. */
export type ClientSelectView = { type: "select_view"; view: string };
/** Undo a previous ``select_view`` for this session only. */
export type ClientClearView = { type: "clear_view" };
/** Client -> daemon: the user's verdict on a pending ``confirm_request``
 * (issues #69 / #107). The daemon looks up the pending action by
 * ``confirm_id``: an unknown / expired / superseded token is a no-op
 * (the action never runs). ``"confirm"`` re-enters the daemon's run
 * path; ``"cancel"`` drops the pending action with no side effects.
 * A literal verb rather than a bare bool, mirroring
 * ``MediaCommandMessage``'s ``"play-pause"`` idiom. */
export type ClientConfirmResponse = {
  type: "confirm_response";
  confirm_id: string;
  decision: "confirm" | "cancel";
};

/** The wire-side id for the MPRIS chrome view (issue #51). The daemon
 * resolves ``select_view: MPRIS_VIEW_ID`` to the layout whose id is the
 * same string — today, ``layouts/mpris.yaml``. Hard-coding the literal
 * here (rather than scattered through component code) keeps the wire
 * surface and the layout loader in lockstep: a rename in either place
 * surfaces as a type error or a load failure, not silent breakage. */
export const MPRIS_VIEW_ID = "mpris";
/** The wire-side id for the editor chrome view (issue #100). Same pattern
 * as MPRIS_VIEW_ID: the client sends ``select_view: EDITOR_VIEW_ID`` and
 * the daemon pushes the editor layout. */
export const EDITOR_VIEW_ID = "editor";
export type ClientMessage =
  | ClientHello
  | ClientPress
  | ClientJog
  | ClientJogEnd
  | ClientPad
  | ClientPadTap
  | ClientPadDrag
  | ClientType
  | ClientKey
  | ClientMediaCommand
  | ClientSelectView
  | ClientClearView
  | ClientConfirmResponse;
