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


# ---------------------------------------------------------------------------
# Button press → D-Bus dispatch
# ---------------------------------------------------------------------------


async def test_press_dbus(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "press", "id": "mpris-toggle"}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    assert len(srv.dbus_calls) == 1
    call = srv.dbus_calls[0]
    assert call["destination"] == "org.mpris.MediaPlayer2.vlc"
    assert call["path"] == "/org/mpris/MediaPlayer2"
    assert call["interface"] == "org.mpris.MediaPlayer2.Player"
    assert call["method"] == "PlayPause"
    assert call["args"] == []
    # Bus is closed after the call.
    bus = srv.dbus_buses[0]
    assert bus.connected is True
    assert bus.disconnected is True


# ---------------------------------------------------------------------------
# Layout override endpoint (T5/issue #11): POST /layout/<name> force-switches
# all connected clients to a named layout regardless of focus.
# ---------------------------------------------------------------------------


async def test_layout_override_switches_clients_to_named_layout(
    srv: ServerHandle,
) -> None:
    async with ws_connected(srv) as (ws, initial):
        assert initial["app"] == "default"

        async with aiohttp.ClientSession() as http:
            async with http.post(f"{srv.http_url}/layout/firefox") as r:
                result = await r.json()

        pushed = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))

    assert result["ok"] is True
    assert pushed["type"] == "layout"
    assert pushed["app"] == "firefox"
    ids = [w["id"] for w in pushed["widgets"]]
    assert "back" in ids
    assert srv.server.current_app_id == "firefox"


async def test_layout_override_to_default(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        async with aiohttp.ClientSession() as http:
            async with http.post(f"{srv.http_url}/layout/default") as r:
                result = await r.json()

        pushed = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))

    assert result["ok"] is True
    assert pushed["app"] == "default"
    assert srv.server.current_app_id == "default"


async def test_layout_override_unknown_name_returns_error(srv: ServerHandle) -> None:
    async with aiohttp.ClientSession() as http:
        async with http.post(f"{srv.http_url}/layout/nonexistent") as r:
            assert r.status == 404
            body = await r.json()

    assert body["ok"] is False
    assert "nonexistent" in body["error"]


# ---------------------------------------------------------------------------
# Persistent jogstrip flag in LayoutMessage (T6/issue #12)
#
# The daemon adds ``jogstrip_enabled`` to every LayoutMessage: True by
# default, False when the active layout's YAML declares ``jogstrip: false``.
# The client chrome uses this to hide the always-on right-side strip.
# ---------------------------------------------------------------------------


async def test_layout_message_defaults_jogstrip_enabled_true(
    srv: ServerHandle,
) -> None:
    """Repo default layout omits ``jogstrip``; the message must carry True."""
    async with ws_connected(srv) as (_, layout):
        assert layout["jogstrip_enabled"] is True


async def test_layout_message_carries_jogstrip_enabled_false_when_suppressed(
    monkeypatch, tmp_path: Path
) -> None:
    """A layout with ``jogstrip: false`` pushes ``jogstrip_enabled: False``."""
    import deckd.actions as actions_mod
    from aiohttp.test_utils import TestServer
    from conftest import make_test_server

    async def fake_shell(cmd: str) -> None:
        return None

    monkeypatch.setattr(actions_mod, "_run_shell", fake_shell)

    (tmp_path / "default.yaml").write_text(
        """
match:
  - default
widgets:
  - id: home
    kind: button
    label: Home
    grid: [0, 0, 1, 1]
"""
    )
    (tmp_path / "nochrome.yaml").write_text(
        """
match:
  - nochrome
jogstrip: false
widgets:
  - id: scroll-own
    kind: button
    label: Scroll own
    grid: [0, 0, 1, 1]
"""
    )

    server, _scroll, _key, _dbus = make_test_server(layouts_dir=tmp_path)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    port = test_server.port or 0
    try:
        # Force-switch to the chrome-suppressed layout.
        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/layout/nochrome") as r:
                assert r.status == 200

        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            layout = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
    finally:
        await test_server.close()
        await server.scroll.close()

    assert layout["type"] == "layout"
    assert layout["app"] == "nochrome"
    assert layout["jogstrip_enabled"] is False


async def test_layout_message_carries_jogstrip_enabled_true_when_explicit(
    monkeypatch, tmp_path: Path
) -> None:
    """A layout that explicitly sets ``jogstrip: true`` also reports True."""
    import deckd.actions as actions_mod
    from aiohttp.test_utils import TestServer
    from conftest import make_test_server

    async def fake_shell(cmd: str) -> None:
        return None

    monkeypatch.setattr(actions_mod, "_run_shell", fake_shell)

    (tmp_path / "default.yaml").write_text(
        """
match:
  - default
jogstrip: true
widgets:
  - id: home
    kind: button
    label: Home
    grid: [0, 0, 1, 1]
"""
    )

    server, _scroll, _key, _dbus = make_test_server(layouts_dir=tmp_path)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    port = test_server.port or 0
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            layout = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
    finally:
        await test_server.close()
        await server.scroll.close()

    assert layout["jogstrip_enabled"] is True
