"""Shared-password auth at the WS + HTTP boundary (issue #16).

The model is deliberately simple: when a password is configured, EVERY
WebSocket and HTTP control connection must present it — there is no
source-address (loopback) exemption. The password rides in the ``hello``
frame / the ``X-Deckd-Password`` header, so this stays correct behind any
proxy. ``--no-auth`` (password=None) turns it off entirely.
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
async def _serve(*, password: str | None) -> AsyncIterator[tuple[int, object]]:
    server, _scroll, _key, _dbus = make_test_server(
        layouts_dir=LAYOUTS_DIR, password=password
    )
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


async def test_ws_without_password_rejected() -> None:
    async with _serve(password=PASSWORD) as (port, _):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(json.dumps({"type": "hello", "client": "web"}))
            assert await _recv(ws) == {"type": "error", "reason": "unauthorized"}
            with pytest.raises(websockets.ConnectionClosed):
                await _recv(ws)


async def test_ws_with_wrong_password_rejected() -> None:
    async with _serve(password=PASSWORD) as (port, _):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(
                json.dumps({"type": "hello", "client": "web", "password": "nope"})
            )
            assert await _recv(ws) == {"type": "error", "reason": "unauthorized"}
            with pytest.raises(websockets.ConnectionClosed):
                await _recv(ws)


async def test_ws_with_correct_password_accepted() -> None:
    async with _serve(password=PASSWORD) as (port, _):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(
                json.dumps({"type": "hello", "client": "web", "password": PASSWORD})
            )
            layout = await _recv(ws)
            assert layout["type"] == "layout"
            assert len(layout["widgets"]) > 0


async def test_ws_no_auth_configured_needs_no_password() -> None:
    """With --no-auth (password=None) the hello need carry nothing."""
    async with _serve(password=None) as (port, _):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            await ws.send(json.dumps({"type": "hello", "client": "web"}))
            layout = await _recv(ws)
            assert layout["type"] == "layout"


# ---------------------------------------------------------------------------
# HTTP control endpoints
# ---------------------------------------------------------------------------


async def test_http_without_password_is_401() -> None:
    async with _serve(password=PASSWORD) as (port, _):
        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/reload") as r:
                assert r.status == 401
            async with http.post(f"http://127.0.0.1:{port}/layout/firefox") as r:
                assert r.status == 401


async def test_http_with_wrong_password_is_401() -> None:
    async with _serve(password=PASSWORD) as (port, _):
        headers = {"X-Deckd-Password": "wrong"}
        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/reload", headers=headers) as r:
                assert r.status == 401


async def test_http_with_correct_password_ok() -> None:
    async with _serve(password=PASSWORD) as (port, _):
        headers = {"X-Deckd-Password": PASSWORD}
        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/reload", headers=headers) as r:
                assert r.status == 200
            async with http.post(
                f"http://127.0.0.1:{port}/layout/firefox", headers=headers
            ) as r:
                assert r.status == 200


async def test_http_no_auth_configured_needs_no_password() -> None:
    async with _serve(password=None) as (port, _):
        async with aiohttp.ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/reload") as r:
                assert r.status == 200


async def test_health_is_open_even_with_auth_on() -> None:
    """/health is the one endpoint left unauthenticated (read-only)."""
    async with _serve(password=PASSWORD) as (port, _):
        async with aiohttp.ClientSession() as http:
            async with http.get(f"http://127.0.0.1:{port}/health") as r:
                assert r.status == 200
                body = await r.json()
    assert body["ok"] is True


# ---------------------------------------------------------------------------
# The password value must never appear in post-startup logs.
# ---------------------------------------------------------------------------


async def test_password_value_never_logged_after_startup(caplog) -> None:
    async with _serve(password=PASSWORD) as (port, _):
        with caplog.at_level("DEBUG", logger="deckd"):
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
