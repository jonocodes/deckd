"""Tests for ``deckd.mpris.build_fake_mpris`` — the JSON-seed factory
behind the ``DECKD_FAKE_MPRIS`` daemon seam (used by the now-playing
Playwright e2e to boot a real daemon with a synthetic "player is
playing" surface, no session bus required).
"""
from __future__ import annotations

import asyncio

import pytest

from deckd.mpris import build_fake_mpris


def test_build_fake_mpris_seeds_rows_and_defaults_available() -> None:
    """A two-key seed ("playing" + metadata) yields an available,
    playing row — ``available`` defaults to True so the common seed
    stays terse."""
    backend = build_fake_mpris(
        {"vlc": {"playing": True, "title": "Track", "artist": "Artist"}}
    )
    assert backend.row_ids() == ["vlc"]
    state = asyncio.run(backend.read_state("vlc"))
    assert state is not None
    assert state.available is True
    assert state.playing is True
    assert state.title == "Track"
    assert state.artist == "Artist"


def test_build_fake_mpris_honours_explicit_available_false() -> None:
    backend = build_fake_mpris({"vlc": {"available": False}})
    state = asyncio.run(backend.read_state("vlc"))
    assert state is not None
    assert state.available is False


def test_build_fake_mpris_rejects_unknown_field() -> None:
    """A typo'd seed key fails loudly rather than silently dropping —
    an e2e that seeds ``titel`` should break, not render a blank row."""
    with pytest.raises(ValueError) as excinfo:
        build_fake_mpris({"vlc": {"titel": "oops"}})
    assert "titel" in str(excinfo.value)


def test_fake_backend_accepts_chrome_media_listener() -> None:
    """The fake must implement ``set_chrome_media_listener`` (the
    server wires it on whatever backend it holds); a seeded playing row
    lights the chrome dot via the snapshot path, so the snapshot must
    report ``playing``."""
    backend = build_fake_mpris({"vlc": {"playing": True}})
    backend.set_chrome_media_listener(lambda _state: None)  # must not raise
    snap = backend.chrome_media_snapshot()
    assert snap.available is True
    assert snap.playing is True
    assert snap.playing_count == 1
