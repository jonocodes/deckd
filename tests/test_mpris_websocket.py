from __future__ import annotations

import asyncio
import json
from pathlib import Path

import websockets
from aiohttp.test_utils import TestServer

from conftest import make_test_server
from deckd.media import MediaState
from deckd.mpris import FakeMprisBackend


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
