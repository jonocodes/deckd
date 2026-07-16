"""Shared test fixtures for deckd daemon tests."""
from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestServer

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

from deckd.input import ScrollController
from deckd.platform import AppInfo
from deckd.server import Server

LAYOUTS_PATH = Path(__file__).parent.parent / "layouts" / "default.yaml"


# ---------------------------------------------------------------------------
# Fake sinks
# ---------------------------------------------------------------------------


class FakeScrollSink:
    """Records scroll deltas emitted by ScrollController."""

    def __init__(self) -> None:
        self.deltas: list[int] = []

    def emit_scroll(self, delta: int) -> None:
        self.deltas.append(delta)

    def close(self) -> None:
        pass


class FakePointerSink:
    """Records pointer and key events emitted by a future uinput device.

    Each entry is a dict: {"type": "key"|"pointer"|"click", ...}
    Added in T1 for future tickets; not wired to the daemon yet.
    """

    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit_key(self, keycodes: list[str]) -> None:
        self.events.append({"type": "key", "keycodes": keycodes})

    def emit_pointer(self, dx: int, dy: int) -> None:
        self.events.append({"type": "pointer", "dx": dx, "dy": dy})

    def emit_click(self, button: str, pressed: bool) -> None:
        self.events.append({"type": "click", "button": button, "pressed": pressed})

    def close(self) -> None:
        pass


class FakeFocusBackend:
    """Async iterator of AppInfo values driven by the test.

    Usage::

        backend = FakeFocusBackend()
        await backend.push(AppInfo(app_id="firefox", wm_class="firefox"))
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[AppInfo] = asyncio.Queue()

    async def push(self, app_info: AppInfo) -> None:
        await self._queue.put(app_info)

    async def watch_active_app(self, *, interval_s: float = 0.1) -> AsyncIterator[AppInfo]:
        while True:
            yield await self._queue.get()


# ---------------------------------------------------------------------------
# Server fixture
# ---------------------------------------------------------------------------


@dataclass
class ServerHandle:
    """Everything a test needs to interact with a running daemon instance."""

    server: Server
    scroll_sink: FakeScrollSink
    called: list[tuple[str, str]]  # ("shell"|"terminal", value)
    port: int

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/ws"

    @property
    def http_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@pytest_asyncio.fixture
async def srv(monkeypatch) -> AsyncIterator[ServerHandle]:
    """Start a Server on a random port with all real I/O replaced by fakes."""
    import deckd.actions as actions_mod

    called: list[tuple[str, str]] = []

    async def fake_shell(cmd: str) -> None:
        called.append(("shell", cmd))

    async def fake_terminal(target: bool | str = True) -> None:
        called.append(("terminal", str(target)))

    monkeypatch.setattr(actions_mod, "_run_shell", fake_shell)
    monkeypatch.setattr(actions_mod, "run_terminal", fake_terminal)

    scroll_sink = FakeScrollSink()

    server = Server(
        layouts_path=LAYOUTS_PATH,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(scroll_sink),
    )

    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    port = test_server.port

    handle = ServerHandle(
        server=server,
        scroll_sink=scroll_sink,
        called=called,
        port=port,
    )
    yield handle

    await test_server.close()
    await server.scroll.close()
