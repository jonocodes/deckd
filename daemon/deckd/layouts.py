from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Widget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    label: str | None = None
    icon: str | None = None
    grid: list[int] = Field(min_length=4, max_length=4)
    action: "Action | None" = None


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = None
    shell: str | None = None
    dbus: str | None = None
    terminal: bool | str | None = None


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: list[str] = Field(default_factory=list)
    widgets: list[Widget] = Field(default_factory=list)


def load_layout(path: Path) -> Layout:
    data = yaml.safe_load(path.read_text())
    try:
        return Layout.model_validate(data)
    except ValidationError as exc:
        raise SystemExit(f"invalid layout YAML at {path}:\n{exc}") from exc


Widget.model_rebuild()
