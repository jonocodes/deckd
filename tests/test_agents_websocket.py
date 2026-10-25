"""WebSocket round-trip for agent tiles (issue #180).

Seam under test: an :class:`AgentSource` snapshot -> the daemon's
dedupe + broadcast -> an ``agents`` frame on the wire, plus the
connect-time replay. Mirrors ``test_running_windows_websocket``.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import websockets
from aiohttp.test_utils import TestServer

sys.path.insert(0, str(Path(__file__).parent))

from conftest import make_test_server
from deckd.agents import AgentStatus


class QueueAgentSource:
    name = "fake"

    def __init__(self) -> None:
        self.queue: asyncio.Queue[list[AgentStatus]] = asyncio.Queue()

    async def watch(self) -> AsyncIterator[list[AgentStatus]]:
        while True:
            yield await self.queue.get()


WORKING = AgentStatus(source="paseo", id="a1", title="Refactor", state="working", cwd="/src/x", since=100.0)
ASKING = AgentStatus(source="paseo", id="a2", title="Docs", state="needs_input", detail="Approve Bash")


async def _boot(tmp_path: Path, source: QueueAgentSource | None):
    (tmp_path / "default.yaml").write_text("match: [default]\nwidgets:\n  - id: x\n    kind: blank\n")
    server, *_ = make_test_server(decks_dir=tmp_path, agent_source=source)
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    server.start_agents_watcher()
    return ts, server


async def _frames(ws, kind: str, timeout: float = 2) -> dict:
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if msg["type"] == kind:
            return msg


async def test_agents_broadcast_and_dedupe(tmp_path: Path) -> None:
    source = QueueAgentSource()
    ts, server = await _boot(tmp_path, source)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            # Source configured but no snapshot yet: connect replays [].
            assert (await _frames(ws, "agents"))["agents"] == []
            await source.queue.put([ASKING, WORKING])
            frame = await _frames(ws, "agents")
            assert frame == {
                "type": "agents",
                "agents": [
                    {"source": "paseo", "id": "a2", "title": "Docs", "state": "needs_input", "cwd": None, "detail": "Approve Bash", "since": None},
                    {"source": "paseo", "id": "a1", "title": "Refactor", "state": "working", "cwd": "/src/x", "detail": None, "since": 100.0},
                ],
            }
            # Identical snapshot: no frame. A real change: one frame.
            await source.queue.put([ASKING, WORKING])
            await source.queue.put([WORKING])
            assert [a["id"] for a in (await _frames(ws, "agents"))["agents"]] == ["a1"]
    finally:
        await server.stop()
        await ts.close()


async def test_agents_replayed_to_late_client(tmp_path: Path) -> None:
    source = QueueAgentSource()
    ts, server = await _boot(tmp_path, source)
    try:
        await source.queue.put([WORKING])
        while server._last_agents is None:
            await asyncio.sleep(0.01)
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            assert [a["id"] for a in (await _frames(ws, "agents"))["agents"]] == ["a1"]
    finally:
        await server.stop()
        await ts.close()


async def test_no_source_sends_no_agents_frame(tmp_path: Path) -> None:
    ts, server = await _boot(tmp_path, None)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            seen = []
            try:
                while True:
                    seen.append(json.loads(await asyncio.wait_for(ws.recv(), 0.3))["type"])
            except asyncio.TimeoutError:
                pass
            assert "deck" in seen and "agents" not in seen
    finally:
        await server.stop()
        await ts.close()
