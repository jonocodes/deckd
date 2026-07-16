from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class LayoutMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["layout"]
    app: str = "default"
    widgets: list[dict]


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
