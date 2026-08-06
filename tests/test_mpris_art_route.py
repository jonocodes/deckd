"""HTTP-level test for the unauthenticated MPRIS album-art proxy route.

Mirrors ``test_media_art_route.py`` for the VLC widget: the daemon
streams the row's current ``mpris:artUrl`` so the client never needs
local-file access to the host's cache or outbound network
credentials. The proxy reads only the URL the backend's cached
``Metadata`` reported for the row — it never accepts a client-supplied
URL — and serves one of the three supported shapes
(``file://`` / ``http(s)://`` / ``data:``) verbatim, 404s on
everything else (issue #57).
"""
from __future__ import annotations

import base64
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

from deckd.input import ScrollController
from deckd.layouts import Layout, Widget
from deckd.mpris import FakeMprisBackend
from deckd.server import Server

from conftest import FakeScrollSink, LAYOUTS_DIR


@dataclass
class _MprisArtFixture:
    """A pair of (client, backend, resolver) for the proxy tests.

    The backend is exposed so individual tests can populate its
    ``art_urls`` table after the server is up but before the request
    is sent. The resolver is the same callable the proxy invokes —
    a dict-backed stub the tests can populate per URL.
    """

    client: TestClient
    backend: FakeMprisBackend
    resolver: dict[str, tuple[str, bytes]]


def _nowplaying_layout() -> Layout:
    return Layout(
        id="mpris",
        widgets=[Widget(id="browser", kind="nowplaying", size=[4, 2])],
    )


class _FakeMprisWithArt(FakeMprisBackend):
    """``FakeMprisBackend`` that lets tests drive the proxy's
    ``art_url(row_id)`` without touching a real bus.

    ``row_ids`` defaults to the ``states`` keys but can be
    overridden via :attr:`row_ids_override` for tests that want to
    exercise the proxy for a row with no ``MediaState``.
    """

    def __init__(self) -> None:
        super().__init__()
        self._row_ids_override: list[str] | None = None

    def set_row_art(self, row_id: str, url: str) -> None:
        self.art_urls[row_id] = url

    def row_ids(self) -> list[str]:
        if self._row_ids_override is not None:
            return list(self._row_ids_override)
        return list(self.states)


@pytest_asyncio.fixture
async def mpris_art_client() -> AsyncIterator[_MprisArtFixture]:
    backend = _FakeMprisWithArt()
    # The resolver is the seam the proxy's URL→bytes step uses;
    # tests inject a dict-backed stub so the suite never reads a
    # real file or opens a real socket.
    resolver_table: dict[str, tuple[str, bytes]] = {}

    async def _resolver(url: str | None) -> tuple[str, bytes] | None:
        if url is None:
            return None
        return resolver_table.get(url)

    server = Server(
        layouts_dir=LAYOUTS_DIR,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        mpris_backend=backend,
        mpris_art_resolver=_resolver,
    )
    server._current_layout = _nowplaying_layout()
    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        yield _MprisArtFixture(
            client=client, backend=backend, resolver=resolver_table
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mpris_art_route_streams_file_url_bytes(
    mpris_art_client: _MprisArtFixture,
) -> None:
    """A ``file://`` artUrl is read server-side and streamed back as
    the bytes the file holds. Cache-Control stays immutable so a
    reload reuses the browser cache until the track changes."""
    mpris_art_client.backend.set_row_art(
        "vlc", "file:///tmp/some-fake-path.png"
    )
    mpris_art_client.resolver["file:///tmp/some-fake-path.png"] = (
        "image/png",
        b"PNGDATA",
    )
    resp = await mpris_art_client.client.get("/mpris/vlc/art?token=abc")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert "immutable" in resp.headers.get("Cache-Control", "")
    assert await resp.read() == b"PNGDATA"


@pytest.mark.asyncio
async def test_mpris_art_route_streams_http_url_bytes(
    mpris_art_client: _MprisArtFixture,
) -> None:
    """An ``https://`` artUrl is fetched server-side (the phone has
    no need to reach out itself or carry credentials). The proxy
    passes through the bytes and the content type the upstream
    returned."""
    mpris_art_client.backend.set_row_art(
        "spotify", "https://example.com/cover.jpg"
    )
    mpris_art_client.resolver["https://example.com/cover.jpg"] = (
        "image/jpeg",
        b"JPEGBYTES",
    )
    resp = await mpris_art_client.client.get("/mpris/spotify/art?token=def")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/jpeg"
    assert "immutable" in resp.headers.get("Cache-Control", "")
    assert await resp.read() == b"JPEGBYTES"


@pytest.mark.asyncio
async def test_mpris_art_route_streams_data_url_bytes(
    mpris_art_client: _MprisArtFixture,
) -> None:
    """A ``data:`` artUrl (a few players inline the cover to avoid
    the cache-file race) is decoded server-side and streamed back.
    The ``data:`` URL is opaque to the client; only the resolved
    bytes travel."""
    payload = base64.b64encode(b"INLINEPNG").decode()
    mpris_art_client.backend.set_row_art(
        "firefox", f"data:image/png;base64,{payload}"
    )
    mpris_art_client.resolver[f"data:image/png;base64,{payload}"] = (
        "image/png",
        b"INLINEPNG",
    )
    resp = await mpris_art_client.client.get("/mpris/firefox/art?token=ghi")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert await resp.read() == b"INLINEPNG"


@pytest.mark.asyncio
async def test_mpris_art_route_404_for_unknown_row(
    mpris_art_client: _MprisArtFixture,
) -> None:
    """A row the backend doesn't know about (or has no art for) 404s
    rather than 200-ing an empty body. The client catches the error
    and falls back to the disc icon."""
    resp = await mpris_art_client.client.get("/mpris/nope/art?token=anything")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_mpris_art_route_404_for_row_with_no_art(
    mpris_art_client: _MprisArtFixture,
) -> None:
    """A known row with no ``mpris:artUrl`` (e.g. a player that
    hasn't published a cover yet) 404s so the client falls back to
    the desktop-entry brand icon or the disc glyph."""
    mpris_art_client.backend._row_ids_override = ["vlc"]
    resp = await mpris_art_client.client.get("/mpris/vlc/art")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_mpris_art_route_does_not_serve_client_supplied_url(
    mpris_art_client: _MprisArtFixture,
) -> None:
    """The proxy never reads a URL from the request — only from the
    row's current backend cache. The row is the only thing the URL
    the proxy serves is keyed on, so a client can't redirect the
    art to an arbitrary path (issue #57 security note)."""
    # Backend knows vlc, but its artUrl is unset.
    mpris_art_client.backend._row_ids_override = ["vlc"]
    resp = await mpris_art_client.client.get(
        "/mpris/vlc/art?file=file:///etc/passwd"
    )
    assert resp.status == 404
