from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import websockets
from aiohttp.test_utils import TestServer

# Reuse the elaborate ``FakeDbusBus`` from the sibling test module.
# The tests dir has no ``__init__.py`` so a plain
# ``from test_mpris_dbus import ...`` would not resolve; same trick
# ``conftest.py`` uses for the daemon package.
sys.path.insert(0, str(Path(__file__).parent))

from conftest import make_test_server, requires_dbus
from deckd.media import MediaState
from deckd.mpris import (
    DbusMprisBackend,
    FakeMprisBackend,
    PLAYER_INTERFACE,
)
from test_mpris_dbus import FakeDbusBus


async def test_mpris_rows_and_commands_cross_websocket_boundary(tmp_path: Path) -> None:
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: browser
    kind: nowplaying
    size: [4, 2]
"""
    )
    backend = FakeMprisBackend(
        {
            "vlc": MediaState(available=True, stale=False, playing=True, title="VLC"),
            "spotify": MediaState(available=True, stale=False, playing=False, title="Spotify"),
        }
    )
    server, *_ = make_test_server(layouts_dir=tmp_path, mpris_backend=backend)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    server.start_media_pump()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "layout"
            received = [
                json.loads(await asyncio.wait_for(ws.recv(), 2)) for _ in range(2)
            ]
            assert {message["id"] for message in received} == {"mpris.vlc", "mpris.spotify"}
            await ws.send(
                json.dumps(
                    {
                        "type": "media_command",
                        "id": "mpris.spotify",
                        "command": "next",
                    }
                )
            )
            await asyncio.sleep(0.05)
        assert backend.commands == [("spotify", "next")]
    finally:
        await server.stop()
        await test_server.close()


async def test_mpris_rows_flow_when_browser_is_a_non_current_view(
    tmp_path: Path,
) -> None:
    """The pump must broadcast MPRIS rows even when the ``nowplaying``
    widget lives only in a chrome-view layout that is *not* the focused
    app's current layout — the real-world shape, where a client pins the
    ``mpris`` view while some other app (e.g. VLC) is focused. Regression:
    gating on ``_current_layout`` starved the pump and left the browser
    empty against a live daemon even though players were discovered."""
    # Current/default layout has no nowplaying widget...
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: pad
    kind: trackpad
    size: [4, 2]
"""
    )
    # ...the browser lives only in the separate mpris view layout.
    (tmp_path / "mpris.yaml").write_text(
        """
match: [mpris]
widgets:
  - id: browser
    kind: nowplaying
    size: [4, 2]
"""
    )
    backend = FakeMprisBackend(
        {"vlc": MediaState(available=True, stale=False, playing=True, title="VLC")}
    )
    server, *_ = make_test_server(layouts_dir=tmp_path, mpris_backend=backend)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    server.start_media_pump()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "layout"
            state = json.loads(await asyncio.wait_for(ws.recv(), 2))
            assert state["id"] == "mpris.vlc"
    finally:
        await server.stop()
        await test_server.close()


async def test_late_session_receives_current_players_via_snapshot(
    tmp_path: Path,
) -> None:
    """A session that connects *after* the pump has already broadcast the
    players must still receive them. The pump only broadcasts on change
    against a global cache, and MPRIS state is static while a track plays,
    so without a per-connect snapshot the second client (a reload, a
    second phone) would show "no players detected" forever. Regression."""
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: browser
    kind: nowplaying
    size: [4, 2]
"""
    )
    backend = FakeMprisBackend(
        {"vlc": MediaState(available=True, stale=False, playing=True, title="VLC")}
    )
    server, *_ = make_test_server(layouts_dir=tmp_path, mpris_backend=backend)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    server.start_media_pump()
    url = f"ws://127.0.0.1:{test_server.port}/ws"
    try:
        # First client drains the pump's initial broadcast, populating the
        # pump's global ``last`` cache so it won't re-broadcast on change.
        async with websockets.connect(url) as first:
            assert json.loads(await asyncio.wait_for(first.recv(), 2))["type"] == "layout"
            assert json.loads(await asyncio.wait_for(first.recv(), 2))["id"] == "mpris.vlc"
            # Let the pump run another cycle so ``last`` is definitely set.
            await asyncio.sleep(1.1)
            # Second client connects late — must still see the player via the
            # connect-time snapshot, not wait for a (never-coming) change.
            async with websockets.connect(url) as second:
                assert json.loads(await asyncio.wait_for(second.recv(), 2))["type"] == "layout"
                snap = json.loads(await asyncio.wait_for(second.recv(), 2))
                assert snap["type"] == "media_state"
                assert snap["id"] == "mpris.vlc"
    finally:
        await server.stop()
        await test_server.close()


async def _boot_mpris_websocket(
    tmp_path: Path,
    bus: FakeDbusBus,
) -> tuple[TestServer, "Server", FakeDbusBus]:
    """Stand up a real daemon + WebSocket fronted by ``bus``.

    Used by the round-trip tests below to share the layout, bus
    factory, server boot, and teardown plumbing. Returns the
    ``TestServer`` (so the caller can connect), the ``Server`` (so it
    can drive the pump), and the ``bus`` (so the test can read
    recorded calls after the fact). The layout declares a single
    ``nowplaying`` widget so the server wires a real
    :class:`DbusMprisBackend`.
    """
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: browser
    kind: nowplaying
    size: [4, 2]
"""
    )
    server, *_ = make_test_server(
        layouts_dir=tmp_path,
        mpris_backend=DbusMprisBackend(bus_factory=lambda _bt: bus),
    )
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    if isinstance(server.mpris, DbusMprisBackend):
        await server.mpris.start()
    server.start_media_pump()
    return test_server, server, bus


@requires_dbus
async def test_dbus_mpris_round_trips_across_websocket(tmp_path: Path) -> None:
    """End-to-end check (issue #52 acceptance criterion 7): the full
    ``DbusMprisBackend`` -> server pump -> WebSocket flow, driven by a
    fake D-Bus bus that records method calls and lets the test push
    signals. Names are seeded on the fake bus's synthetic
    ``ListNames`` reply; commands from the client arrive at the
    backend via ``media_command`` messages and translate into the
    right D-Bus method call."""
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc",
        {"PlaybackStatus": "Playing", "Metadata": {"xesam:title": "VLC Playing"}},
    )
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.spotify",
        {"PlaybackStatus": "Paused", "Metadata": {"xesam:title": "Spotify"}},
    )
    test_server, server, bus = await _boot_mpris_websocket(tmp_path, bus)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "layout"
            received = [
                json.loads(await asyncio.wait_for(ws.recv(), 2)) for _ in range(2)
            ]
            ids = {message["id"] for message in received if message["type"] == "media_state"}
            assert ids == {"mpris.vlc", "mpris.spotify"}

            # Client-side click: pause Spotify.
            await ws.send(
                json.dumps(
                    {
                        "type": "media_command",
                        "id": "mpris.spotify",
                        "command": "play-pause",
                    }
                )
            )
            # Pump loop sleeps 1s; let the dispatch settle.
            await asyncio.sleep(0.1)

        # The bus recorded the dispatch with the right destination +
        # method.
        playlist_calls = [
            c
            for c in bus.calls
            if c["interface"] == PLAYER_INTERFACE and c["member"] == "PlayPause"
        ]
        assert playlist_calls, "expected a PlayPause call on the Player interface"
        assert playlist_calls[0]["destination"] == "org.mpris.MediaPlayer2.spotify"
    finally:
        await server.stop()
        await test_server.close()


@requires_dbus
async def test_all_three_browser_commands_round_trip_through_dbus(tmp_path: Path) -> None:
    """End-to-end check (issue #54 acceptance criterion 4): every browser
    command — ``play-pause``, ``next``, ``previous`` — issued over a real
    WebSocket lands as the right D-Bus method on the right bus name.

    The seam is the WebSocket -> dispatch -> MprisBackend -> D-Bus
    boundary; nothing inside that chain is mocked beyond the bus
    itself. Together with :func:`test_dbus_mpris_round_trips_across_websocket`
    this is the WebSocket integration test the spec asks for: one
    command is enough to prove the round trip; all three is enough to
    prove the per-command dispatch table."""
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc",
        {"PlaybackStatus": "Playing", "Metadata": {"xesam:title": "VLC Playing"}},
    )
    test_server, server, bus = await _boot_mpris_websocket(tmp_path, bus)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "layout"
            # Drain the initial media_state for vlc so the pump's cache
            # is warm before we start sending commands.
            await asyncio.wait_for(ws.recv(), 2)

            for command in ("play-pause", "next", "previous"):
                await ws.send(
                    json.dumps(
                        {
                            "type": "media_command",
                            "id": "mpris.vlc",
                            "command": command,
                        }
                    )
                )
                # Let the dispatch await the bus round-trip.
                await asyncio.sleep(0.05)
    finally:
        await server.stop()
        await test_server.close()

    # The bus saw exactly one call per command, all on the Player
    # interface, all targeting the vlc row's bus name.
    player_calls = [
        c
        for c in bus.calls
        if c["interface"] == PLAYER_INTERFACE
        and c["member"] in {"PlayPause", "Next", "Previous"}
    ]
    assert [c["member"] for c in player_calls] == ["PlayPause", "Next", "Previous"]
    assert all(c["destination"] == "org.mpris.MediaPlayer2.vlc" for c in player_calls)
