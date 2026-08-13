/* client/src/protocol.ts — public protocol types.
 *
 * Two layers, two sources:
 *   - Wire-protocol types (LayoutMessage, PressMessage, ...) are
 *     generated from daemon/deckd/protocol.py — see
 *     scripts/codegen_protocol_ts.py. Edit the Python side and run
 *     `just check-protocol`; the drift guard fails CI if the two
 *     diverge (#76).
 *   - Schema-layer types (Widget, Icon, ...) are hand-curated. They
 *     mirror daemon/deckd/layouts.py, which is YAML-loader concern,
 *     not wire. We keep them here for ergonomics — clients import
 *     ``Widget`` from this file — and rely on the daemon's Pydantic
 *     validators to backstop the editor's "save" path.
 *
 * Aliases at the bottom (``ServerLayout`` etc.) preserve the original
 * public surface for consumers that haven't migrated to the new names.
 */

// Wire-protocol types — re-exported from the codegen artifact.
import type {
  FocusedAppInfo,
  LayoutMessage,
  StateMessage,
  BrightnessMessage,
  WidgetUpdateMessage,
  MediaStateMessage,
  ChromeMediaMessage,
  ErrorMessage,
  MacroResultMessage,
  ConfirmRequestMessage,
  RunningWindowsMessage,
  HelloMessage,
  PressMessage,
  JogMessage,
  JogEndMessage,
  PadMessage,
  PadTapMessage,
  PadDragMessage,
  TypeMessage,
  KeyMessage,
  MediaCommandMessage,
  SelectViewMessage,
  ClearViewMessage,
  RaiseWindowMessage,
  ConfirmResponseMessage,
  WindowListEntry,
} from "./protocol.generated";
export {
  WINDOWS_VIEW_ID,
  MPRIS_VIEW_ID,
  EDITOR_VIEW_ID,
} from "./protocol.generated";
export type {
  FocusedAppInfo,
  LayoutMessage,
  StateMessage,
  BrightnessMessage,
  WidgetUpdateMessage,
  MediaStateMessage,
  ChromeMediaMessage,
  EventMessage,
  MacroResultMessage,
  ConfirmRequestMessage,
  WindowListEntry,
  RunningWindowsMessage,
  ServerMessage,
  HelloMessage,
  PressMessage,
  JogMessage,
  JogEndMessage,
  PadMessage,
  PadTapMessage,
  PadDragMessage,
  TypeMessage,
  KeyMessage,
  MediaCommandMessage,
  SelectViewMessage,
  ClearViewMessage,
  RaiseWindowMessage,
  EnableEventsMessage,
  DisableEventsMessage,
  ConfirmResponseMessage,
  MprisCommandRequest,
  ErrorMessage,
  ClientMessage,
} from "./protocol.generated";

/* Schema-layer types (hand-curated; mirror daemon/deckd/layouts.py). */

/** An icon reference: ``source`` picks a client-side renderer (e.g.
 * "lucide", "simple-icons"), ``name`` is resolved within it. The daemon
 * relays this opaquely (ADR-0006); the client owns the source registry
 * and renders a placeholder for an unknown source. */
export type Icon = { source: string; name: string };

/** One data point of a ``stats`` widget: a sensor ``source`` plus an
 * optional short caption. When ``label`` is absent the client derives one
 * from the source name (``cpu_percent`` → ``CPU``). */
export type Metric = { source: string; label?: string | null };

export type MediaHttp = { host?: string; port?: number; password_ref?: string | null };
export type MediaControl = "play" | "previous" | "next" | "volume" | "position" | "speed";
export type NowPlayingEmptyState = "show" | "hide";

/** A widget's extent in the reflow (ADR-0010). ``[w, h]`` is a column/row
 * span (default ``[1, 1]``); the literal ``"full"`` opts the widget out of
 * the flow to take the whole chrome-excluded surface. There is no position —
 * widgets pack in list order, left-to-right, wrapping down. */
export type WidgetSize = [number, number] | "full";
export type Widget = {
  id: string;
  kind: "button" | "blank" | "jogstrip" | "trackpad" | "meter" | "stats" | "media" | "nowplaying";
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
  /** ``nowplaying`` knob (issue #50): whether the cell still renders
   * a placeholder row when no MPRIS player is discovered. ``show``
   * keeps the chrome's icon reachable; ``hide`` collapses the cell.
   * Row order follows the daemon's ``row_ids`` (the session bus's
   * ``ListNames`` reply order — matching GNOME Shell — issue #58). */
  empty_state?: NowPlayingEmptyState | null;
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

/* Backwards-compat aliases — wire types under their old public names.
 *
 * The drift guard codegen emits the canonical names (``LayoutMessage``,
 * ``MediaStateMessage``, ``HelloMessage`` etc.) but consumers import the
 * older ``Server<Kind>`` and ``Client<Kind>`` names that predate #76.
 * Keep both alive so a one-shot rename isn't a breaking change.
 *
 * ``ServerLayout`` widens ``widgets`` from the wire's opaque blob to
 * the schema-layer ``Widget[]`` and ``icon`` to the typed ``Icon`` —
 * the daemon relays both opaquely, but the client renders them as
 * widgets with type-checked fields. Consumers can use the canonical
 * ``LayoutMessage`` if they want the strict wire shape. */

// ``ServerLayout`` is the historical public name for ``LayoutMessage``.
// We declare it as a standalone interface rather than an Omit+& so it
// stays structurally compatible with the wire shape (the Omit+& form
// produces an intersection that TS won't widen back to LayoutMessage).
// Consumers that need a strict-typed ``widgets`` can cast at the
// boundary; the daemon relays widgets opaquely (ADR-0006).
export interface ServerLayout {
  type: "layout";
  app?: string;
  view?: string | null;
  widgets: Widget[];
  overflow?: "clip" | "shrink-to-fit";
  jogstrip_enabled?: boolean;
  display_name?: string | null;
  theme?: string | null;
  icon?: Icon | null;
  web_app?: boolean;
  error?: string | null;
  focused_app?: FocusedAppInfo | null;
  is_default?: boolean;
}
export type ServerState = StateMessage;
export type ServerBrightness = BrightnessMessage;
export type ServerWidgetUpdate = WidgetUpdateMessage;
export type ServerChromeMedia = ChromeMediaMessage;
export type ServerError = ErrorMessage;
export type ServerMacroResult = MacroResultMessage;
export type ServerConfirmRequest = ConfirmRequestMessage;
// WindowListEntry carries an opaque ``icon`` field on the wire but the
// client renders it as a typed ``Icon``. Mirror the ServerLayout rule:
// declare the alias as a standalone interface so it stays compatible
// with the wire type at the message boundary.
export interface ServerWindowListEntry {
  window_id: string;
  label: string;
  icon?: Icon | null;
}
export type ServerRunningWindows = Omit<RunningWindowsMessage, "windows"> & {
  windows: ServerWindowListEntry[];
};
export type MediaState = MediaStateMessage;

export type ClientHello = HelloMessage;
export type ClientPress = PressMessage;
export type ClientJog = JogMessage;
export type ClientJogEnd = JogEndMessage;
export type ClientPad = PadMessage;
export type ClientPadTap = PadTapMessage;
export type ClientPadDrag = PadDragMessage;
export type ClientType = TypeMessage;
export type ClientKey = KeyMessage;
export type ClientMediaCommand = MediaCommandMessage;
export type ClientSelectView = SelectViewMessage;
export type ClientClearView = ClearViewMessage;
export type ClientRaiseWindow = RaiseWindowMessage;
export type ClientConfirmResponse = ConfirmResponseMessage;

/* Wire-to-schema coercion helpers (#76).
 *
 * ``LayoutMessage`` and friends carry ``widgets`` / ``icon`` as opaque
 * blobs (the daemon relays them, ADR-0006); the client renders them
 * against the typed ``Widget`` / ``Icon`` shapes. Centralise the cast
 * here so a single well-named helper replaces the scattered
 * ``as unknown as Widget[]`` / ``as ServerLayout`` sites — consumers
 * import one helper, and a future tightening of the wire shape has
 * exactly one place to update.
 */

/** Coerce a wire ``LayoutMessage`` to the typed-schema ``ServerLayout``
 * (Widget[] for ``widgets``, typed ``Icon`` for ``icon``). Throws nothing
 * — the wire shape is structurally compatible, so the cast is sound. */
export function wireLayoutToServer(msg: LayoutMessage): ServerLayout {
  return msg as unknown as ServerLayout;
}

/** Coerce a wire snapshot of window rows to the typed-schema
 * ``ServerWindowListEntry[]``. Same opaque-icon rationale as the
 * layout helper. */
export function wireWindowsToServer(
  windows: WindowListEntry[] | undefined,
): ServerWindowListEntry[] | undefined {
  return windows as unknown as ServerWindowListEntry[] | undefined;
}

/** Lookup a widget by id in a wire ``LayoutMessage``. Convenience so
 * ``App.tsx``-style consumers don't repeat the opaque-blob cast. */
export function widgetById(
  layout: LayoutMessage,
  id: string,
): Widget | undefined {
  return (layout.widgets as unknown as Widget[]).find((w) => w.id === id);
}