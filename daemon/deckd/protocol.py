from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from .layouts import Icon


class LayoutMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["layout"]
    app: str = "default"
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


ServerMessage = Annotated[
    Union[LayoutMessage, StateMessage, BrightnessMessage],
    Field(discriminator="type"),
]


class HelloMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["hello"]
    client: str = "web"
    token: str | None = None


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


ClientMessage = Annotated[
    Union[HelloMessage, PressMessage, JogMessage, JogEndMessage, PadMessage, PadTapMessage, PadDragMessage],
    Field(discriminator="type"),
]
