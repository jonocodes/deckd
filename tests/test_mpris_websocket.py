from __future__ import annotations

import asyncio
import json
from pathlib import Path

import websockets
from aiohttp.test_utils import TestServer

from conftest import make_test_server
from deckd.media import MediaState
from deckd.mpris import (
    DbusMprisBackend,
    FakeMprisBackend,
    PLAYER_INTERFACE,
)
from tests.test_mpris_dbus import FakeDbusBus


async def test_mpris_rows_and_commands_cross_websocket_boundary(tmp_path: Path) -> None:
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: browser
    kind: mediabrowser
    grid: [0, 0, 4, 2]
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


async def test_dbus_mpris_round_trips_across_websocket(tmp_path: Path) -> None:
    """End-to-end check (issue #52 acceptance criterion 7): the full
    ``DbusMprisBackend`` -> server pump -> WebSocket flow, driven by a
    fake D-Bus bus that records method calls and lets the test push
    signals. Names are seeded on the fake bus's synthetic
    ``ListNames`` reply; commands from the client arrive at the
    backend via ``media_command`` messages and translate into the
    right D-Bus method call.
    """
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: browser
    kind: mediabrowser
    grid: [0, 0, 4, 2]
"""
    )
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc",
        {"PlaybackStatus": "Playing", "Metadata": {"xesam:title": "VLC Playing"}},
    )
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.spotify",
        {"PlaybackStatus": "Paused", "Metadata": {"xesam:title": "Spotify"}},
    )

    # Use a small closure-based factory to drop a fresh bus in.
    captured: dict = {}

    def factory(_bt):
        captured["bus"] = bus
        return bus

    server, *_ = make_test_server(
        layouts_dir=tmp_path,
        mpris_backend=DbusMprisBackend(bus_factory=factory),
    )
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    # Start the bus, then start the pump loop. Both happen on the
    # event loop we're running on.
    if isinstance(server.mpris, DbusMprisBackend):
        await server.mpris.start()
    server.start_media_pump()
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
