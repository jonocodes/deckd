from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import websockets
from aiohttp.test_utils import TestServer

from conftest import make_test_server
from deckd.media import MediaState
from deckd.server import Server


class FakeMediaManager:
    def __init__(self) -> None:
        self.reads = 0
        self.commands: list[tuple[str, str, float, str, int, str | None]] = []

    def stop(self) -> None:
        pass

    async def read(self, key: str, *, host: str, port: int, password_ref: str | None) -> MediaState:
        self.reads += 1
        return MediaState(available=True, stale=False, playing=True, position=10, duration=20, volume=30)

    async def command(
        self,
        key: str,
        command: str,
        value: float,
        *,
        host: str,
        port: int,
        password_ref: str | None,
    ) -> None:
        self.commands.append((key, command, value, host, port, password_ref))


async def _serve(tmp_path: Path, manager: FakeMediaManager) -> tuple[TestServer, Server]:
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: media
    kind: media
    grid: [0, 0, 4, 2]
    media_http:
      host: media.local
      port: 9090
      password_ref: VLC_PASSWORD
"""
    )
    server, *_ = make_test_server(layouts_dir=tmp_path, media_manager=manager)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    server.start_media_pump()
    return test_server, server


async def test_media_state_and_command_cross_real_websocket_boundary(tmp_path: Path) -> None:
    manager = FakeMediaManager()
    test_server, server = await _serve(tmp_path, manager)
    port = test_server.port or 0
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "layout"
            state = json.loads(await asyncio.wait_for(ws.recv(), 2))
            assert state | {"art_token": None} == {
                "type": "media_state",
                "id": "media",
                "available": True,
                "stale": False,
                "playing": True,
                "position": 10.0,
                "duration": 20.0,
                "volume": 30,
                "rate": None,
                "title": None,
                "artist": None,
                "album": None,
                "art_token": None,
                "desktop_entry": None,
                "can_go_next": None,
                "can_go_previous": None,
                "app_name": None,
            }
            await ws.send(json.dumps({"type": "media_command", "id": "media", "command": "volume", "value": 55}))
            await asyncio.sleep(0.05)
        assert manager.commands == [("media", "volume", 55.0, "media.local", 9090, "VLC_PASSWORD")]

        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "layout"
            await asyncio.sleep(1.1)
            assert manager.reads >= 2
    finally:
        await server.stop()
        await test_server.close()


async def test_media_unavailable_state_crosses_websocket_boundary(tmp_path: Path) -> None:
    manager = FakeMediaManager()

    async def unavailable(*args, **kwargs) -> MediaState:
        return MediaState(available=False, stale=True)

    manager.read = unavailable  # type: ignore[method-assign]
    test_server, server = await _serve(tmp_path, manager)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), 2)
            state = json.loads(await asyncio.wait_for(ws.recv(), 2))
            assert state["available"] is False
            assert state["stale"] is True
    finally:
        await server.stop()
        await test_server.close()
