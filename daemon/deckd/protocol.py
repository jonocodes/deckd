from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .layouts import Icon


class FocusedAppInfo(BaseModel):
    """The daemon's best-known identity of the currently focused application.

    Carries the fields the editor's new-layout creation flow (#104) needs to
    prefill ``match`` tokens for the detect-and-offer prompt and the
    browser-vs-site branch. None when the daemon has not yet seen a focus
    event (headless, start-up race).

    ``app_id`` and ``wm_class`` are the desktop-identity tokens the layout
    matcher compares against ``match`` entries. ``title`` is the raw window
    title. ``is_browser`` gates the two-prefill browser branch — its value
    is the daemon's best-effort substring match against a maintained browser
    marker list (:func:`deckd.platform.AppInfo.is_browser`).
    """

    model_config = ConfigDict(extra="forbid")

    app_id: str | None = None
    wm_class: str | None = None
    title: str | None = None
    is_browser: bool = False


class LayoutMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["layout"]
    app: str = "default"
    view: str | None = None
    widgets: list[dict]
    # Overflow behaviour for the client's reflow (ADR-0010): ``clip`` drops
    # trailing widgets off-surface, ``shrink-to-fit`` shrinks cells below the
    # band floor so all fit. Relayed from the layout's ``overflow`` field.
    overflow: Literal["clip", "shrink-to-fit"] = "shrink-to-fit"
    jogstrip_enabled: bool = True
    # Chrome app badge (ADR-0007), relayed opaquely. The client renders a
    # branded pill in the always-on bottom strip from these three:
    # ``display_name`` replaces the raw ``app`` match token, ``theme`` tints
    # the badge, ``icon`` is the ``{source, name}`` dispatch widgets use.
    # The daemon never interprets them.
    display_name: str | None = None
    theme: str | None = None
    icon: Icon | None = None
    # True when this layout was resolved as a *web app*: it matched the focused
    # browser's window title (a ``title:`` token) AND the focused app is a
    # browser. The client renders a small globe on the badge. Derived by the
    # daemon, never authored in YAML — a plain title match on a non-browser
    # (or an app-identity match) leaves this false.
    web_app: bool = False
    # Non-null when the on-disk layouts failed to load. The client renders the
    # message in place of the widget grid; the daemon keeps the last-good
    # layouts live so a fix on disk restores service without a restart.
    error: str | None = None
    # The currently focused app's identity, populated when the daemon has a
    # focus backend (never in headless mode). ``None`` before the first focus
    # event arrives. The editor's new-layout creation flow (#104) uses this to
    # prefill ``match`` tokens for the detect-and-offer prompt and the
    # browser-vs-site branch.
    focused_app: FocusedAppInfo | None = None
    # True only on a genuine focus-driven fallback to the default layout —
    # i.e. the resolution missed every loaded layout and ``store.default()``
    # was returned. The client uses this to render the live program next to
    # the layout name (issues #116 / #123, stage 1). Forced ``False``
    # whenever the daemon is serving a pinned layout/view (demo
    # ``?layout=`` pin or chrome ``select_view`` pin), even if the pinned
    # layout happens to be the default — a pin means "frozen, don't report
    # what's underneath".
    is_default: bool = False


class StateMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["state"]
    locked: bool


class BrightnessMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["brightness"]
    value: int = Field(ge=0, le=255)


class MediaStateMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["media_state"]
    id: str
    available: bool = False
    stale: bool = True
    playing: bool | None = None
    position: float | None = Field(default=None, ge=0)
    duration: float | None = Field(default=None, ge=0)
    volume: int | None = Field(default=None, ge=0, le=100)
    rate: float | None = Field(default=None, gt=0)
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    art_token: str | None = None
    # MPRIS-only fields populated only for ``id == "mpris.<suffix>"``
    # state messages (issue #52). The VLC path leaves them ``None``.
    # ``desktop_entry`` is the bus's reported ``.desktop`` basename
    # (or ``None`` when the player doesn't publish one); the browser
    # uses it to look up an app icon. ``can_go_next`` /
    # ``can_go_previous`` mirror MPRIS ``CanGoNext`` /
    # ``CanGoPrevious`` so the browser can grey out the matching
    # transport controls.
    desktop_entry: str | None = None
    can_go_next: bool | None = None
    can_go_previous: bool | None = None
    # The player's human-readable name from the MPRIS root interface's
    # ``Identity`` (e.g. "Firefox", "VLC media player"); the browser
    # renders it as a per-row header. ``None`` for the VLC widget path.
    app_name: str | None = None


class ChromeMediaMessage(BaseModel):
    """Daemon -> client push: the chrome media icon's passive
    playback-state snapshot (issue #47).

    Sent by the daemon whenever the meaning of the indicator changes —
    a player registered / unregistered, or a ``PlaybackStatus`` flipped
    across the Playing ↔ non-Playing boundary. The client tints the
    media icon when ``playing`` is true and leaves it outlined
    otherwise. Position / Metadata updates that don't flip ``playing``
    never produce a frame (debounce by event type).

    Pushed to every connected session regardless of which view the
    client has pinned — the indicator is global chrome, not
    per-session. ``available`` is true when at least one MPRIS
    player is registered; ``playing`` is true when at least one is
    in ``PlaybackStatus == Playing``; ``playing_count`` carries the
    number currently in Playing so a future per-player / count-style
    indicator has the raw tally without a separate wire message.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["chrome_media"]
    available: bool
    playing: bool
    playing_count: int = Field(ge=0)


class WidgetUpdateMessage(BaseModel):
    """Daemon->client push: a meter widget's live value (issue #40).

    The daemon sends one of these to every connected session whenever a
    sensor the session has subscribed to produces a new reading.
    ``id`` is the widget id from the active layout; ``source`` echoes
    the bound sensor name so a client with a stale layout can still tell
    what the value belongs to; ``unit`` rides along so the client
    doesn't have to know a per-source unit registry.

    ``stale=True`` means the source could not refresh (sensor
    disappeared, permission denied); the client renders an "unknown"
    treatment and keeps the bar at its last-known position. We send
    ``stale=True`` explicitly rather than dropping the message so the
    UI can stop claiming the value is fresh.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["widget_update"]
    id: str
    source: str
    value: float
    unit: str
    stale: bool = False


class EventMessage(BaseModel):
    """Daemon -> client push: a diagnostic event (issue #73).

    Fires on focus changes, layout reloads, action attempts,
    authentication outcomes, and MPRIS player / playback transitions.
    The client renders nothing on receipt — the events are observability
    fodder for an external watcher that has subscribed to this
    session's stream.

    Unknown ``name`` values are ignored on the client (clients key off
    a switch in their message dispatcher). ``data`` is event-specific
    and never carries the shared password or injected input.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["event"]
    name: str = Field(min_length=1)
    ts: float
    data: dict
    #: When the daemon had a correlation id for the originating
    #: action / request, it rides along so a watcher can correlate the
    #: event to log lines / ``/actions/recent`` entries / the
    #: structured-log feed.
    trace_id: str | None = None


class MacroResultMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["macro_result"]
    id: str
    outcome: Literal["ok", "failed-at-step"]
    failed_step: int | None = Field(default=None, ge=0)
    error: str | None = None


class ConfirmRequestMessage(BaseModel):
    """Daemon -> client push: ask for a confirmation before running an
    action (issues #69 / #107).

    Fires on a ``confirm: true`` press *instead of* running the action.
    The daemon mints ``confirm_id``, stores the pending action in
    session-scoped state, and waits up to ~30 seconds for a matching
    :class:`ConfirmResponseMessage`. The client renders a confirmation
    prompt naming the widget (``widget_id``); the widget's action /
    command text is *not* sent over the wire — the client already holds
    it from the last ``LayoutMessage`` and generates the prompt text
    locally (no custom copy from the daemon).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["confirm_request"]
    confirm_id: str = Field(min_length=1)
    widget_id: str = Field(min_length=1)


class WindowListEntry(BaseModel):
    """One row in the running-windows list (issues #116 / #120 / #126).

    ``window_id`` is the per-session opaque string handle minted by the
    platform extension on enumeration (#119) — the client echoes it on
    tap (stage 3, #122) but never parses it. ``label`` is the
    daemon-derived display string: matched layout's ``display_name`` on
    a hit, else a raw identity fallback (``wm_class`` then ``app_id``
    then ``title``, last resort). ``icon`` mirrors the matched layout's
    icon when present and is ``null`` on a default-fallback row — the
    absence is honest (a generic terminal glyph would imply every xterm
    is the same xterm; the list is per-window precisely so they're not).
    """

    model_config = ConfigDict(extra="forbid")

    window_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    icon: Icon | None = None


class RunningWindowsMessage(BaseModel):
    """Daemon -> client push: the chrome windows list's snapshot
    (issues #116 / #120 / #126).

    Full-snapshot per push, MRU-sorted (per #119). Pushed to every
    connected session regardless of which view the client has pinned —
    the list reflects global reality; every session holds a fresh
    snapshot so a view switch is instant (no spinner, no
    ``select_view`` round-trip-fetch). Same graceful-degradation as
    ``ChromeMediaMessage``: backends whose ``capabilities()`` does not
    include ``"watch_windows"`` never produce a frame.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["running_windows"]
    windows: list[WindowListEntry]


ServerMessage = Annotated[
    Union[LayoutMessage, StateMessage, BrightnessMessage, WidgetUpdateMessage, MediaStateMessage, ChromeMediaMessage, EventMessage, MacroResultMessage, ConfirmRequestMessage, RunningWindowsMessage],
    Field(discriminator="type"),
]


class HelloMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["hello"]
    client: str = "web"
    token: str | None = None
    # Shared password (issue #16). Required whenever the daemon runs with auth
    # on; validated by the server before the hello frame reaches ``_dispatch``.
    # Omitted only when the daemon was started with --no-auth.
    password: str | None = None
    # Optional demo pin (``?layout=<name>`` in the client URL): forces this one
    # session to the named layout regardless of host focus, so a demo device can
    # be parked on a view. Ignored if the name doesn't match a loaded layout.
    layout: str | None = None
    # Issue #73: client-supplied correlation id. When set, every
    # diagnostic surface touched by this session (recent-action
    # entries, log fields, event pushes) carries this id so an AI
    # agent can correlate the connection to its own watcher. The
    # ``X-Deckd-Trace`` upgrade header takes precedence when both are
    # present; absent both, the daemon mints a fresh short id.
    trace: str | None = None


class PressMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["press"]
    id: str


class JogMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["jog"]
    id: str
    delta: int


class JogEndMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["jog_end"]
    id: str
    velocity: int


class PadMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["pad"]
    id: str
    dx: int
    dy: int


class PadTapMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["pad_tap"]
    id: str
    fingers: int


class PadDragMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["pad_drag"]
    id: str
    state: Literal["start", "end"]


class TypeMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["type"]
    text: str


class MediaCommandMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["media_command"]
    id: str
    command: Literal["volume", "seek", "rate", "play-pause", "next", "previous"]
    value: float | None = None

    @model_validator(mode="after")
    def validate_value(self) -> "MediaCommandMessage":
        if self.command in {"volume", "seek", "rate"} and self.value is None:
            raise ValueError(f"media command {self.command} requires a value")
        if self.command in {"play-pause", "next", "previous"} and self.value is not None:
            raise ValueError(f"media command {self.command} does not accept a value")
        return self


class SelectViewMessage(BaseModel):
    """Client -> daemon: ask the server to render a chrome view (issue #50).

    The named view is the ``id`` of a layout whose ``match`` token is the
    same string (e.g. ``mpris`` resolves to the ``mpris.yaml`` shipping
    layout). The server pushes the resolved layout with ``view`` set to
    the requested name, so the client can tell focus-driven layouts
    (``view: null``) from client-requested chrome views. An unknown
    name pushes the current focused-app layout with ``view`` set and
    ``error: "view not found"`` so the client can show the failure
    without losing the chrome context.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["select_view"]
    view: str = Field(min_length=1)


class ClearViewMessage(BaseModel):
    """Client -> daemon: revert to the focused-app layout (issue #50).

    Undoes a prior ``select_view`` for this session only; other sessions
    keep whatever view they have selected (or none). The server pushes
    the current focused-app layout with ``view: null``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["clear_view"]


class KeyMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["key"]
    combo: str


class RaiseWindowMessage(BaseModel):
    """Client -> daemon: raise (focus) an open window by its id (#122).

    The user tapped a row in the running-windows chrome list; the client
    echoes back the opaque ``window_id`` the daemon minted into that
    row's ``running_windows`` frame (#119). The daemon routes it to the
    active backend's ``raise_window``; backends that can't enumerate /
    raise never produce the list in the first place, so a stray id here
    is a no-op at worst. The client pairs this with a ``clear_view`` to
    close the overlay (stage 3, #122).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["raise_window"]
    window_id: str = Field(min_length=1)


class ConfirmResponseMessage(BaseModel):
    """Client -> daemon: the user's verdict on a pending
    :class:`ConfirmRequestMessage` (issues #69 / #107).

    ``decision`` is a literal verb over a bare bool, mirroring the
    ``MediaCommandMessage`` idiom (``"play-pause"`` not ``True``). The
    daemon looks up the pending action by ``confirm_id``: an unknown /
    expired / superseded token is a no-op (the action never runs). On
    ``"confirm"`` the daemon re-enters the normal ``run_action`` path;
    on ``"cancel"`` the pending action is dropped without side effects.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["confirm_response"]
    confirm_id: str = Field(min_length=1)
    decision: Literal["confirm", "cancel"]


class EnableEventsMessage(BaseModel):
    """Client -> daemon: subscribe this session to the diagnostic event
    stream (issue #73).

    Adds the session to the server's per-session subscriber list. Until
    the client opts in, no diagnostic events are pushed. A re-sent
    ``enable_events`` is a no-op. ``events`` is the optional allow-list;
    when absent, every published event name is delivered.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["enable_events"]
    events: list[str] | None = None


class DisableEventsMessage(BaseModel):
    """Client -> daemon: stop the diagnostic event stream for this
    session (issue #73). Mirrors :class:`EnableEventsMessage`."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["disable_events"]


class MprisCommandRequest(BaseModel):
    """Body for ``POST /mpris/{row}/command`` (issue #72).

    Only ``play-pause``, ``next``, ``previous`` are dispatched to the
    MPRIS backend — the dispatch table is intentionally small enough
    that a bug or a typo in the wire shape can't invoke arbitrary
    D-Bus methods. ``raise`` is accepted at the validation layer
    (the spec's acceptance criterion mentions it) but currently
    rejected with 400; the dispatch will land alongside MPRIS
    Raise() support in a follow-up.
    """

    model_config = ConfigDict(extra="forbid")

    command: Literal["play-pause", "next", "previous", "raise"]


ClientMessage = Annotated[
    Union[HelloMessage, PressMessage, JogMessage, JogEndMessage, PadMessage, PadTapMessage, PadDragMessage, TypeMessage, KeyMessage, MediaCommandMessage, SelectViewMessage, ClearViewMessage, RaiseWindowMessage, EnableEventsMessage, DisableEventsMessage, ConfirmResponseMessage],
    Field(discriminator="type"),
]
