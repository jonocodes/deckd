/** An icon reference: ``source`` picks a client-side renderer (e.g.
 * "lucide", "simple-icons"), ``name`` is resolved within it. The daemon
 * relays this opaquely (ADR-0006); the client owns the source registry and
 * renders a placeholder for an unknown source. */
export type Icon = { source: string; name: string };

export type Widget = {
  id: string;
  kind: "button" | "jogstrip" | "trackpad";
  label?: string | null;
  icon?: Icon | null;
  grid: [number, number, number, number];
  /** Optional CSS colour string; applied as the button's background. */
  color?: string | null;
  action?: Record<string, unknown> | null;
};

export type ServerLayout = {
  type: "layout";
  app: string;
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
export type ServerMessage = ServerLayout | ServerState | ServerBrightness;

export type ClientHello = { type: "hello"; client: "web"; token?: string };
export type ClientPress = { type: "press"; id: string };
export type ClientJog = { type: "jog"; id: string; delta: number };
export type ClientJogEnd = { type: "jog_end"; id: string; velocity: number };
export type ClientPad = { type: "pad"; id: string; dx: number; dy: number };
export type ClientPadTap = { type: "pad_tap"; id: string; fingers: number };
export type ClientPadDrag = { type: "pad_drag"; id: string; state: "start" | "end" };
export type ClientType = { type: "type"; text: string };
export type ClientKey = { type: "key"; combo: string };
export type ClientMessage =
  | ClientHello
  | ClientPress
  | ClientJog
  | ClientJogEnd
  | ClientPad
  | ClientPadTap
  | ClientPadDrag
  | ClientType
  | ClientKey;
