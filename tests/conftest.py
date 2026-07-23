"""Shared test fixtures for deckd daemon tests."""
from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestServer

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

from deckd.input import ScrollController
from deckd.platform import AppInfo
from deckd.server import Server

LAYOUTS_DIR = Path(__file__).parent.parent / "layouts"


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
    """Records pointer and key events emitted by a uinput device.

    Each entry is a dict: {"type": "key"|"pointer"|"click", ...}
    """

    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit_key(self, keycodes: list[int]) -> None:
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

    Duck-types ``PlatformBackend``: implements ``start`` / ``stop`` as
    no-ops so the daemon's run_focus_watcher — which now awaits
    ``backend.start()`` before the first poll (issue #31, KDE backend
    owns a session-bus name there) — works against this fake unchanged.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[AppInfo] = asyncio.Queue()

    async def start(self) -> None:  # mirror PlatformBackend.start no-op
        pass

    async def stop(self) -> None:  # mirror PlatformBackend.stop no-op
        pass

    async def push(self, app_info: AppInfo) -> None:
        await self._queue.put(app_info)

    async def watch_active_app(self, *, interval_s: float = 0.1) -> AsyncIterator[AppInfo]:
        while True:
            yield await self._queue.get()


class FakeDbusBus:
    """Stand-in for ``dbus_fast.aio.MessageBus`` at the ActionContext seam.

    Records every ``call(message)`` into the shared ``all_calls`` list passed
    at construction time so a test can assert on the destination, path,
    interface, method, and body across every bus opened. Optionally raises
    a configured exception from ``call`` to exercise the error path.
    """

    def __init__(
        self,
        bus_type: Any,
        all_calls: list[dict] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.bus_type = bus_type
        self.all_calls = all_calls if all_calls is not None else []
        self._error = error
        self.connected = False
        self.disconnected = False

    async def connect(self) -> "FakeDbusBus":
        self.connected = True
        return self

    def disconnect(self) -> None:
        self.disconnected = True

    async def call(self, message: Any) -> Any:
        if self._error is not None:
            raise self._error
        self.all_calls.append(
            {
                "bus_type": self.bus_type,
                "destination": message.destination,
                "path": message.path,
                "interface": message.interface,
                "method": message.member,
                "args": list(message.body or []),
            }
        )
        return None


class FakeDbusBusFactory:
    """Callable returning ``FakeDbusBus`` instances, one per call.

    Buses are appended to ``self.buses`` and every call made on any bus is
    appended to ``self.calls`` so a test can inspect them after the fact.
    """

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.buses: list[FakeDbusBus] = []
        self.calls: list[dict] = []

    def __call__(self, bus_type: Any) -> Any:
        bus = FakeDbusBus(bus_type, all_calls=self.calls, error=self.error)
        self.buses.append(bus)
        return bus


# ---------------------------------------------------------------------------
# Server fixture
# ---------------------------------------------------------------------------


@dataclass
class ServerHandle:
    """Everything a test needs to interact with a running daemon instance."""

    server: Server
    scroll_sink: FakeScrollSink
    key_sink: FakePointerSink
    called: list[tuple[str, str]]  # ("shell"|"terminal", value)
    port: int
    dbus_buses: list  # list of fake dbus buses (one per press)
    dbus_calls: list[dict]  # all dbus call records from the session

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
    key_sink = FakePointerSink()
    dbus_factory = FakeDbusBusFactory()

    server = Server(
        layouts_dir=LAYOUTS_DIR,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(scroll_sink),
        key_sink=key_sink,
        dbus_bus_factory=dbus_factory,
    )

    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    port = test_server.port

    handle = ServerHandle(
        server=server,
        scroll_sink=scroll_sink,
        key_sink=key_sink,
        called=called,
        port=port or 0,
        dbus_buses=dbus_factory.buses,
        dbus_calls=dbus_factory.calls,
    )
    yield handle

    await test_server.close()
    await server.scroll.close()


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


def make_test_server(
    *,
    layouts_dir: Path,
    focus_backend=None,
    password: str | None = None,
) -> tuple[Server, FakeScrollSink, FakePointerSink, FakeDbusBusFactory]:
    """Build a ``Server`` with the same fake sinks used by the fixtures.

    Returns ``(server, scroll_sink, key_sink, dbus_factory)``; the caller
    is responsible for booting and tearing down the ``TestServer`` and
    for the ``monkeypatch`` of ``actions._run_shell`` / ``run_terminal``
    if it wants the fake shell behaviour.
    """
    scroll_sink = FakeScrollSink()
    key_sink = FakePointerSink()
    dbus_factory = FakeDbusBusFactory()
    server = Server(
        layouts_dir=layouts_dir,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(scroll_sink),
        key_sink=key_sink,
        dbus_bus_factory=dbus_factory,
        focus_backend=focus_backend,
        password=password,
    )
    return server, scroll_sink, key_sink, dbus_factory
