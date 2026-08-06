"""WebSocket round-trip tests for the running-windows chrome list
(issues #120 / #126).

Seam under test: the full chain from the platform backend's
``watch_windows`` iterator -> the daemon's broadcast loop -> the
WebSocket as a ``running_windows`` frame, plus the new-session
catch-up via ``push_running_windows_snapshot``. The test boots a real
``Server`` with a fake focus backend whose ``watch_windows`` is driven
by the test (no real D-Bus, no GNOME Shell).

The shape mirrors :mod:`tests.test_chrome_media_websocket` — same
broadcast / snapshot / connect-timing pattern, different message type.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import websockets
from aiohttp.test_utils import TestServer

sys.path.insert(0, str(Path(__file__).parent))

from conftest import FakeFocusBackend, make_test_server
from deckd.platform import WindowInfo

if TYPE_CHECKING:
    from deckd.server import Server


class FakeWindowsBackend(FakeFocusBackend):
    """FakeFocusBackend with a controllable ``watch_windows`` iterator.

    Reuses the focus backend's ``start`` / ``stop`` / ``capabilities``
    surface so the daemon's wiring stays exercised against a single
    fake. ``capabilities`` advertises ``watch_windows`` so the daemon
    actually starts the watcher (issue #121).
    """

    def __init__(self) -> None:
        super().__init__()
        self._windows_queue: asyncio.Queue[list[WindowInfo]] = asyncio.Queue()
        self._windows_snapshots: list[list[WindowInfo]] = []
        self._capabilities = frozenset({"watch_active_app", "watch_windows"})

    async def watch_windows(
        self, *, interval_s: float = 0.1
    ) -> AsyncIterator[list[WindowInfo]]:
        while True:
            snapshot = await self._windows_queue.get()
            self._windows_snapshots.append(snapshot)
            yield snapshot

    async def push_windows(self, snapshot: list[WindowInfo]) -> None:
        await self._windows_queue.put(snapshot)


async def _drain_initial(ws) -> None:
    """Drain the layout frame a fresh client gets.

    The chrome windows list's snapshot lives on the running-windows
    watcher (separate from the layout pump), so the warm-up sequence
    is just ``layout`` then ``running_windows``. Subsequent test frames
    land on a clean WebSocket.
    """
    assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "layout"


async def _next_running_windows(ws) -> dict:
    """Return the next ``running_windows`` frame received over the socket."""
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 2))
        if msg["type"] == "running_windows":
            return msg


async def _boot_running_windows_server(
    tmp_path: Path, backend: FakeWindowsBackend
) -> tuple[TestServer, "Server"]:
    """Stand up a daemon with the supplied fake backend."""
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: x
    kind: blank
"""
    )
    (tmp_path / "firefox.yaml").write_text(
        """
match: [firefox]
display_name: Firefox
icon:
  source: simple-icons
  name: firefox
widgets:
  - id: x
    kind: blank
"""
    )
    server, *_ = make_test_server(layouts_dir=tmp_path, focus_backend=backend)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    server.start_focus_watcher()
    server.start_windows_watcher()
    return test_server, server


async def test_running_windows_emits_on_snapshot_change(tmp_path: Path) -> None:
    """A genuine window-list change pushes a ``running_windows`` frame
    over the WebSocket. Verifies the watcher → broadcast wiring.

    The two-window snapshot exercises the per-push label derivation:
    ``firefox`` resolves to the Firefox layout (matched), ``xterm``
    falls through to the default (raw ``wm_class``). The matched
    layout's icon rides on row 0; row 1's icon is ``null``
    (decision 6)."""
    backend = FakeWindowsBackend()
    test_server, server = await _boot_running_windows_server(tmp_path, backend)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            await _drain_initial(ws)
            await backend.push_windows(
                [
                    WindowInfo(
                        window_id="1",
                        wm_class="firefox",
                        gtk_application_id=None,
                        sandboxed_app_id=None,
                        title="YouTube",
                        workspace=0,
                        minimized=False,
                    ),
                    WindowInfo(
                        window_id="2",
                        wm_class="xterm",
                        gtk_application_id=None,
                        sandboxed_app_id=None,
                        title="bash",
                        workspace=0,
                        minimized=False,
                    ),
                ]
            )
            frame = await _next_running_windows(ws)
            assert frame == {
                "type": "running_windows",
                "windows": [
                    {
                        "window_id": "1",
                        "label": "Firefox",
                        "icon": {"source": "simple-icons", "name": "firefox"},
                    },
                    {"window_id": "2", "label": "xterm", "icon": None},
                ],
            }
    finally:
        await server.stop()
        await test_server.close()


async def test_running_windows_does_not_emit_on_identical_snapshot(
    tmp_path: Path,
) -> None:
    """The watcher dedupes identical snapshots — a desktop that hasn't
    changed since the last enumeration doesn't keep the chrome list
    re-rendering every poll tick. Mirrors the chrome-media debounce,
    but in user-space (the backend's enumeration isn't debounced by
    event type the way MPRIS PropertiesChanged is)."""
    backend = FakeWindowsBackend()
    test_server, server = await _boot_running_windows_server(tmp_path, backend)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            await _drain_initial(ws)
            snapshot = [
                WindowInfo(
                    window_id="1",
                    wm_class="firefox",
                    gtk_application_id=None,
                    sandboxed_app_id=None,
                    title="YouTube",
                    workspace=0,
                    minimized=False,
                ),
            ]
            await backend.push_windows(snapshot)
            first = await _next_running_windows(ws)
            assert len(first["windows"]) == 1

            # Second push of the same snapshot must NOT produce a
            # frame. We wait briefly; a timeout is the success path,
            # any frame received is the failure.
            await backend.push_windows(snapshot)
            try:
                stray = await asyncio.wait_for(ws.recv(), 0.3)
            except asyncio.TimeoutError:
                stray = None
            assert stray is None, f"unexpected duplicate frame: {stray}"
    finally:
        await server.stop()
        await test_server.close()


async def test_running_windows_snapshot_replay_to_late_session(
    tmp_path: Path,
) -> None:
    """A session that connects mid-lifetime still gets the current
    windows snapshot — same rationale as ``push_chrome_media_snapshot``.
    Without this a reload / second client would see an empty list until
    the next genuine change."""
    backend = FakeWindowsBackend()
    test_server, server = await _boot_running_windows_server(tmp_path, backend)
    try:
        # Seed the cache with a snapshot BEFORE any client connects.
        await backend.push_windows(
            [
                WindowInfo(
                    window_id="1",
                    wm_class="firefox",
                    gtk_application_id=None,
                    sandboxed_app_id=None,
                    title="YouTube",
                    workspace=0,
                    minimized=False,
                ),
            ]
        )
        # Let the watcher's first iteration land.
        await asyncio.sleep(0.05)

        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            # After the layout frame, the snapshot replay fires.
            assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "layout"
            frame = json.loads(await asyncio.wait_for(ws.recv(), 2))
            assert frame == {
                "type": "running_windows",
                "windows": [
                    {
                        "window_id": "1",
                        "label": "Firefox",
                        "icon": {"source": "simple-icons", "name": "firefox"},
                    }
                ],
            }
    finally:
        await server.stop()
        await test_server.close()


async def test_running_windows_skipped_on_backend_without_capability(
    tmp_path: Path,
) -> None:
    """A backend whose ``capabilities()`` does not include
    ``"watch_windows"`` (X11, macOS, headless) never produces a
    ``running_windows`` frame. The chrome view's "unsupported on this
    platform" empty state is the wire-level signal — issue #120,
    decision 8."""
    backend = FakeWindowsBackend()
    # Strip the capability so the watcher is a no-op at startup.
    backend._capabilities = frozenset({"watch_active_app"})
    test_server, server = await _boot_running_windows_server(tmp_path, backend)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            await _drain_initial(ws)
            # No frame should arrive even if the backend were to push
            # something (it can't — watcher never started).
            try:
                stray = await asyncio.wait_for(ws.recv(), 0.3)
            except asyncio.TimeoutError:
                stray = None
            assert stray is None, f"unexpected frame on disabled backend: {stray}"
    finally:
        await server.stop()
        await test_server.close()


async def test_running_windows_broadcasts_to_all_sessions(tmp_path: Path) -> None:
    """The windows list is global chrome (decision 7) — every connected
    session receives the frame regardless of which view it pinned.
    Two simultaneous WS clients both see the snapshot change."""
    backend = FakeWindowsBackend()
    test_server, server = await _boot_running_windows_server(tmp_path, backend)
    url = f"ws://127.0.0.1:{test_server.port}/ws"
    try:
        async with websockets.connect(url) as first, websockets.connect(url) as second:
            await _drain_initial(first)
            await _drain_initial(second)
            await backend.push_windows(
                [
                    WindowInfo(
                        window_id="1",
                        wm_class="xterm",
                        gtk_application_id=None,
                        sandboxed_app_id=None,
                        title="bash",
                        workspace=0,
                        minimized=False,
                    ),
                ]
            )
            frame_a = await _next_running_windows(first)
            frame_b = await _next_running_windows(second)
            assert frame_a == frame_b
            assert frame_a["windows"][0]["label"] == "xterm"
    finally:
        await server.stop()
        await test_server.close()