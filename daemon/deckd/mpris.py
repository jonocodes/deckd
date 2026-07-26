from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .layouts import MediaBrowserEmptyState, MediaBrowserOrdering
from .media import MediaState


class MediaBrowser(BaseModel):
    """The ``mediabrowser`` widget kind (issue #50).

    Lists the MPRIS rows the daemon's :class:`MprisBackend` reports, with
    each row showing its player identity and prev / play-pause / next
    controls. Lives here (not in :mod:`layouts`) because it's the MPRIS
    feature's own schema, not a VLC-media cousin — keeping the new model
    next to its backend seam avoids re-coupling the layout module to a
    second media source.

    Fields:

    - ``id``: the widget id (used as the layout-internal id and surfaced
      to the client so it can correlate per-row updates).
    - ``grid``: the standard 4-int grid placement, identical to every
      other widget kind.
    - ``ordering``: how rows are presented when multiple MPRIS players
      are available. ``playing_first`` (default) surfaces the active
      player first; ``stable`` keeps the daemon-emitted order.
    - ``empty_state``: whether the cell still renders a placeholder row
      when no MPRIS player is discovered. ``show`` (default) keeps the
      chrome's icon reachable; ``hide`` collapses the cell so a layout
      that relies on the browser can drop the cell entirely.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    grid: list[int] = Field(min_length=4, max_length=4)
    ordering: MediaBrowserOrdering = "playing_first"
    empty_state: MediaBrowserEmptyState = "show"


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
