"""Tests for the deckd daemon at the WebSocket boundary."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiohttp
import pytest
import websockets

from conftest import ServerHandle

# Time to wait for a fire-and-forget side effect (shell dispatch, scroll emit).
SIDE_EFFECT_WAIT = 0.05


@asynccontextmanager
async def ws_connected(srv: ServerHandle) -> AsyncIterator[tuple[websockets.WebSocketClientProtocol, dict]]:
    """Open a WS connection and yield (ws, initial_layout_message)."""
    async with websockets.connect(srv.ws_url) as ws:
        layout = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        yield ws, layout


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


async def test_health(srv: ServerHandle) -> None:
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/health") as r:
            body = await r.json()

    assert body["ok"] is True
    assert "sessions" in body


# ---------------------------------------------------------------------------
# Layout push on connect
# ---------------------------------------------------------------------------


async def test_layout_push_on_connect(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (_, layout):
        pass

    assert layout["type"] == "layout"
    assert isinstance(layout["widgets"], list)
    assert len(layout["widgets"]) > 0


# ---------------------------------------------------------------------------
# Button press → shell dispatch
# ---------------------------------------------------------------------------


async def test_press_shell(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "press", "id": "open-url"}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    assert any(kind == "shell" and "example.com" in val for kind, val in srv.called)


# ---------------------------------------------------------------------------
# Button press → terminal dispatch
# ---------------------------------------------------------------------------


async def test_press_terminal_auto(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "press", "id": "open-terminal"}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    assert any(kind == "terminal" for kind, _ in srv.called)


async def test_press_terminal_explicit(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "press", "id": "xterm"}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    assert ("terminal", "xterm") in srv.called


# ---------------------------------------------------------------------------
# Jog → scroll sink
# ---------------------------------------------------------------------------


async def test_jog_emits_scroll(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "jog", "id": "scroll-strip", "delta": 42}))
        await ws.send(json.dumps({"type": "jog_end", "id": "scroll-strip", "velocity": 0}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    assert 42 in srv.scroll_sink.deltas


# ---------------------------------------------------------------------------
# Layout reload
# ---------------------------------------------------------------------------


async def test_reload_pushes_layout(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        async with aiohttp.ClientSession() as http:
            async with http.post(f"{srv.http_url}/reload") as r:
                result = await r.json()

        pushed = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))

    assert result["ok"] is True
    assert pushed["type"] == "layout"


# ---------------------------------------------------------------------------
# Button press → key injection
# ---------------------------------------------------------------------------


async def test_press_key(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "press", "id": "send-key"}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    assert len(srv.key_sink.events) == 1
    event = srv.key_sink.events[0]
    assert event["type"] == "key"
    assert event["keycodes"] == [29, 20]  # KEY_LEFTCTRL, KEY_T
