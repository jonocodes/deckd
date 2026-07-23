"""Remote-client password auth at the WS + HTTP boundary (issue #16).

The daemon binds to 127.0.0.1 in tests, so ``request.remote`` is always
loopback. To exercise the *remote* path we monkeypatch ``_is_loopback``
to report ``False`` — that's the one seam between "who is calling" and
"do they need a password", and faking it is equivalent to a genuine
non-loopback peer.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiohttp
import pytest
import websockets
from aiohttp.test_utils import TestServer

from conftest import LAYOUTS_DIR, make_test_server

PASSWORD = "s3cret-shared-password"


@asynccontextmanager
async def _serve(
    *, password: str | None, loopback: bool
) -> AsyncIterator[tuple[int, object]]:
    server, _scroll, _key, _dbus = make_test_server(
        layouts_dir=LAYOUTS_DIR, password=password
    )
    # Force every request onto the remote (or loopback) path regardless of
    # the real 127.0.0.1 peer address.
    server._is_loopback = lambda _req: loopback  # type: ignore[assignment]
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    try:
        yield ts.port or 0, server
    finally:
        await ts.close()
        await server.scroll.close()


async def _recv(ws, timeout: float = 2.0) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


async def test_ws_remote_without_password_rejected() -> None:
    async with _serve(password=PASSWORD, loopback=False) as (port, _):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(json.dumps({"type": "hello", "client": "web"}))
            msg = await _recv(ws)
            assert msg == {"type": "error", "reason": "unauthorized"}
            with pytest.raises(websockets.ConnectionClosed):
                await _recv(ws)


async def test_ws_remote_with_wrong_password_rejected() -> None:
    async with _serve(password=PASSWORD, loopback=False) as (port, _):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(
                json.dumps({"type": "hello", "client": "web", "password": "nope"})
            )
            msg = await _recv(ws)
            assert msg == {"type": "error", "reason": "unauthorized"}
            with pytest.raises(websockets.ConnectionClosed):
                await _recv(ws)


async def test_ws_remote_with_correct_password_accepted() -> None:
    async with _serve(password=PASSWORD, loopback=False) as (port, _):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(
                json.dumps({"type": "hello", "client": "web", "password": PASSWORD})
            )
            layout = await _recv(ws)
            assert layout["type"] == "layout"
            assert len(layout["widgets"]) > 0


async def test_ws_loopback_needs_no_password() -> None:
    async with _serve(password=PASSWORD, loopback=True) as (port, _):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            # Loopback pushes the layout immediately; hello may follow.
            layout = await _recv(ws)
            assert layout["type"] == "layout"
            await ws.send(json.dumps({"type": "hello", "client": "web"}))


async def test_ws_no_auth_configured_needs_no_password() -> None:
    """With no password set, even a 'remote' peer connects freely."""
    async with _serve(password=None, loopback=False) as (port, _):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            layout = await _recv(ws)
            assert layout["type"] == "layout"


# ---------------------------------------------------------------------------
# HTTP control endpoints
# ---------------------------------------------------------------------------


async def test_http_remote_without_password_is_401() -> None:
    async with _serve(password=PASSWORD, loopback=False) as (port, _):
        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/reload") as r:
                assert r.status == 401
            async with http.post(f"http://127.0.0.1:{port}/layout/firefox") as r:
                assert r.status == 401


async def test_http_remote_with_wrong_password_is_401() -> None:
    async with _serve(password=PASSWORD, loopback=False) as (port, _):
        headers = {"X-Deckd-Password": "wrong"}
        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/reload", headers=headers) as r:
                assert r.status == 401


async def test_http_remote_with_correct_password_ok() -> None:
    async with _serve(password=PASSWORD, loopback=False) as (port, _):
        headers = {"X-Deckd-Password": PASSWORD}
        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/reload", headers=headers) as r:
                assert r.status == 200
            async with http.post(
                f"http://127.0.0.1:{port}/layout/firefox", headers=headers
            ) as r:
                assert r.status == 200


async def test_http_loopback_needs_no_password() -> None:
    async with _serve(password=PASSWORD, loopback=True) as (port, _):
        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/reload") as r:
                assert r.status == 200


async def test_password_value_never_logged_after_startup(caplog) -> None:
    """Acceptance: the daemon never logs the password value at any level
    while handling connections. Only the one-time generation WARN (which
    lives in ``auth``, not exercised here) may contain it."""
    async with _serve(password=PASSWORD, loopback=False) as (port, _):
        with caplog.at_level("DEBUG", logger="deckd"):
            # A rejected attempt (wrong password) and an accepted one both
            # touch the auth path; neither should echo the secret.
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                await ws.send(
                    json.dumps({"type": "hello", "client": "web", "password": "wrong"})
                )
                await _recv(ws)  # unauthorized
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
                await ws.send(
                    json.dumps({"type": "hello", "client": "web", "password": PASSWORD})
                )
                await _recv(ws)  # layout
            async with aiohttp.ClientSession() as http:
                async with http.post(
                    f"http://127.0.0.1:{port}/reload",
                    headers={"X-Deckd-Password": PASSWORD},
                ) as r:
                    assert r.status == 200

    for record in caplog.records:
        assert PASSWORD not in record.getMessage(), (
            f"password leaked in {record.levelname} log: {record.getMessage()!r}"
        )


async def test_loopback_addr_classification() -> None:
    from deckd.server import _is_loopback_addr

    assert _is_loopback_addr("127.0.0.1") is True
    assert _is_loopback_addr("::1") is True
    assert _is_loopback_addr("::ffff:127.0.0.1") is True
    assert _is_loopback_addr("192.168.1.5") is False
    assert _is_loopback_addr("10.0.0.1") is False
    assert _is_loopback_addr(None) is False
    assert _is_loopback_addr("not-an-ip") is False
