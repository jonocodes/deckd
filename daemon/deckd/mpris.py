from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .media import MediaState


class MprisBackend(Protocol):
    """Backend seam for enumerating MPRIS rows and controlling them."""

    def row_ids(self) -> list[str]:
        ...

    async def read_state(self, row_id: str) -> MediaState | None:
        ...

    async def send_command(self, row_id: str, command: str) -> None:
        ...


@dataclass
class FakeMprisBackend(MprisBackend):
    states: dict[str, MediaState]

    def __init__(self, states: dict[str, MediaState] | None = None) -> None:
        self.states = dict(states or {})
        self.commands: list[tuple[str, str]] = []

    def row_ids(self) -> list[str]:
        return list(self.states)

    async def read_state(self, row_id: str) -> MediaState | None:
        return self.states.get(row_id)

    async def send_command(self, row_id: str, command: str) -> None:
        self.commands.append((row_id, command))
