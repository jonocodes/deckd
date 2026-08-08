"""WebSocket round-trip tests for the chrome-media passive indicator (issue #47).

Seam under test: the full chain from a real D-Bus ``PropertiesChanged``
or ``NameOwnerChanged`` signal through ``DbusMprisBackend`` ->
``compute_chrome_media`` -> the server's broadcast loop -> the
WebSocket as a ``chrome_media`` frame.

This is the integration view the unit-level reducer test can't see:
the listener wiring on the backend (``set_chrome_media_listener``),
the broadcast loop's session iteration, and the pydantic message
model all have to agree before a frame lands on the wire.

The test boots a real ``Server`` with a ``FakeDbusBus`` so signals
can be pushed directly into the backend's handlers — no real session
bus, no D-Bus daemon. The fake records the method calls so we can
assert against the live bus state too.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
import websockets
from aiohttp.test_utils import TestServer

sys.path.insert(0, str(Path(__file__).parent))

from conftest import make_test_server, requires_dbus
from deckd.mpris import DbusMprisBackend, PLAYER_INTERFACE
from test_mpris_dbus import FakeDbusBus

# Whole module boots a real ``DbusMprisBackend`` and calls ``.start()``,
# which lazily imports ``dbus_fast`` (issue #27).
pytestmark = requires_dbus


async def _boot_chrome_media_websocket(
    tmp_path: Path,
    bus: FakeDbusBus,
) -> tuple[TestServer, "Server", FakeDbusBus]:
    """Stand up a real daemon + WebSocket fronted by ``bus``.

    Mirrors :func:`test_mpris_websocket._boot_mpris_websocket` so the
    chrome-media and per-row tests share the same plumbing: a layout
    with one ``nowplaying`` widget (so the daemon wires a real
    :class:`DbusMprisBackend`), booted on a random port, with the
    server's pump started. Returns the ``TestServer``, the ``Server``,
    and the bus so tests can push signals and read recorded calls.
    """
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: browser
    kind: nowplaying
    size: [4, 2]
"""
    )
    server, *_ = make_test_server(
        layouts_dir=tmp_path,
        mpris_backend=DbusMprisBackend(bus_factory=lambda _bt: bus),
    )
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    if isinstance(server.mpris, DbusMprisBackend):
        await server.mpris.start()
    server.start_media_pump()
    return test_server, server, bus


async def test_chrome_media_snapshot_says_unsupported_when_backend_cannot_start(
    tmp_path: Path,
) -> None:
    """A host with no session bus gets ``supported=False``, not silence.

    macOS is the live case: a layout declares ``nowplaying``, so the
    daemon builds a ``DbusMprisBackend``, and ``start()`` then fails
    because there is no session bus to reach. Dropping the frame
    entirely would leave the client unable to distinguish "unsupported
    host" from "snapshot hasn't arrived yet", so it would sit on
    "Nothing playing" forever — telling the user to go play something
    that can never appear.
    """
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: browser
    kind: nowplaying
    size: [4, 2]
"""
    )
    server, *_ = make_test_server(layouts_dir=tmp_path)
    # Stand in for the post-``start()`` state on a bus-less host: the
    # backend was configured by the layout, then torn down when the
    # connect failed (see Server.start).
    server.mpris = None
    server._mpris_unsupported = True
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            frame = await _next_chrome_media(ws)
            assert frame == {
                "type": "chrome_media",
                "available": False,
                "playing": False,
                "playing_count": 0,
                "supported": False,
            }
    finally:
        await server.stop()
        await test_server.close()


async def test_chrome_media_snapshot_stays_silent_when_feature_unconfigured(
    tmp_path: Path,
) -> None:
    """No ``nowplaying`` layout means no backend was ever built —
    an unconfigured feature, not an unsupported host. The daemon sends
    nothing, exactly as before, so the client keeps its default
    ("Nothing playing") rather than claiming the platform can't do
    it. This is the case that makes ``_mpris_unsupported`` a separate
    flag from ``mpris is None``."""
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: btn
    kind: button
    action: {key: a}
"""
    )
    server, *_ = make_test_server(layouts_dir=tmp_path)
    assert server.mpris is None
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            with pytest.raises(asyncio.TimeoutError):
                await _next_chrome_media(ws)
    finally:
        await server.stop()
        await test_server.close()


async def _drain_initial(ws) -> None:
    """Drain the layout + per-row media_state frames + chrome-media
    snapshot a fresh client gets.

    The pump pushes ``media_state`` for every owned row on connect
    (the snapshot replay path added for issue #52's late-client
    case); the chrome-media snapshot rides right after (issue #47).
    Once those warm-up frames are consumed the client only sees new
    chrome_media frames when the underlying MPRIS events change, so
    the test's signal-emit / recv sequence lands on the right frame.
    """
    assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "layout"
    # Drain per-row media_state frames. Tests register vlc in their
    # own setup so the snapshot has one row.
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 2))
        if msg["type"] != "media_state":
            raise AssertionError(f"unexpected initial frame: {msg}")
        if msg["id"] == "mpris.vlc":
            break
    # Drain the chrome-media snapshot too (issue #47). After this
    # returns, the next chrome-media frame the client sees is one
    # pushed by a signal under test.
    snap = json.loads(await asyncio.wait_for(ws.recv(), 2))
    assert snap["type"] == "chrome_media", f"expected snapshot, got {snap}"


async def _next_chrome_media(ws) -> dict:
    """Return the next ``chrome_media`` frame received over the socket.

    Drains any other frame types (a stray ``media_state`` for the
    freshly-registered row, for example) so the assertion lands on
    exactly the chrome-media wire shape under test.
    """
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 2))
        if msg["type"] == "chrome_media":
            return msg


async def test_chrome_media_emits_on_player_registration(tmp_path: Path) -> None:
    """A ``NameOwnerChanged`` registration fires a ``chrome_media`` frame
    over the WebSocket with ``available=True``. The client receives it
    on the same connection that pushed the signal — issue #47 acceptance
    criterion: indicator is correct on first view of the chrome."""
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc", {"PlaybackStatus": "Paused"}
    )
    test_server, server, bus = await _boot_chrome_media_websocket(tmp_path, bus)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            await _drain_initial(ws)
            # VLC just appeared on the bus. The handler must fire a
            # chrome_media frame so the client's icon updates.
            bus.emit_name_owner_changed(
                "org.mpris.MediaPlayer2.vlc", None, ":1.99"
            )
            frame = await _next_chrome_media(ws)
            assert frame == {
                "type": "chrome_media",
                "available": True,
                "playing": False,
                "playing_count": 0,
                # A live backend is by definition a supported one; the
                # flag only goes false when the host has no session bus.
                "supported": True,
            }
    finally:
        await server.stop()
        await test_server.close()


async def test_chrome_media_emits_on_playback_status_transition(
    tmp_path: Path,
) -> None:
    """A ``PropertiesChanged`` carrying ``PlaybackStatus = Playing`` for
    a registered row flips the chrome icon to tinted. The frame fires
    immediately (not on the pump's 1-second tick) — the listener
    bypasses the poll loop (issue #47 acceptance criterion: indicator
    reflects state without making playback traffic chatty)."""
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc", {"PlaybackStatus": "Paused"}
    )
    test_server, server, bus = await _boot_chrome_media_websocket(tmp_path, bus)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            await _drain_initial(ws)
            # Register vlc first (sets up the owner mapping so the
            # subsequent PropertiesChanged can route back to a row).
            bus.emit_name_owner_changed(
                "org.mpris.MediaPlayer2.vlc", None, ":1.99"
            )
            # Drain the registration frame.
            reg = await _next_chrome_media(ws)
            assert reg["playing"] is False

            # Now the player starts playing.
            bus.emit_properties_changed(
                "org.mpris.MediaPlayer2.vlc",
                PLAYER_INTERFACE,
                {"PlaybackStatus": "Playing"},
            )
            frame = await _next_chrome_media(ws)
            assert frame == {
                "type": "chrome_media",
                "available": True,
                "playing": True,
                "playing_count": 1,
                "supported": True,
            }
    finally:
        await server.stop()
        await test_server.close()


async def test_chrome_media_does_not_emit_on_metadata_update(
    tmp_path: Path,
) -> None:
    """A ``PropertiesChanged`` that updates ``Metadata`` (a track skip)
    but doesn't touch ``PlaybackStatus`` must NOT produce a
    ``chrome_media`` frame. This is the debounce-by-event-type rule:
    playback traffic is high-frequency (a 1Hz position poll alone
    would otherwise flood the icon with redundant frames)."""
    bus = FakeDbusBus()
    # Seed vlc as already-Playing on the bus, then register it on the
    # backend via start() so the snapshot's chrome-media state is
    # ``playing=True``. Subsequent PropertiesChanged with Metadata
    # only must not flip that and must not produce a chrome_media
    # frame.
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc", {"PlaybackStatus": "Playing"}
    )
    test_server, server, bus = await _boot_chrome_media_websocket(tmp_path, bus)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            await _drain_initial(ws)

            # Track skip: Metadata changes, PlaybackStatus stays Playing.
            # No chrome_media frame must follow.
            bus.emit_properties_changed(
                "org.mpris.MediaPlayer2.vlc",
                PLAYER_INTERFACE,
                {
                    "Metadata": {
                        "xesam:title": "New Track",
                        "mpris:artUrl": "file:///cache/vlc/new.png",
                    }
                },
            )
            # Wait briefly for any (incorrectly-fired) frame. A timeout
            # is the success path; any chrome_media frame received is
            # the failure. A ``media_state`` from the 1-second pump
            # tick is unrelated — the bus backend will see the
            # Metadata update and re-broadcast the row state, which
            # is exactly the existing per-row stream we already test
            # elsewhere (issue #52).
            try:
                stray = await asyncio.wait_for(ws.recv(), 0.3)
            except asyncio.TimeoutError:
                stray = None
            if stray is not None:
                assert stray["type"] != "chrome_media", (
                    f"unexpected chrome_media frame on metadata-only update: {stray}"
                )
    finally:
        await server.stop()
        await test_server.close()


async def test_chrome_media_emits_to_all_connected_sessions(tmp_path: Path) -> None:
    """The chrome icon is global chrome — every connected session
    receives the frame, not only the one with the nowplaying view
    pinned (issue #47 acceptance criterion: push to all connected
    clients). Two simultaneous WS clients both see the registration
    transition."""
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc", {"PlaybackStatus": "Playing"}
    )
    test_server, server, bus = await _boot_chrome_media_websocket(tmp_path, bus)
    url = f"ws://127.0.0.1:{test_server.port}/ws"
    try:
        async with websockets.connect(url) as first, websockets.connect(url) as second:
            await _drain_initial(first)
            await _drain_initial(second)

            bus.emit_name_owner_changed(
                "org.mpris.MediaPlayer2.vlc", None, ":1.99"
            )
            frame_a = await _next_chrome_media(first)
            frame_b = await _next_chrome_media(second)
            assert frame_a["playing"] is True
            assert frame_a["playing_count"] == 1
            assert frame_b["playing"] is True
            assert frame_b["playing_count"] == 1
    finally:
        await server.stop()
        await test_server.close()


async def test_chrome_media_emits_when_no_nowplaying_widget_mounted(
    tmp_path: Path,
) -> None:
    """The indicator is global chrome — a user with a ``nowplaying``
    layout loaded (so the backend is alive) but currently focused on
    some other app's layout (no ``nowplaying`` widget in the
    *current* layout) must still see ``chrome_media`` frames
    (acceptance criterion 4: "the daemon emits a ``chrome_media``
    frame regardless of whether any ``nowplaying`` widget is
    mounted"). The real-world shape: a user who has the
    ``layouts/mpris.yaml`` shipped but spends most of their time in
    Firefox / a terminal / etc."""
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc", {"PlaybackStatus": "Playing"}
    )
    # Layouts: a default with no browser widget + the mpris view
    # layout that brings the backend alive on ``connect_mpris_backend``.
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: pad
    kind: trackpad
    size: [4, 2]
"""
    )
    (tmp_path / "mpris.yaml").write_text(
        """
match: [mpris]
widgets:
  - id: browser
    kind: nowplaying
    size: [4, 2]
"""
    )
    server, *_ = make_test_server(
        layouts_dir=tmp_path,
        mpris_backend=DbusMprisBackend(bus_factory=lambda _bt: bus),
    )
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    if isinstance(server.mpris, DbusMprisBackend):
        await server.mpris.start()
    server.start_media_pump()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            assert json.loads(await asyncio.wait_for(ws.recv(), 2))["type"] == "layout"
            # Drain the per-row media_state + chrome-media snapshot
            # frames. ``vlc`` is in the bus's seed set so the
            # snapshot replay pushes a ``media_state`` for it; the
            # chrome-media snapshot rides after.
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 2))
                if msg["type"] == "chrome_media":
                    snap = msg
                    break
            assert snap == {
                "type": "chrome_media",
                "available": True,
                "playing": True,
                "playing_count": 1,
                "supported": True,
            }

            # A fresh registration transition still pushes a frame
            # even though the focused-app layout has no
            # ``nowplaying`` widget — the indicator is global chrome.
            # The reducer's rule is "registered AND confirmed Playing":
            # spotify's cache hasn't been populated yet, so it
            # contributes 0 to the playing tally; the frame still
            # fires (every NameOwnerChanged does) with the new
            # ``available`` state.
            bus.emit_name_owner_changed(
                "org.mpris.MediaPlayer2.spotify", None, ":1.42"
            )
            frame = await _next_chrome_media(ws)
            assert frame == {
                "type": "chrome_media",
                "available": True,
                "playing": True,
                "playing_count": 1,
                "supported": True,
            }
    finally:
        await server.stop()
        await test_server.close()
