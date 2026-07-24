"""Tests for the deckd daemon at the WebSocket boundary."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
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
    # Host-identity fields (T-followup: settings-page diagnostics).
    # Values are environment-dependent; assert they exist and are strings.
    for field in ("hostname", "os", "desktop"):
        assert field in body, f"/health missing {field!r}"
        assert isinstance(body[field], str) and body[field]


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


async def test_press_terminal_auto(monkeypatch, tmp_path: Path) -> None:
    """``terminal: true`` dispatches to the terminal action (auto-detect)."""
    import deckd.actions as actions_mod
    from aiohttp.test_utils import TestServer
    from conftest import make_test_server

    called: list[tuple[str, str]] = []

    async def fake_shell(cmd: str) -> None:
        called.append(("shell", cmd))

    async def fake_terminal(target: bool | str = True) -> None:
        called.append(("terminal", str(target)))

    monkeypatch.setattr(actions_mod, "_run_shell", fake_shell)
    monkeypatch.setattr(actions_mod, "run_terminal", fake_terminal)

    (tmp_path / "default.yaml").write_text(
        """
match:
  - default
widgets:
  - id: open-terminal
    kind: button
    label: Open terminal
    grid: [0, 0, 1, 1]
    action:
      terminal: true
"""
    )

    server, _scroll, _key, _dbus = make_test_server(layouts_dir=tmp_path)
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    port = ts.port or 0
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)  # initial layout
            await ws.send(json.dumps({"type": "press", "id": "open-terminal"}))
            await asyncio.sleep(SIDE_EFFECT_WAIT)
    finally:
        await ts.close()
        await server.scroll.close()

    assert any(kind == "terminal" for kind, _ in called)


async def test_press_terminal_true(srv: ServerHandle) -> None:
    """A ``terminal: true`` widget dispatches to the auto-detect terminal."""
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "press", "id": "open-terminal"}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    assert ("terminal", "True") in srv.called


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
        await ws.send(json.dumps({"type": "press", "id": "audio-toggle"}))
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


# ---------------------------------------------------------------------------
# Chrome app badge (issue #41 / ADR-0007)
#
# A layout's optional ``display_name`` / ``theme`` / ``icon`` top-level
# attributes are relayed verbatim on every ``LayoutMessage`` so the
# client can render a branded app badge in the always-on bottom chrome.
# The daemon never interprets them; when the active layout omits them
# the fields are ``null`` (JSON ``null``, not absent) so the client has
# a stable shape to destructure.
# ---------------------------------------------------------------------------


async def test_layout_message_relays_app_badge_when_set(
    monkeypatch, tmp_path: Path
) -> None:
    """``display_name`` / ``theme`` / ``icon`` round-trip onto the wire."""
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
    grid: [0, 0, 1, 1]
"""
    )
    (tmp_path / "firefox.yaml").write_text(
        """
match:
  - firefox
display_name: Mozilla Firefox
theme: "#ff7139"
icon:
  source: simple-icons
  name: firefox
widgets:
  - id: back
    kind: button
    grid: [0, 0, 1, 1]
"""
    )

    server, _scroll, _key, _dbus = make_test_server(layouts_dir=tmp_path)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    port = test_server.port or 0
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            initial = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            # The default layout carries no chrome presentation -> all ``None``.
            assert initial["app"] == "default"
            assert initial["display_name"] is None
            assert initial["theme"] is None
            assert initial["icon"] is None

            async with aiohttp.ClientSession() as http:
                async with http.post(f"http://127.0.0.1:{port}/layout/firefox") as r:
                    assert r.status == 200

            pushed = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            assert pushed["app"] == "firefox"
            assert pushed["display_name"] == "Mozilla Firefox"
            assert pushed["theme"] == "#ff7139"
            assert pushed["icon"] == {"source": "simple-icons", "name": "firefox"}
    finally:
        await test_server.close()
        await server.scroll.close()


async def test_layout_message_app_badge_null_when_omitted(
    srv: ServerHandle,
) -> None:
    """Repo default layout omits the chrome fields; the message carries
    explicit ``null`` for each so the client has a stable shape."""
    async with ws_connected(srv) as (_, layout):
        assert "display_name" in layout and layout["display_name"] is None
        assert "theme" in layout and layout["theme"] is None
        assert "icon" in layout and layout["icon"] is None


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


# ---------------------------------------------------------------------------
# Trackpad mode (T8 / issue #14).
#
# WS carries three trackpad messages: ``pad`` (dx/dy movement), ``pad_tap``
# (single/two-finger click), and ``pad_drag`` (start/end of a button-held
# drag lock). The daemon forwards each to a pointer/click uinput sink.
# Client-side gesture recognition (tap-vs-drag, tap-and-a-half timing) is
# out of scope for the daemon; these tests exercise only the WS boundary.
# ---------------------------------------------------------------------------


async def test_pad_message_emits_pointer_delta(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "pad", "id": "trackpad", "dx": 5, "dy": -3}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    events = [e for e in srv.key_sink.events if e["type"] == "pointer"]
    assert events == [{"type": "pointer", "dx": 5, "dy": -3}]


async def test_pad_tap_one_finger_emits_left_click(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "pad_tap", "id": "trackpad", "fingers": 1}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    clicks = [e for e in srv.key_sink.events if e["type"] == "click"]
    assert clicks == [
        {"type": "click", "button": "left", "pressed": True},
        {"type": "click", "button": "left", "pressed": False},
    ]


async def test_pad_tap_two_fingers_emits_right_click(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "pad_tap", "id": "trackpad", "fingers": 2}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    clicks = [e for e in srv.key_sink.events if e["type"] == "click"]
    assert clicks == [
        {"type": "click", "button": "right", "pressed": True},
        {"type": "click", "button": "right", "pressed": False},
    ]


async def test_pad_drag_start_presses_left_button(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "pad_drag", "id": "trackpad", "state": "start"}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    clicks = [e for e in srv.key_sink.events if e["type"] == "click"]
    assert clicks == [{"type": "click", "button": "left", "pressed": True}]


async def test_pad_drag_end_releases_left_button(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "pad_drag", "id": "trackpad", "state": "end"}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    clicks = [e for e in srv.key_sink.events if e["type"] == "click"]
    assert clicks == [{"type": "click", "button": "left", "pressed": False}]


async def test_pad_drag_full_sequence(srv: ServerHandle) -> None:
    """End-to-end tap-and-a-half sequence: start drag, move, end drag."""
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "pad_drag", "id": "trackpad", "state": "start"}))
        await ws.send(json.dumps({"type": "pad", "id": "trackpad", "dx": 4, "dy": 0}))
        await ws.send(json.dumps({"type": "pad", "id": "trackpad", "dx": 0, "dy": 6}))
        await ws.send(json.dumps({"type": "pad_drag", "id": "trackpad", "state": "end"}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    types_in_order = [e["type"] for e in srv.key_sink.events]
    assert types_in_order == ["click", "pointer", "pointer", "click"]
    assert srv.key_sink.events[0] == {"type": "click", "button": "left", "pressed": True}
    assert srv.key_sink.events[-1] == {"type": "click", "button": "left", "pressed": False}


# ---------------------------------------------------------------------------
# Kbd mode (issue #23). The phone's IME forwards literal text as ``type``
# messages; named keys (strip + IME control keys) ride as ``key`` combos
# through the T2 parser. The daemon turns each glyph into one keystroke
# on the uinput sink. Client-side IME plumbing is out of scope; these
# tests exercise only the WS boundary.
# ---------------------------------------------------------------------------


async def test_type_message_emits_per_char_keystrokes(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "type", "text": "aB!"}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    keys = [e for e in srv.key_sink.events if e["type"] == "key"]
    assert keys == [
        {"type": "key", "keycodes": [30]},  # a
        {"type": "key", "keycodes": [42, 48]},  # B = Shift+b
        {"type": "key", "keycodes": [42, 2]},  # ! = Shift+1
    ]


async def test_type_message_drops_non_ascii(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        await ws.send(json.dumps({"type": "type", "text": "aéb"}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    keys = [e for e in srv.key_sink.events if e["type"] == "key"]
    assert keys == [
        {"type": "key", "keycodes": [30]},
        {"type": "key", "keycodes": [48]},
    ]


async def test_key_message_emits_named_key(srv: ServerHandle) -> None:
    async with ws_connected(srv) as (ws, _):
        for combo in ("enter", "backspace", "tab", "esc", "up", "down", "left", "right"):
            await ws.send(json.dumps({"type": "key", "combo": combo}))
        await asyncio.sleep(SIDE_EFFECT_WAIT)

    keys = [e for e in srv.key_sink.events if e["type"] == "key"]
    assert keys == [
        {"type": "key", "keycodes": [28]},  # enter
        {"type": "key", "keycodes": [14]},  # backspace
        {"type": "key", "keycodes": [15]},  # tab
        {"type": "key", "keycodes": [1]},  # esc
        {"type": "key", "keycodes": [103]},  # up
        {"type": "key", "keycodes": [108]},  # down
        {"type": "key", "keycodes": [105]},  # left
        {"type": "key", "keycodes": [106]},  # right
    ]


# ---------------------------------------------------------------------------
# Layouts hot-reload: watcher + error-tolerant reload.
#
# Layouts are user configuration, so the daemon watches ``layouts/*.y[a]ml``
# and reloads on change. A parse/schema error keeps the last-good layouts
# live but pushes a ``LayoutMessage`` with ``error`` set so the client can
# render a diagnostic in place of the widget grid.
# ---------------------------------------------------------------------------


VALID_DEFAULT = """
match:
  - default
widgets:
  - id: home
    kind: button
    label: Home
    grid: [0, 0, 1, 1]
"""

VALID_DEFAULT_V2 = """
match:
  - default
widgets:
  - id: home-v2
    kind: button
    label: Home v2
    grid: [0, 0, 1, 1]
"""

INVALID_YAML = """
match:
  - default
widgets:
  - id: broken
    kind: button
    grid: [0, 0, 1, 1]
    action:
      key: 42  # wrong type; schema says str
      unknown_field: nope
"""


@asynccontextmanager
async def _serve(monkeypatch, tmp_path: Path) -> AsyncIterator[tuple[int, "Server"]]:
    """Boot a server against ``tmp_path`` with the layout watcher running."""
    import deckd.actions as actions_mod
    from aiohttp.test_utils import TestServer
    from conftest import make_test_server

    async def _fake_shell(cmd: str) -> None:
        return None

    monkeypatch.setattr(actions_mod, "_run_shell", _fake_shell)

    server, _scroll, _key, _dbus = make_test_server(layouts_dir=tmp_path)
    server.start_layouts_watcher()
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    try:
        yield ts.port or 0, server
    finally:
        await server.stop()
        await ts.close()


async def _next_layout(ws, timeout: float = 3.0) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))


async def test_reload_with_bad_yaml_keeps_daemon_alive_and_pushes_error(
    monkeypatch, tmp_path: Path
) -> None:
    """POST /reload with broken YAML must not raise; error travels on the WS."""
    (tmp_path / "default.yaml").write_text(VALID_DEFAULT)

    async with _serve(monkeypatch, tmp_path) as (port, _server):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            initial = await _next_layout(ws)
            assert initial["widgets"][0]["id"] == "home"
            assert initial.get("error") in (None, "")

            (tmp_path / "default.yaml").write_text(INVALID_YAML)

            async with aiohttp.ClientSession() as http:
                async with http.post(f"http://127.0.0.1:{port}/reload") as r:
                    body = await r.json()
                    # 400 signals bad config; daemon is still up.
                    assert r.status == 400
                    assert body["ok"] is False
                    assert "error" in body

            pushed = await _next_layout(ws)
            assert pushed["type"] == "layout"
            assert pushed["error"]
            assert pushed["widgets"] == []


async def test_reload_after_fixing_yaml_clears_error(
    monkeypatch, tmp_path: Path
) -> None:
    """Once the YAML is valid again, the next reload restores the grid."""
    (tmp_path / "default.yaml").write_text(VALID_DEFAULT)

    async with _serve(monkeypatch, tmp_path) as (port, _server):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await _next_layout(ws)  # initial

            (tmp_path / "default.yaml").write_text(INVALID_YAML)
            async with aiohttp.ClientSession() as http:
                async with http.post(f"http://127.0.0.1:{port}/reload") as r:
                    assert r.status == 400
            broken = await _next_layout(ws)
            assert broken["error"]

            (tmp_path / "default.yaml").write_text(VALID_DEFAULT_V2)
            async with aiohttp.ClientSession() as http:
                async with http.post(f"http://127.0.0.1:{port}/reload") as r:
                    assert r.status == 200

            fixed = await _next_layout(ws)
            assert fixed.get("error") in (None, "")
            assert fixed["widgets"][0]["id"] == "home-v2"


async def test_layouts_watcher_reloads_on_yaml_edit(
    monkeypatch, tmp_path: Path
) -> None:
    """Editing a YAML file in the layouts dir triggers an auto-push."""
    (tmp_path / "default.yaml").write_text(VALID_DEFAULT)

    async with _serve(monkeypatch, tmp_path) as (port, _server):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            initial = await _next_layout(ws)
            assert initial["widgets"][0]["id"] == "home"

            (tmp_path / "default.yaml").write_text(VALID_DEFAULT_V2)

            # The watcher polls; give it real time to react before failing.
            pushed = await _next_layout(ws, timeout=5.0)
            assert pushed["type"] == "layout"
            assert pushed.get("error") in (None, "")
            assert pushed["widgets"][0]["id"] == "home-v2"


async def test_layouts_watcher_bad_edit_pushes_error_not_crash(
    monkeypatch, tmp_path: Path
) -> None:
    """A broken save on disk pushes the error state; daemon keeps serving."""
    (tmp_path / "default.yaml").write_text(VALID_DEFAULT)

    async with _serve(monkeypatch, tmp_path) as (port, _server):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await _next_layout(ws)  # initial

            (tmp_path / "default.yaml").write_text(INVALID_YAML)
            pushed = await _next_layout(ws, timeout=5.0)
            assert pushed["error"]
            assert pushed["widgets"] == []

            # Fixing the file drives the client back to a good grid.
            (tmp_path / "default.yaml").write_text(VALID_DEFAULT_V2)
            recovered = await _next_layout(ws, timeout=5.0)
            assert recovered.get("error") in (None, "")
            assert recovered["widgets"][0]["id"] == "home-v2"
