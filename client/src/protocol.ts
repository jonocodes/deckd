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
export type MediaBrowserOrdering = "playing_first" | "stable";
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
export type Widget = {
  id: string;
  kind: "button" | "jogstrip" | "trackpad" | "meter" | "stats" | "media" | "mediabrowser";
  label?: string | null;
  icon?: Icon | null;
  grid: [number, number, number, number];
  color?: string | null;
  action?: Record<string, unknown> | null;
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
  /** ``mediabrowser`` knob (issue #50): how rows are presented when the
   * backend reports multiple MPRIS players. ``playing_first`` surfaces
   * the active player first; ``stable`` keeps the daemon-emitted order. */
  ordering?: MediaBrowserOrdering | null;
  /** ``mediabrowser`` knob (issue #50): whether the cell still renders
   * a placeholder row when no MPRIS player is discovered. ``show``
   * keeps the chrome's icon reachable; ``hide`` collapses the cell. */
  empty_state?: MediaBrowserEmptyState | null;
};

export type ServerLayout = {
  type: "layout";
  app: string;
  /** Optional chrome view identifier; null for focus-driven layouts. */
  view?: string | null;
  widgets: Widget[];
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
  /** Non-null when the daemon failed to load layouts; the client renders this
   * in place of the grid until the on-disk config is fixed. */
  error?: string | null;
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
/** Sent by the daemon to a non-loopback client whose ``hello`` omitted or
 * got the shared password wrong (issue #16); the socket is closed straight
 * after. The client swaps in the password prompt. */
export type ServerError = { type: "error"; reason: string };
export type ServerMessage =
  | ServerLayout
  | ServerState
  | ServerBrightness
  | ServerWidgetUpdate
  | MediaState
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

/** The wire-side id for the MPRIS chrome view (issue #51). The daemon
 * resolves ``select_view: MPRIS_VIEW_ID`` to the layout whose id is the
 * same string — today, ``layouts/mpris.yaml``. Hard-coding the literal
 * here (rather than scattered through component code) keeps the wire
 * surface and the layout loader in lockstep: a rename in either place
 * surfaces as a type error or a load failure, not silent breakage. */
export const MPRIS_VIEW_ID = "mpris";
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
  | ClientClearView;
