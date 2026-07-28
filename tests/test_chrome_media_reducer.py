"""Tests for the chrome-media passive-playback indicator (issue #47).

Seam under test: ``compute_chrome_media`` in :mod:`deckd.mpris`. The
reducer is the pure mapping from the backend's owned-rows + per-row
``playing`` flag to the wire shape (``available``, ``playing``,
``playing_count``) the chrome media icon tints against. The reducer is
fed by ``DbusMprisBackend`` on the wire-relevant event types
(``NameOwnerChanged`` registration transitions and PlaybackStatus
boundary crossings); those wiring concerns live in the websocket round
trip tests, not here.

The seam is unit-tested: ``owned_names`` + ``states`` in,
``ChromeMediaState`` out. No D-Bus, no asyncio — the rule is small
enough to assert exhaustively at the input/output boundary.
"""
from __future__ import annotations

from deckd.media import MediaState
from deckd.mpris import ChromeMediaState, compute_chrome_media


def test_compute_chrome_media_no_players_reports_unavailable() -> None:
    """An empty session bus means the chrome icon's outlined default
    state holds — neither tinted nor framed. The reducer reports
    ``available=False, playing=False, playing_count=0``."""
    state = compute_chrome_media([], {})
    assert state == ChromeMediaState(available=False, playing=False, playing_count=0)


def test_compute_chrome_media_paused_player_reports_available_not_playing() -> None:
    """A registered but paused player is available (so the icon would
    outline if there were a tinted available-but-not-playing state, per
    the issue's out-of-scope note) but not playing."""
    state = compute_chrome_media(
        ["vlc"],
        {"vlc": MediaState(available=True, stale=False, playing=False)},
    )
    assert state == ChromeMediaState(available=True, playing=False, playing_count=0)


def test_compute_chrome_media_single_playing_player_reports_one() -> None:
    """One registered player in Playing state reports ``playing=True``
    with ``playing_count=1``."""
    state = compute_chrome_media(
        ["vlc"],
        {"vlc": MediaState(available=True, stale=False, playing=True)},
    )
    assert state == ChromeMediaState(available=True, playing=True, playing_count=1)


def test_compute_chrome_media_two_players_one_playing() -> None:
    """Two registered players, exactly one Playing. The chrome icon
    tints because at least one is playing; ``playing_count`` carries the
    count so a future indicator could show '2 playing'."""
    state = compute_chrome_media(
        ["vlc", "spotify"],
        {
            "vlc": MediaState(available=True, stale=False, playing=True),
            "spotify": MediaState(available=True, stale=False, playing=False),
        },
    )
    assert state == ChromeMediaState(available=True, playing=True, playing_count=1)


def test_compute_chrome_media_two_players_both_playing() -> None:
    state = compute_chrome_media(
        ["vlc", "spotify"],
        {
            "vlc": MediaState(available=True, stale=False, playing=True),
            "spotify": MediaState(available=True, stale=False, playing=True),
        },
    )
    assert state == ChromeMediaState(available=True, playing=True, playing_count=2)


def test_compute_chrome_media_missing_state_is_treated_as_not_playing() -> None:
    """A row whose state hasn't been fetched yet (the cache hasn't been
    populated — a common race right after ``NameOwnerChanged``) must
    not crash the reducer and must count as not playing. Available
    still reflects the owned-names set; only the playing tally uses
    the cache."""
    state = compute_chrome_media(["vlc"], {})
    assert state == ChromeMediaState(available=True, playing=False, playing_count=0)


def test_compute_chrome_media_none_playing_state_treated_as_not_playing() -> None:
    """A cached ``playing=None`` (the backend hasn't observed any
    ``PlaybackStatus`` transition yet — it hasn't issued a
    Properties.GetAll) must not crash the reducer and must count as
    not playing. Same out-of-scope as missing state: the chrome icon
    tints only on a confirmed Playing."""
    state = compute_chrome_media(
        ["vlc"],
        {"vlc": MediaState(available=True, stale=False, playing=None)},
    )
    assert state == ChromeMediaState(available=True, playing=False, playing_count=0)


def test_compute_chrome_media_only_counts_owned_rows() -> None:
    """A stale cache entry for a row that's no longer in ``owned_names``
    (a player disconnected mid-transition) must not contribute to the
    playing tally. Mirrors how the backend itself prunes its cache on
    NameOwnerChanged removals."""
    state = compute_chrome_media(
        ["vlc"],
        {
            "vlc": MediaState(available=True, stale=False, playing=False),
            "ghost": MediaState(available=True, stale=False, playing=True),
        },
    )
    assert state == ChromeMediaState(available=True, playing=False, playing_count=0)
