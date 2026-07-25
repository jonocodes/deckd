"""Unit tests for the VLC HTTP media backend command building."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

from deckd.media import VlcHttpBackend


class _CapturingBackend(VlcHttpBackend):
    """VlcHttpBackend that records requested paths instead of doing HTTP."""

    def __init__(self) -> None:
        super().__init__()
        self.paths: list[str] = []

    def _request(self, path: str) -> dict:  # type: ignore[override]
        self.paths.append(path)
        return {}


@pytest.mark.asyncio
async def test_seek_builds_absolute_seconds_request() -> None:
    """A seek must hit VLC's ``command=seek`` with an absolute second value.

    Regression for #45: seek was unhandled and raised, which tore down the
    websocket session and bounced the client's position slider back to 0.
    """
    backend = _CapturingBackend()
    await backend.command("seek", 137.6)
    assert backend.paths == ["/requests/status.json?command=seek&val=138"]


@pytest.mark.asyncio
async def test_seek_clamps_negative_to_zero() -> None:
    backend = _CapturingBackend()
    await backend.command("seek", -5)
    assert backend.paths == ["/requests/status.json?command=seek&val=0"]


@pytest.mark.asyncio
async def test_volume_and_rate_still_work() -> None:
    backend = _CapturingBackend()
    await backend.command("volume", 50)
    await backend.command("rate", 1.5)
    assert backend.paths == [
        "/requests/status.json?command=volume&val=128",
        "/requests/status.json?command=rate&val=1.5",
    ]


@pytest.mark.asyncio
async def test_unsupported_command_raises() -> None:
    backend = _CapturingBackend()
    with pytest.raises(ValueError):
        await backend.command("bogus", 1)
