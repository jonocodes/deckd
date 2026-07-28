# Chrome view carve-out: client-requested daemon-rendered chrome surfaces

ADR-0003 declared chrome a pure client concern — the daemon has no chrome
knowledge, the client renders the persistent bottom strip and right-side
jogstrip unchanged regardless of which layout is active. The MPRIS media
browser is the first feature that needs more: a chrome-shaped surface (a
full-bleed panel that replaces the layout area, not a grid cell) whose
state comes from the host — the session-bus MPRIS player list — and
which the client asks the daemon to render by name. This ADR records
that carve-out and the new general mechanism that supports it.

The carve-out is small in code (`select_view` / `clear_view` messages, a
`view` field on `LayoutMessage`, the `mediabrowser` widget kind) and
deliberate in scope: the chrome is still rendered by the client; the
daemon only pushes a layout the client has explicitly asked to see. A
future chrome-shaped view (a settings panel, a trackpad surface, a
clipboard viewer, anything else that wants the same affordance) plugs
in through the same mechanism.

## Decisions

### Chrome stays a client concern; the carve-out is opt-in per session

ADR-0003's core claim — the daemon hard-codes no chrome behaviour — is
preserved. The daemon does not know about the bottom strip, the right
jogstrip, the trackpad mode button, the settings button, the connection
indicator, or the new media icon. It pushes a `LayoutMessage`; the
client decides what to render around it.

The carve-out is that the client can ask the daemon to push a *specific*
layout it has reason to want, regardless of the focused app. The daemon
honours the request by switching this session to the named layout for as
long as the client holds the request. The persistent chrome frame
(bottom strip + jogstrip) is still client-rendered and never depends on
the daemon's view choice.

### `select_view` / `clear_view` are per-session, opt-in

The client->daemon `select_view` message names the view to render (the
view id is the synthetic match token the server uses to address a
chrome view, e.g. `"mpris"` for the shipped `mpris.yaml` layout). The
daemon pushes the resolved layout with `view` set to the requested name.
A follow-up `clear_view` message from the same client reverts to the
focused-app layout for that session only; other clients keep whatever
view they have selected. The view is per-session because the affordance
is per-client: one phone pinned to the browser doesn't lock a second
phone out of its own focus-driven layout.

Per-session state lives on the `Session` object (`view: str | None`).
A session that never sends `select_view` keeps the focus-driven default
forever; a session that does only sees its own view choice change. The
state is reset on disconnect (sessions are not persisted across
WebSocket close).

### `LayoutMessage` carries `view: <name> | null`

Every `LayoutMessage` now carries a `view` field set to:

- the requested name (e.g. `"mpris"`) when the client is currently pinned
  to a chrome view — focus-driven layouts *and* chrome views both
  arrive on the same message type, distinguished by the field;
- `null` when the client is following focus (no `select_view` is active).

The field is present and `null` on every push, so the client has a
stable shape to destructure. A view-resolution failure (unknown name)
keeps the focused-app widgets and rides an `error: "view not found"`
alongside them, so the chrome stays usable while the failure is
surfaced — a separate `view not found` error from a YAML `layout error`
which collapses the grid (issue #50).

### The view survives focus changes until the client clears it

A genuine (non-deckd-window) focus change re-resolves the *layout* per
ADR-0003, but a client-requested view is not a layout — it's a chrome
view the daemon re-pushes on every focus change until the client
explicitly clears it. This is the carve-out: a user who tapped the
media icon in the chrome wants the browser to stay put even if they
alt-tab to a different app. `clear_view` (or the session ending) is the
only way out.

### The `mediabrowser` widget kind

The view surfaces through a new widget kind, `mediabrowser`, declared
in YAML the same as any other widget:

```yaml
match: [mpris]
display_name: MPRIS
widgets:
  - id: browser
    kind: mediabrowser
    grid: [0, 0, 4, 2]
```

The kind is a *grid cell* the client renders when it has the view
pinned; the chrome surface (trackpad, settings, browser) is a *mode*
the client swaps into when the layout's `match` token matches the
selected view name. Both shapes share the same `LayoutMessage` — the
`view` field tells the client which mode to render. The widget kind
also has a small public schema (`empty_state`) but that lives with
the kind, not the view mechanism. Row order follows the session bus's
`ListNames` reply — matching GNOME Shell — with no per-widget knob
(issue #58).

A layout that uses `mediabrowser` also pays the bus-connect cost:
the daemon opens the session D-Bus only when at least one loaded
layout declares the kind. Users who don't enable the feature don't
pay the cost.

### The mechanism is general, not MPRIS-specific

The new mechanism — `select_view` request, `view` field on the layout
push, the per-session pin — is intentionally not bound to MPRIS. Any
future chrome-shaped surface that wants the same affordance is one
new `match: [<view-name>]` layout away, plus the chrome button on
the client side. The chrome button set is client-owned; the daemon
doesn't know which buttons exist or which view names map to which
layouts. Future views plug in without daemon or protocol changes.

## Out of scope (deferred, deliberately)

- **Passive playback-state tint on the chrome media icon** (issue
  #47). The icon is currently a static music note. A future follow-up
  will subscribe to the live MPRIS state and tint the icon while a
  player is `Playing`. The carve-out here is the *view*; the icon's
  passive state is a separate concern.
- **Multi-view chrome surfaces, per-device view state, animated
  view transitions** — all plausible extensions, none scoped here.
  The v1 shape is one full-bleed view per session; a session ends
  when its WebSocket closes. Persisted per-device preference is
  outside this ticket's intent (issue #38 territory).

## Consequences

- `LayoutMessage` gains a `view: str | None` field; the client
  `ServerLayout` type mirrors it. Both protocols were extended;
  existing clients that ignore unknown fields keep working (the
  field defaults to `null`).
- The `mediabrowser` widget kind is a documented public schema. New
  users can ship a layout with it without reading the daemon source.
- A user who has shipped a `mediabrowser` layout once has a stable
  path to enable the feature on every daemon they run: ship the
  layout, tap the chrome icon, the view is pinned until cleared.
- ADR-0003's wording ("the daemon has no chrome knowledge") is
  superseded here in a single bounded way: the daemon *resolves*
  named views to layouts at the client's request, and pushes a
  `view`-tagged `LayoutMessage` so the client knows which mode to
  render. Its *intent* (no chrome behaviour baked in, no per-button
  daemon knowledge) is preserved.
- The persistent chrome frame (bottom strip, jogstrip, app badge,
  connection indicator, settings button, media icon) remains a pure
  client concern; the new mechanism is opt-in per session and adds
  no daemon config. Future chrome-shaped views are positioned to be
  additive (a new layout + a new chrome button + a new `select_view`
  token, with no daemon or protocol change).

### The chrome media icon's passive state (issue #47)

The carve-out also covers the media icon's *passive* playback state
— a small green dot in the icon's top-right corner pulses outward
whenever at least one MPRIS player is `Playing`, and disappears
otherwise. The dot reads as the same "live signal" affordance chat
apps use for recording indicators, and deliberately doesn't compete
with the cyan accent the icon takes on when the view is open — the
two stack cleanly when both are true. The signal is a new
`chrome_media` daemon → client message (`{available, playing,
playing_count}`) the daemon emits on the two event types that change
the indicator's meaning: `NameOwnerChanged` registration transitions
(registration, unregistration, handoff) and `PlaybackStatus` changes
that cross the Playing ↔ non-Playing boundary. Position / Metadata
updates are filtered out so a 1Hz position poll doesn't flood the
icon with redundant frames. The icon stays a single glyph; the
change is a class toggle (`chrome-btn-playing`) and a CSS
pseudo-element overlay, not a glyph swap.

The indicator reflects global reality — every connected client
receives the frame regardless of which view it has pinned — so the
icon is useful as a glance affordance from across the room even when
the user isn't looking at the browser. On platforms without an
`MprisBackend` (macOS today), no frames are produced and the dot
stays hidden, the same graceful-degradation stance the rest of the
MPRIS surface takes.
