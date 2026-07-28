"""Integration tests for the diagnostic event stream (issue #73).

Covers the ``enable_events`` / ``disable_events`` WS message pair,
correlation ids on the session, the ``trace_id`` field on event
frames, and the opt-in allow-list semantics. Unknown events stay
silent — existing clients ignore them without crashing.
"""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from conftest import ServerHandle


async def _first_frame(ws: websockets.WebSocketClientProtocol) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout=2)
    return json.loads(raw)


@pytest.fixture
async def srv_with_focus(monkeypatch):
    """A ``srv`` variant that wires the daemon's ``FakeFocusBackend``."""
    from aiohttp.test_utils import TestServer
    from conftest import (
        FakeDbusBusFactory,
        FakeFocusBackend,
        FakePointerSink,
        FakeScrollSink,
        LAYOUTS_DIR,
    )
    from deckd.input import ScrollController
    from deckd.server import Server

    import deckd.actions as actions_mod

    called: list[tuple[str, str]] = []

    async def fake_shell(cmd: str) -> None:
        called.append(("shell", cmd))

    async def fake_terminal(target: bool | str = True) -> None:
        called.append(("terminal", str(target)))

    monkeypatch.setattr(actions_mod, "_run_shell", fake_shell)
    monkeypatch.setattr(actions_mod, "run_terminal", fake_terminal)

    backend = FakeFocusBackend()
    server = Server(
        layouts_dir=LAYOUTS_DIR,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        key_sink=FakePointerSink(),
        dbus_bus_factory=FakeDbusBusFactory(),
        focus_backend=backend,
    )
    server.start_focus_watcher()
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    handle = ServerHandle(
        server=server,
        scroll_sink=FakeScrollSink(),
        key_sink=FakePointerSink(),
        called=called,
        port=ts.port or 0,
        dbus_buses=[],
        dbus_calls=[],
    )
    try:
        yield handle, backend
    finally:
        await ts.close()
        await server.scroll.close()


async def test_enable_events_receives_focus_change(srv_with_focus) -> None:
    """An opted-in session receives a ``focus_change`` event after a
    fake focus push."""
    from deckd.platform import AppInfo

    srv, backend = srv_with_focus
    async with websockets.connect(srv.ws_url) as ws:
        await _first_frame(ws)
        await ws.send(json.dumps({"type": "enable_events"}))
        # Allow the dispatcher to subscribe the session to the bus
        # before the focus push fires.
        await asyncio.sleep(0.05)
        await backend.push(AppInfo(app_id="firefox", wm_class="firefox"))
        deadline = asyncio.get_event_loop().time() + 2.0
        saw_event = False
        while asyncio.get_event_loop().time() < deadline and not saw_event:
            raw = await asyncio.wait_for(ws.recv(), timeout=1)
            data = json.loads(raw)
            if data.get("type") == "event" and data["name"] == "focus_change":
                assert data["data"]["app_id"] == "firefox"
                assert data["data"]["new_layout_id"] == "firefox"
                assert "ts" in data
                saw_event = True
        assert saw_event, "expected a focus_change event within 2s"


async def test_disable_events_silences_stream(srv_with_focus) -> None:
    """After ``disable_events``, no events are pushed even if focus
    keeps changing."""
    from deckd.platform import AppInfo

    srv, backend = srv_with_focus
    async with websockets.connect(srv.ws_url) as ws:
        await _first_frame(ws)
        await ws.send(json.dumps({"type": "enable_events"}))
        await ws.send(json.dumps({"type": "disable_events"}))
        await asyncio.sleep(0.05)
        await backend.push(AppInfo(app_id="firefox", wm_class="firefox"))
        # Drain the layout push (focus_change → layout); then assert
        # no event frames arrive.
        await asyncio.wait_for(ws.recv(), timeout=1)
        # After the layout push completes, no further event frame
        # should arrive.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ws.recv(), timeout=0.5)


async def test_enable_events_with_allow_list(srv_with_focus) -> None:
    """Allow-list filters events to the named set."""
    from deckd.platform import AppInfo

    srv, backend = srv_with_focus
    async with websockets.connect(srv.ws_url) as ws:
        await _first_frame(ws)
        await ws.send(
            json.dumps({"type": "enable_events", "events": ["layout_reload"]})
        )
        await asyncio.sleep(0.05)
        await backend.push(AppInfo(app_id="firefox", wm_class="firefox"))
        # Drain the layout push; the focus_change event must be
        # filtered out by the allow-list.
        await asyncio.wait_for(ws.recv(), timeout=1)
        # Trigger a layout_reload event by POSTing to /reload.
        import aiohttp

        async with aiohttp.ClientSession() as http:
            await http.post(f"{srv.http_url}/reload")
        deadline = asyncio.get_event_loop().time() + 2.0
        saw = False
        while asyncio.get_event_loop().time() < deadline and not saw:
            raw = await asyncio.wait_for(ws.recv(), timeout=1)
            data = json.loads(raw)
            if data.get("type") == "event" and data["name"] == "layout_reload":
                saw = True
        assert saw, "expected a layout_reload event after /reload"


async def test_event_carries_trace_id(srv: ServerHandle) -> None:
    """An event produced under a correlation scope carries the id."""
    from deckd.events import DiagnosticEvent, correlation_id_var
    from deckd.mpris import FakeMprisBackend
    from deckd.media import MediaState

    fake = FakeMprisBackend(states={"vlc": MediaState(available=True)})
    srv.server.mpris = fake
    fake.set_diagnostic_listener(srv.server._on_mpris_diagnostic_event)

    async with websockets.connect(srv.ws_url) as ws:
        await _first_frame(ws)
        await ws.send(
            json.dumps(
                {"type": "enable_events", "events": ["player_added"]}
            )
        )
        # Allow the dispatcher to register the session's subscriber.
        await asyncio.sleep(0.05)
        token = correlation_id_var.set("trace-abc")
        try:
            await srv.server.events.emit(
                DiagnosticEvent(
                    name="player_added",
                    ts=0.0,
                    data={"row_id": "vlc"},
                    correlation_id="trace-abc",
                )
            )
        finally:
            correlation_id_var.reset(token)
        deadline = asyncio.get_event_loop().time() + 2.0
        saw_event = False
        while asyncio.get_event_loop().time() < deadline and not saw_event:
            raw = await asyncio.wait_for(ws.recv(), timeout=1)
            data = json.loads(raw)
            if data.get("type") == "event" and data["name"] == "player_added":
                # The trace id rides on the wire.
                assert data.get("trace_id") == "trace-abc"
                saw_event = True
        assert saw_event


async def test_unknown_event_is_ignored_by_other_clients(srv_with_focus) -> None:
    """A session that didn't opt in sees no event frames even though
    another session did."""
    from deckd.platform import AppInfo

    srv, backend = srv_with_focus
    async with websockets.connect(srv.ws_url) as ws_a, websockets.connect(
        srv.ws_url
    ) as ws_b:
        await _first_frame(ws_a)
        await _first_frame(ws_b)
        await ws_a.send(json.dumps({"type": "enable_events"}))
        await asyncio.sleep(0.05)
        await backend.push(AppInfo(app_id="firefox", wm_class="firefox"))
        # Both sessions get the layout push; drain ws_b's layout push.
        await asyncio.wait_for(ws_b.recv(), timeout=1)
        # Drain ws_a (it gets layout + event).
        deadline = asyncio.get_event_loop().time() + 1.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws_a.recv(), timeout=0.2)
                json.loads(raw)
            except asyncio.TimeoutError:
                break
        # ws_b should not see any further frames — no event frames.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(ws_b.recv(), timeout=0.5)


async def test_session_trace_id_is_set_on_connect(srv: ServerHandle) -> None:
    """The session carries a generated trace id when no header is sent."""
    async with websockets.connect(srv.ws_url) as ws:
        await _first_frame(ws)
        sessions = list(srv.server._sessions)
        assert len(sessions) == 1
        assert sessions[0].trace_id
        # 12 hex chars per the new_correlation_id generator.
        assert len(sessions[0].trace_id) == 12


async def test_session_trace_id_respects_hello_field(srv: ServerHandle) -> None:
    """The hello ``trace`` field becomes the session's trace id.

    On a no-auth server the hello arrives via the dispatcher (after
    the initial push). The ``trace`` field is read by the dispatcher
    and re-stamped on the session's trace_id.
    """
    async with websockets.connect(srv.ws_url) as ws:
        await _first_frame(ws)
        await ws.send(json.dumps({"type": "hello", "client": "test", "trace": "abc"}))
        # Drain any frames the dispatcher sends in response (a layout
        # push when the demo pin is empty).
        await asyncio.sleep(0.05)
        sessions = list(srv.server._sessions)
        assert sessions[0].trace_id == "abc"


async def test_mpris_diagnostic_listener_emits_event(srv: ServerHandle) -> None:
    """``Server._on_mpris_diagnostic_event`` (issue #72's backend hook)
    also emits a ``DiagnosticEvent`` on the EventBus, so the WS event
    stream sees MPRIS changes — not just the ring buffer (issue #73)."""
    from deckd.events import EventBus
    from deckd.media import MediaState
    from deckd.mpris import FakeMprisBackend

    fake = FakeMprisBackend(states={"vlc": MediaState(available=True)})
    srv.server.mpris = fake
    fake.set_diagnostic_listener(srv.server._on_mpris_diagnostic_event)

    # Subscribe directly to the bus rather than going through WS — this
    # test asserts the EventBus wiring, not the wire format.
    bus: EventBus = srv.server.events
    seen: list[dict] = []

    async def _capture(event) -> None:
        seen.append({"name": event.name, "data": event.data})

    unsubscribe = bus.subscribe(_capture)
    try:
        srv.server._on_mpris_diagnostic_event(
            "player_added", "vlc", {"playing": True}
        )
        # The emit is scheduled as a task — yield until it lands.
        for _ in range(20):
            await asyncio.sleep(0.01)
            if seen:
                break
    finally:
        unsubscribe()

    assert seen, "expected an mpris event after _on_mpris_diagnostic_event"
    evt = seen[0]
    assert evt["name"] == "mpris"
    assert evt["data"]["kind"] == "player_added"
    assert evt["data"]["row_id"] == "vlc"
    assert evt["data"]["playing"] is True
    # The MPRIS events ride on the same ring buffer used by
    # ``/mpris/events/recent`` — record count bumped by one.
    assert len(srv.server.mpris_events.snapshot()) == 1