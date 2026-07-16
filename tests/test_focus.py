"""Tests for per-app layout switching driven by the focus watcher.

Seam under test: when the focused application changes, the daemon pushes
the matching layout to every connected client. New clients see the
layout for the currently focused app at connect-time.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiohttp
import pytest
import websockets

from conftest import FakeFocusBackend, ServerHandle

SIDE_EFFECT_WAIT = 0.05
LAYOUT_TIMEOUT = 2.0


# ---------------------------------------------------------------------------
# Helper: build a per-test layouts directory
# ---------------------------------------------------------------------------


FIREFOX_YAML = """
match:
  - firefox
widgets:
  - id: back
    kind: button
    label: Back
    grid: [0, 0, 1, 1]
    action:
      key: "alt+Left"
  - id: forward
    kind: button
    label: Forward
    grid: [1, 0, 1, 1]
    action:
      key: "alt+Right"
"""

TERMINAL_YAML = """
match:
  - org.gnome.Console
widgets:
  - id: new-tab
    kind: button
    label: New tab
    grid: [0, 0, 1, 1]
    action:
      key: "ctrl+shift+t"
"""

DEFAULT_YAML = """
match:
  - default
widgets:
  - id: home
    kind: button
    label: Home
    grid: [0, 0, 1, 1]
    action:
      shell: "xdg-open https://example.com"
"""


def _seed_layouts(tmp_path: Path) -> Path:
    (tmp_path / "firefox.yaml").write_text(FIREFOX_YAML)
    (tmp_path / "terminal.yaml").write_text(TERMINAL_YAML)
    (tmp_path / "default.yaml").write_text(DEFAULT_YAML)
    return tmp_path


async def _recv_layout(ws) -> dict:
    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=LAYOUT_TIMEOUT))
    assert msg["type"] == "layout", f"expected layout, got {msg}"
    return msg


async def _recv_eventual_layout(ws) -> dict:
    """Drain any pending messages until a layout arrives (or timeout)."""
    deadline = asyncio.get_event_loop().time() + LAYOUT_TIMEOUT
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise AssertionError("timed out waiting for layout message")
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
        if msg.get("type") == "layout":
            return msg


# ---------------------------------------------------------------------------
# Fixture: a server with FakeFocusBackend wired in
# ---------------------------------------------------------------------------


@pytest.fixture
def focus_layouts_dir(tmp_path: Path) -> Path:
    return _seed_layouts(tmp_path)


@asynccontextmanager
async def _focus_srv(
    monkeypatch,
    layouts_dir: Path,
    *,
    initial_focus: str = "firefox",
) -> AsyncIterator[tuple[ServerHandle, FakeFocusBackend]]:
    """Build a Server backed by a FakeFocusBackend.

    Returns (handle, focus_backend). The watcher is started immediately
    so the initial focus state resolves and is the layout new clients
    receive.
    """
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

    focus = FakeFocusBackend()
    server, scroll, key_sink, dbus_factory = make_test_server(
        layouts_dir=layouts_dir, focus_backend=focus
    )
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()

    handle = ServerHandle(
        server=server,
        scroll_sink=scroll,
        key_sink=key_sink,
        called=called,
        port=test_server.port or 0,
        dbus_buses=dbus_factory.buses,
        dbus_calls=dbus_factory.calls,
    )

    # Seed initial focus and start watcher.
    from deckd.platform import AppInfo

    if initial_focus == "firefox":
        await focus.push(AppInfo(app_id="firefox", wm_class="firefox"))
    elif initial_focus == "terminal":
        await focus.push(AppInfo(app_id="org.gnome.Console", wm_class="org.gnome.Console"))
    elif initial_focus == "default":
        await focus.push(AppInfo(app_id=None, wm_class="totally.unknown.app"))
    else:
        raise ValueError(initial_focus)
    watcher = asyncio.create_task(server.run_focus_watcher())

    try:
        yield handle, focus
    finally:
        watcher.cancel()
        try:
            await watcher
        except (asyncio.CancelledError, Exception):
            pass
        await test_server.close()
        await server.scroll.close()


# ---------------------------------------------------------------------------
# Initial layout on connect
# ---------------------------------------------------------------------------


async def test_new_client_receives_firefox_layout(
    monkeypatch, focus_layouts_dir: Path
) -> None:
    async with _focus_srv(monkeypatch, focus_layouts_dir, initial_focus="firefox") as (srv, _focus):
        async with websockets.connect(srv.ws_url) as ws:
            layout = await _recv_layout(ws)
    assert layout["app"] == "firefox"
    ids = [w["id"] for w in layout["widgets"]]
    assert "back" in ids
    assert "forward" in ids


async def test_new_client_receives_default_when_focus_unmatched(
    monkeypatch, focus_layouts_dir: Path
) -> None:
    async with _focus_srv(monkeypatch, focus_layouts_dir, initial_focus="default") as (srv, _focus):
        async with websockets.connect(srv.ws_url) as ws:
            layout = await _recv_layout(ws)
    assert layout["app"] == "default"
    ids = [w["id"] for w in layout["widgets"]]
    assert "home" in ids


# ---------------------------------------------------------------------------
# Live focus changes push the right layout
# ---------------------------------------------------------------------------


async def test_focus_change_pushes_new_layout_to_existing_clients(
    monkeypatch, focus_layouts_dir: Path
) -> None:
    from deckd.platform import AppInfo

    async with _focus_srv(monkeypatch, focus_layouts_dir, initial_focus="firefox") as (srv, focus):
        async with websockets.connect(srv.ws_url) as ws:
            first = await _recv_layout(ws)
            assert first["app"] == "firefox"

            # Switch focus to terminal.
            await focus.push(AppInfo(app_id="org.gnome.Console", wm_class="org.gnome.Console"))
            pushed = await _recv_eventual_layout(ws)
            assert pushed["app"] == "org.gnome.Console"
            ids = [w["id"] for w in pushed["widgets"]]
            assert "new-tab" in ids


async def test_focus_change_pushes_default_when_no_match(
    monkeypatch, focus_layouts_dir: Path
) -> None:
    from deckd.platform import AppInfo

    async with _focus_srv(monkeypatch, focus_layouts_dir, initial_focus="firefox") as (srv, focus):
        async with websockets.connect(srv.ws_url) as ws:
            first = await _recv_layout(ws)
            assert first["app"] == "firefox"

            await focus.push(AppInfo(app_id="org.kde.dolphin", wm_class="dolphin"))
            pushed = await _recv_eventual_layout(ws)
            assert pushed["app"] == "default"


async def test_focus_change_pushes_to_multiple_clients(
    monkeypatch, focus_layouts_dir: Path
) -> None:
    from deckd.platform import AppInfo

    async with _focus_srv(monkeypatch, focus_layouts_dir, initial_focus="firefox") as (srv, focus):
        async with websockets.connect(srv.ws_url) as ws_a, websockets.connect(srv.ws_url) as ws_b:
            await _recv_layout(ws_a)
            await _recv_layout(ws_b)

            await focus.push(AppInfo(app_id="org.gnome.Console", wm_class="org.gnome.Console"))

            pushed_a = await _recv_eventual_layout(ws_a)
            pushed_b = await _recv_eventual_layout(ws_b)

    assert pushed_a["app"] == "org.gnome.Console"
    assert pushed_b["app"] == "org.gnome.Console"


async def test_no_push_when_layout_unchanged(
    monkeypatch, focus_layouts_dir: Path
) -> None:
    """If the new focus resolves to the same layout, do not push."""
    from deckd.platform import AppInfo

    async with _focus_srv(monkeypatch, focus_layouts_dir, initial_focus="firefox") as (srv, focus):
        async with websockets.connect(srv.ws_url) as ws:
            first = await _recv_layout(ws)
            assert first["app"] == "firefox"

            # Different focus, but same matching layout (wm_class variant).
            await focus.push(AppInfo(app_id=None, wm_class="firefox"))
            await asyncio.sleep(0.1)

            # The WS should be silent — the recv would block past the
            # timeout, which is exactly what we assert.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(ws.recv(), timeout=0.3)


async def test_no_focus_backend_serves_default_layout(
    monkeypatch, focus_layouts_dir: Path
) -> None:
    """When the daemon is started without a focus backend it still serves
    the default layout to new clients (used by ``--no-focus`` mode and
    by the smoke test)."""
    import deckd.actions as actions_mod
    from aiohttp.test_utils import TestServer
    from conftest import make_test_server

    called: list[tuple[str, str]] = []

    async def fake_shell(cmd: str) -> None:
        called.append(("shell", cmd))

    monkeypatch.setattr(actions_mod, "_run_shell", fake_shell)

    server, _scroll, _key, _dbus = make_test_server(
        layouts_dir=focus_layouts_dir, focus_backend=None
    )
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    port = test_server.port
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            layout = await _recv_layout(ws)
    finally:
        await test_server.close()
        await server.scroll.close()

    assert layout["app"] == "default"
    assert server.current_app_id == "default"


async def test_reload_picks_up_new_layout_files(
    monkeypatch, focus_layouts_dir: Path
) -> None:
    """Adding a new YAML file at runtime is visible after /reload."""
    import deckd.actions as actions_mod
    from aiohttp.test_utils import TestServer
    from conftest import make_test_server

    called: list[tuple[str, str]] = []

    async def fake_shell(cmd: str) -> None:
        called.append(("shell", cmd))

    monkeypatch.setattr(actions_mod, "_run_shell", fake_shell)

    server, _scroll, _key, _dbus = make_test_server(
        layouts_dir=focus_layouts_dir, focus_backend=None
    )
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    port = test_server.port
    try:
        # New layout file is dropped in after startup.
        (focus_layouts_dir / "new-app.yaml").write_text(
            """
match:
  - totally-new-app
widgets:
  - id: brand-new
    kind: button
    label: Brand new
    grid: [0, 0, 1, 1]
"""
        )
        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/reload") as r:
                body = await r.json()
        assert body["ok"] is True
        assert "totally-new-app" in server.layouts
    finally:
        await test_server.close()
        await server.scroll.close()


async def test_reload_falls_back_to_default_when_current_app_removed(
    monkeypatch, focus_layouts_dir: Path
) -> None:
    """If the layout for the currently-focused app is deleted, /reload
    should fall back to the default layout rather than leaving a stale
    app_id pointing at nothing."""
    import deckd.actions as actions_mod
    from aiohttp.test_utils import TestServer
    from conftest import make_test_server

    called: list[tuple[str, str]] = []

    async def fake_shell(cmd: str) -> None:
        called.append(("shell", cmd))

    monkeypatch.setattr(actions_mod, "_run_shell", fake_shell)

    server, _scroll, _key, _dbus = make_test_server(
        layouts_dir=focus_layouts_dir, focus_backend=None
    )
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    port = test_server.port
    try:
        # Pretend firefox is the current focus.
        server._current_app_id = "firefox"  # type: ignore[attr-defined]
        server._current_layout = server.layouts["firefox"]  # type: ignore[attr-defined]

        # Delete the firefox layout.
        (focus_layouts_dir / "firefox.yaml").unlink()

        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/reload") as r:
                body = await r.json()

        assert body["ok"] is True
        assert server.current_app_id == "default"
    finally:
        await test_server.close()
        await server.scroll.close()


# ---------------------------------------------------------------------------
# Auto-ignore the deckd client window (T5/issue #11)
#
# The T4 spec lists this as a separate ticket (#11 / T5). We do not wire
# it here — but the seam where it'd plug in (the focus handler) is
# already the right one. Asserting that the watcher *does* react to focus
# changes on the focused window is enough for T4.
# ---------------------------------------------------------------------------
