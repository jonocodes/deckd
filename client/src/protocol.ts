export type Widget = {
  id: string;
  kind: "button" | "jogstrip" | "trackpad";
  label?: string | null;
  icon?: string | null;
  grid: [number, number, number, number];
  action?: Record<string, unknown> | null;
};

export type ServerLayout = {
  type: "layout";
  app: string;
  widgets: Widget[];
  jogstrip_enabled: boolean;
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
export type ClientMessage = ClientHello | ClientPress | ClientJog | ClientJogEnd;
