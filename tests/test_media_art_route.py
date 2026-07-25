"""HTTP-level test for the unauthenticated album-art proxy route."""
from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

from deckd.input import ScrollController
from deckd.layouts import Layout, MediaHttp, Widget
from deckd.server import Server

from conftest import FakeScrollSink, LAYOUTS_DIR


class _FakeMedia:
    """Stands in for MediaManager: returns fixed art, or None to force 404."""

    def __init__(self, art: tuple[str, bytes] | None) -> None:
        self._art = art
        self.calls: list[str] = []

    async def art(self, key: str, **_kw: object) -> tuple[str, bytes] | None:
        self.calls.append(key)
        return self._art


def _media_layout() -> Layout:
    return Layout(
        id="vlc",
        widgets=[
            Widget(
                id="vlc-media",
                kind="media",
                grid=[0, 0, 4, 2],
                controls=["play", "position"],
                media_http=MediaHttp(host="127.0.0.1", port=8080),
            )
        ],
    )


@pytest_asyncio.fixture
async def art_client(request) -> AsyncIterator[TestClient]:
    server = Server(
        layouts_dir=LAYOUTS_DIR,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        media_manager=request.param,
    )
    server._current_layout = _media_layout()
    client = TestClient(TestServer(server.app))
    await client.start_server()
    yield client
    await client.close()


@pytest.mark.parametrize("art_client", [_FakeMedia(("image/png", b"PNGDATA"))], indirect=True)
@pytest.mark.asyncio
async def test_art_route_streams_bytes(art_client: TestClient) -> None:
    resp = await art_client.get("/media/vlc-media/art?token=abc")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert "immutable" in resp.headers.get("Cache-Control", "")
    assert await resp.read() == b"PNGDATA"


@pytest.mark.parametrize("art_client", [_FakeMedia(None)], indirect=True)
@pytest.mark.asyncio
async def test_art_route_404_when_no_art(art_client: TestClient) -> None:
    resp = await art_client.get("/media/vlc-media/art")
    assert resp.status == 404


@pytest.mark.parametrize("art_client", [_FakeMedia(("image/png", b"x"))], indirect=True)
@pytest.mark.asyncio
async def test_art_route_404_for_unknown_widget(art_client: TestClient) -> None:
    resp = await art_client.get("/media/nope/art")
    assert resp.status == 404
