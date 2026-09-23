"""Session lock/blank awareness: backend detection + daemon gate (issue #160)."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestServer

from deckd.platform import (
    GnomeShellFocusBackend,
    PlatformBackend,
    SessionState,
    UnimplementedCapability,
)

from conftest import LAYOUTS_DIR, make_test_server


# ---------------------------------------------------------------------------
# Backend: session-state detection
# ---------------------------------------------------------------------------


class FakeGdbusBackend(GnomeShellFocusBackend):
    """GnomeShellFocusBackend with the gdbus shell-out replaced.

    ``scripted`` maps a canned reply to each probe; an unscripted probe
    raises — the "not on the bus" failure the watcher has to survive.
    """

    def __init__(self) -> None:
        self.scripted: dict[str, str] = {}

    async def _fake_run(self, *args: str) -> str:
        if "--session" in args and "ScreenSaver.GetActive" in args[-1]:
            canned = self.scripted.get("GetActive", "(false,)")
        elif "--system" in args and args[-1] == "LockedHint":
            canned = self.scripted.get("LockedHint")
            if canned is None:
                raise RuntimeError("no such session")
        else:
            raise RuntimeError(f"unexpected gdbus call: {args}")
        if canned == "FAIL":
            raise RuntimeError("bus unreachable")
        return canned


@pytest.fixture
def fake_gdbus(monkeypatch):
    backend = FakeGdbusBackend()
    monkeypatch.setattr("deckd.platform._run", backend._fake_run)
    monkeypatch.setenv("XDG_SESSION_ID", "c1")  # login1 path resolves via this
    return backend


async def test_default_backend_refuses_session_state() -> None:
    with pytest.raises(UnimplementedCapability):
        async for _ in PlatformBackend().watch_session_state():
            pass


async def test_gnome_session_state_once(fake_gdbus) -> None:
    state = await fake_gdbus._session_state_once()
    assert state == SessionState(locked=False, blanked=False)


async def test_gnome_blank_without_lock(fake_gdbus) -> None:
    """Blank-but-not-locked: ScreenSaver says active, login1 says awake.

    Everything about issue #160 hinges on this split — a single boolean
    would gate input on every screen blank and forfeit wake-from-phone.
    """
    fake_gdbus.scripted = {"GetActive": "(true,)", "LockedHint": "(false,)"}
    state = await fake_gdbus._session_state_once()
    assert state.blanked is True
    assert state.locked is False


async def test_gnome_locked(fake_gdbus) -> None:
    fake_gdbus.scripted = {"GetActive": "(true,)", "LockedHint": "(true,)"}
    state = await fake_gdbus._session_state_once()
    assert state.locked is True
    assert state.blanked is True


async def test_gnome_login1_failure_degrades_to_unlocked(fake_gdbus) -> None:
    """login1 unreachable → the lock half stays false, never an error."""
    fake_gdbus.scripted = {"GetActive": "(false,)"}
    state = await fake_gdbus._session_state_once()
    assert state.locked is False


async def test_gnome_screensaver_failure_survives(fake_gdbus) -> None:
    """No org.gnome.ScreenSaver on the bus → the probe raises, but the
    *watcher* keeps polling (failure model of every other watcher here:
    log once, sleep through, keep going)."""
    fake_gdbus.scripted = {"GetActive": "FAIL"}
    with pytest.raises(RuntimeError):
        await fake_gdbus._session_state_once()
    gen = fake_gdbus.watch_session_state(interval_s=0.01)
    # The broken tick is swallowed (yields nothing); the first real
    # snapshot arrives when the bus starts answering.
    fake_gdbus.scripted = {"LockedHint": "(false,)", "GetActive": "(true,)"}
    state = await gen.__anext__()
    assert state.blanked is True and state.locked is False


async def test_watch_session_state_yields_transitions(fake_gdbus) -> None:
    gen = fake_gdbus.watch_session_state(interval_s=0.01)
    first = await gen.__anext__()
    assert first == SessionState(locked=False, blanked=False)
    # Flip blanked on the bus (auto-lock off: blank, not locked)…
    fake_gdbus.scripted = {"LockedHint": "(false,)", "GetActive": "(true,)"}
    transition = await gen.__anext__()
    assert transition.blanked is True and transition.locked is False
    # …and lock it later.
    fake_gdbus.scripted = {"LockedHint": "(true,)", "GetActive": "(true,)"}
    transition = await gen.__anext__()
    assert transition.locked is True


def test_gnome_capabilities_advertise_both_session_flags() -> None:
    caps = GnomeShellFocusBackend().capabilities()
    assert {"session_lock", "session_blank"} <= caps


def test_base_backend_does_not_advertise_session_flags() -> None:
    caps = PlatformBackend().capabilities()
    assert "session_lock" not in caps
    assert "session_blank" not in caps


# ---------------------------------------------------------------------------
# Server: connect snapshot
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _boot_server(locked_backend=True, **kwargs):
    server, _, _, _ = make_test_server(layouts_dir=LAYOUTS_DIR, **kwargs)
    # A session-state-capable backend so the connect snapshot is live
    # (mirrors GNOME in production; a caps-less fake produces NO state
    # frame at all — see `test_no_capability_no_state_frame`).
    if locked_backend:
        server.focus_backend = SimpleNamespace(
            capabilities=lambda: frozenset({"watch_active_app", "session_lock", "session_blank"}),
        )
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    try:
        yield server, ts.port
    finally:
        await ts.close()


@asynccontextmanager
async def _connect(port: int):
    """Open a no-auth WS and yield (ws, layout, state) — the first three pushes."""
    import websockets as _ws

    async with _ws.connect(f"ws://127.0.0.1:{port}/ws") as ws:
        layout = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        state = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        yield ws, layout, state


@asynccontextmanager
async def _ws_session(srv):
    """Open a WS against the ``srv`` fixture; yield (ws, initial layout)."""
    import websockets as _ws

    async with _ws.connect(srv.ws_url) as ws:
        layout = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        yield ws, layout


async def test_state_snapshot_on_connect() -> None:
    """A phone connecting *during* a lock gets the state immediately."""
    async with _boot_server() as (server, port):
        server._session_locked = True
        async with _connect(port) as (_, layout, state):
            pass
        assert layout["type"] == "layout"
        assert state == {"type": "state", "locked": True, "blanked": False}


async def test_no_capability_no_state_frame() -> None:
    """A backend with no session-state caps pushes NOTHING at connect.

    The absent frame is the wire-level signal; a client that never
    receives ``state`` can never strand itself in a lock view.
    """
    async with _boot_server(locked_backend=False) as (server, port):
        import websockets as _ws

        async with _ws.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            layout = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            try:
                frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.25))
            except TimeoutError:
                return
            assert frame["type"] != "state"


# ---------------------------------------------------------------------------
# Server: press / injection gate at the WebSocket boundary
# ---------------------------------------------------------------------------

ORNAMENT_WAIT = 0.05


async def _recv(ws, timeout: float = 2.0) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))


async def test_press_refused_while_locked(srv) -> None:
    async with _ws_session(srv) as (ws, _):
        srv.server._session_locked = True
        await ws.send(json.dumps({"type": "press", "id": "open-url"}))
        reply = await _recv(ws)
        await asyncio.sleep(ORNAMENT_WAIT)
    assert reply == {"type": "error", "reason": "screen_locked"}
    assert not any(kind == "shell" for kind, _ in srv.called)


async def test_press_allowed_while_unlocked(srv) -> None:
    async with _ws_session(srv) as (ws, _):
        await ws.send(json.dumps({"type": "press", "id": "open-url"}))
        await asyncio.sleep(ORNAMENT_WAIT)
    assert any(kind == "shell" for kind, _ in srv.called)


async def test_allow_while_locked_opt_out(srv) -> None:
    """``--allow-while-locked`` restores today's ungated behaviour."""
    srv.server._allow_while_locked = True
    srv.server._session_locked = True
    async with _ws_session(srv) as (ws, _):
        await ws.send(json.dumps({"type": "press", "id": "open-url"}))
        await asyncio.sleep(ORNAMENT_WAIT)
    assert any(kind == "shell" for kind, _ in srv.called)


async def test_key_type_gated_while_locked(srv) -> None:
    async with _ws_session(srv) as (ws, _):
        srv.server._session_locked = True
        await ws.send(json.dumps({"type": "key", "combo": "ctrl+l"}))
        reply = await _recv(ws)
        await ws.send(json.dumps({"type": "type", "text": "hi"}))
        await _recv(ws)
        await ws.send(json.dumps({"type": "pad", "id": "x", "dx": 5, "dy": 0}))
        await ws.send(json.dumps({"type": "jog", "id": "x", "delta": 3}))
        await asyncio.sleep(ORNAMENT_WAIT)
    assert reply == {"type": "error", "reason": "screen_locked"}
    assert srv.key_sink.events == []
    assert srv.scroll_sink.deltas == []


async def test_key_type_runs_while_unlocked(srv) -> None:
    async with _ws_session(srv) as (ws, _):
        await ws.send(json.dumps({"type": "key", "combo": "ctrl+t"}))
        await asyncio.sleep(ORNAMENT_WAIT)
    assert srv.key_sink.events


async def test_raise_window_gated_while_locked(srv) -> None:
    async with _ws_session(srv) as (ws, _):
        srv.server._session_locked = True
        await ws.send(json.dumps({"type": "raise_window", "window_id": "42"}))
        reply = await _recv(ws)
        await asyncio.sleep(ORNAMENT_WAIT)
    assert reply == {"type": "error", "reason": "screen_locked"}


async def test_press_refusal_recorded_in_recent_actions(srv) -> None:
    async with _ws_session(srv) as (ws, _):
        srv.server._session_locked = True
        await ws.send(json.dumps({"type": "press", "id": "open-url"}))
        await _recv(ws)
        await asyncio.sleep(ORNAMENT_WAIT)
    assert "lock_dropped" in {r.outcome for r in srv.server.recent_actions.snapshot()}


async def test_transition_broadcast_reaches_session(srv) -> None:
    from deckd.platform import SessionState as _SS

    async with _ws_session(srv) as (ws, _):
        await srv.server._on_session_state(_SS(locked=True, blanked=False))
        frame = await _recv(ws)
        assert frame == {"type": "state", "locked": True, "blanked": False}
        # Identical push is deduped, a transition re-fires.
        await srv.server._on_session_state(_SS(locked=True, blanked=False))
        await srv.server._on_session_state(_SS(locked=False, blanked=True))
        frame = await _recv(ws)
        assert frame["locked"] is False and frame["blanked"] is True


async def test_watcher_broadcast_and_capability_refusal(srv) -> None:
    """start_session_state_watcher is a silent no-op without the caps."""
    srv.server._last = None
    assert srv.server.start_session_state_watcher() is None

