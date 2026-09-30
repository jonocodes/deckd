"""Issue #64: reconnect, locked, and error feedback that explains and recovers.

The client-facing half of these states lives in the React app; these tests
cover the daemon seam that has to *supply the facts* the client explains:

* a failed deck reload now carries the deck name and offending widget so
  the error surface can name them (instead of pasting a pydantic dump);
* a failed media command — MPRIS player gone / method rejected, or the VLC
  HTTP call failing — is reported to the requesting session as a
  ``media_error`` frame naming the player, rather than vanishing into a log.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp
import websockets
from aiohttp.test_utils import TestServer

from conftest import make_test_server
from deckd.media import MediaState
from deckd.mpris import FakeMprisBackend, MprisCommandError


async def _recv_type(ws, wanted: str, timeout: float = 2.0) -> dict:
    """Read frames until one of ``wanted`` type arrives (or time out)."""
    while True:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if frame.get("type") == wanted:
            return frame


# ---------------------------------------------------------------------------
# Deck reload error: structured deck / widget names on the wire
# ---------------------------------------------------------------------------


_GOOD = """
match: [default]
widgets:
  - id: home
    kind: button
"""

_BAD = """
match: [default]
widgets:
  - id: home
    kind: button
    action:
      nope: true
"""


async def test_deck_reload_error_carries_deck_and_widget(tmp_path: Path) -> None:
    (tmp_path / "default.yaml").write_text(_GOOD)
    server, *_ = make_test_server(decks_dir=tmp_path)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            first = json.loads(await asyncio.wait_for(ws.recv(), 2))
            assert first["type"] == "deck"
            assert first["error"] is None

            # Break the file on disk and reload; the daemon keeps the
            # last-good deck but flags the error on the next push.
            (tmp_path / "default.yaml").write_text(_BAD)
            await server.reload_and_push()

            err = await _recv_type(ws, "deck")
            assert err["error"], "raw error text still rides for diagnostics"
            assert err["error_deck"] == "default"
            assert err["error_widget"] == "home"
            assert err["widgets"] == []
    finally:
        await server.stop()
        await test_server.close()


# ---------------------------------------------------------------------------
# Media errors: MPRIS player gone / command rejected
# ---------------------------------------------------------------------------


class _RaisingMpris(FakeMprisBackend):
    """FakeMprisBackend whose commands always fail with a given error."""

    def __init__(self, states: dict[str, MediaState], error: MprisCommandError) -> None:
        super().__init__(states)
        self._error = error

    async def send_command(self, row_id: str, command: str) -> None:
        raise self._error

    def identity(self, row_id: str) -> str | None:
        return "VLC media player"


async def test_mpris_media_error_is_reported_to_requester(tmp_path: Path) -> None:
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: browser
    kind: nowplaying
    size: [4, 2]
"""
    )
    backend = _RaisingMpris(
        {"vlc": MediaState(available=True, stale=False, playing=True, title="VLC")},
        MprisCommandError("vlc", "player disappeared"),
    )
    server, *_ = make_test_server(decks_dir=tmp_path, mpris_backend=backend)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            await _recv_type(ws, "deck")
            await ws.send(
                json.dumps(
                    {"type": "media_command", "id": "mpris.vlc", "command": "next"}
                )
            )
            err = await _recv_type(ws, "media_error")
            assert err["id"] == "mpris.vlc"
            assert err["player"] == "VLC media player"
            assert err["retryable"] is True
            assert "player disappeared" in err["message"]
    finally:
        await server.stop()
        await test_server.close()


async def test_mpris_http_command_reports_missing_player(tmp_path: Path) -> None:
    """The authenticated HTTP command endpoint mirrors the WS feedback:
    a vanished row is a structured 404, not a silent 200 (issue #64)."""
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: browser
    kind: nowplaying
    size: [4, 2]
"""
    )
    backend = _RaisingMpris(
        {"vlc": MediaState(available=True, stale=False, playing=True, title="VLC")},
        MprisCommandError("vlc", "player disappeared"),
    )
    server, *_ = make_test_server(decks_dir=tmp_path, mpris_backend=backend)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        async with aiohttp.ClientSession() as client:
            resp = await client.post(
                f"http://127.0.0.1:{test_server.port}/mpris/vlc/command",
                json={"command": "next"},
            )
            assert resp.status == 404
            body = await resp.json()
            assert body == {"ok": False, "error": "player disappeared"}
    finally:
        await server.stop()
        await test_server.close()


class _FailingMediaManager:
    def stop(self) -> None:
        pass

    async def read(self, key: str, *, host: str, port: int, password_ref: str | None) -> MediaState:
        return MediaState(available=True, stale=False, playing=True)

    async def command(
        self,
        key: str,
        command: str,
        value: float,
        *,
        host: str,
        port: int,
        password_ref: str | None,
    ) -> None:
        raise RuntimeError("connection refused")


async def test_vlc_media_error_is_reported_to_requester(tmp_path: Path) -> None:
    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: media
    kind: media
    label: Living Room VLC
    size: [4, 2]
    media_http:
      host: media.local
      port: 9090
"""
    )
    server, *_ = make_test_server(
        decks_dir=tmp_path, media_manager=_FailingMediaManager()
    )
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            await _recv_type(ws, "deck")
            await ws.send(
                json.dumps(
                    {"type": "media_command", "id": "media", "command": "volume", "value": 55}
                )
            )
            err = await _recv_type(ws, "media_error")
            assert err["id"] == "media"
            assert err["player"] == "Living Room VLC"
            assert err["retryable"] is True
    finally:
        await server.stop()
        await test_server.close()
