from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .layouts import Icon


class LayoutMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["layout"]
    app: str = "default"
    view: str | None = None
    widgets: list[dict]
    jogstrip_enabled: bool = True
    # Chrome app badge (ADR-0007), relayed opaquely. The client renders a
    # branded pill in the always-on bottom strip from these three:
    # ``display_name`` replaces the raw ``app`` match token, ``theme`` tints
    # the badge, ``icon`` is the ``{source, name}`` dispatch widgets use.
    # The daemon never interprets them.
    display_name: str | None = None
    theme: str | None = None
    icon: Icon | None = None
    # Non-null when the on-disk layouts failed to load. The client renders the
    # message in place of the widget grid; the daemon keeps the last-good
    # layouts live so a fix on disk restores service without a restart.
    error: str | None = None


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


ServerMessage = Annotated[
    Union[LayoutMessage, StateMessage, BrightnessMessage, WidgetUpdateMessage, MediaStateMessage],
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


ClientMessage = Annotated[
    Union[HelloMessage, PressMessage, JogMessage, JogEndMessage, PadMessage, PadTapMessage, PadDragMessage, TypeMessage, KeyMessage, MediaCommandMessage, SelectViewMessage, ClearViewMessage],
    Field(discriminator="type"),
]
