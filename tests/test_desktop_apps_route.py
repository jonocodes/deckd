"""HTTP tests for the ``desktop`` icon source's routes (issue #187).

``GET /desktop-apps`` lists installed apps for the editor's icon picker
(authenticated, like the editor's other reads). ``GET
/desktop-apps/<id>/icon`` serves one app's icon to an ``<img>`` tag
(unauthenticated, like the album-art proxies: icons are low-value and
an ``<img>`` can't carry the password header). The icon route only
serves ids the resolver indexed — a client string never becomes a path.
"""
from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

from deckd.desktop_icons import DesktopIconIndex
from deckd.input import ScrollController
from deckd.server import Server

from conftest import FakeScrollSink, DECKS_DIR

PASSWORD = "hunter2"


def _install(data: Path, desktop_id: str, name: str, icon_file: str, payload: bytes) -> None:
    entry = data / "applications" / f"{desktop_id}.desktop"
    entry.parent.mkdir(parents=True, exist_ok=True)
    stem = icon_file.rsplit(".", 1)[0]
    entry.write_text(f"[Desktop Entry]\nType=Application\nName={name}\nIcon={stem}\n")
    size = "scalable" if icon_file.endswith(".svg") else "256x256"
    icon = data / "icons" / "hicolor" / size / "apps" / icon_file
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(payload)


@asynccontextmanager
async def _client(data: Path, password: str | None = None) -> AsyncIterator[TestClient]:
    server = Server(
        decks_dir=DECKS_DIR,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        password=password,
        desktop_icons=DesktopIconIndex([data]),
    )
    client = TestClient(TestServer(server.app))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
def host_apps(tmp_path: Path) -> Path:
    _install(tmp_path, "com.gexperts.Tilix", "Tilix", "com.gexperts.Tilix.svg", b"<svg/>")
    _install(tmp_path, "org.videolan.VLC", "VLC", "vlc.png", b"\x89PNG-bytes")
    return tmp_path


@pytest.mark.asyncio
async def test_icon_route_serves_svg_with_hardening_headers(host_apps: Path) -> None:
    async with _client(host_apps) as client:
        resp = await client.get("/desktop-apps/com.gexperts.Tilix/icon")
        assert resp.status == 200
        assert resp.content_type == "image/svg+xml"
        assert await resp.read() == b"<svg/>"
        # An SVG opened top-level on the daemon origin must not run script:
        # a hostile app's icon could otherwise read the stored password.
        assert "sandbox" in resp.headers["Content-Security-Policy"]
        assert "default-src 'none'" in resp.headers["Content-Security-Policy"]
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert "max-age" in resp.headers["Cache-Control"]


@pytest.mark.asyncio
async def test_icon_route_serves_png(host_apps: Path) -> None:
    async with _client(host_apps) as client:
        resp = await client.get("/desktop-apps/org.videolan.VLC/icon")
        assert resp.status == 200
        assert resp.content_type == "image/png"
        assert await resp.read() == b"\x89PNG-bytes"


@pytest.mark.asyncio
async def test_icon_route_needs_no_password(host_apps: Path) -> None:
    async with _client(host_apps, password=PASSWORD) as client:
        resp = await client.get("/desktop-apps/org.videolan.VLC/icon")
        assert resp.status == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/desktop-apps/not.installed/icon",
        "/desktop-apps/..%2F..%2Fetc%2Fpasswd/icon",
        "/desktop-apps/%2Fetc%2Fpasswd/icon",
        "/desktop-apps/../../etc/passwd/icon",
    ],
)
async def test_icon_route_404s_unknown_and_traversal_ids(host_apps: Path, path: str) -> None:
    async with _client(host_apps) as client:
        resp = await client.get(path)
        assert resp.status == 404


@pytest.mark.asyncio
async def test_list_route_returns_sorted_apps(host_apps: Path) -> None:
    async with _client(host_apps) as client:
        resp = await client.get("/desktop-apps")
        assert resp.status == 200
        assert await resp.json() == {
            "ok": True,
            "apps": [
                {"id": "com.gexperts.Tilix", "name": "Tilix"},
                {"id": "org.videolan.VLC", "name": "VLC"},
            ],
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "status"),
    [({}, 401), ({"X-Deckd-Password": "wrong"}, 401), ({"X-Deckd-Password": PASSWORD}, 200)],
)
async def test_list_route_requires_password_when_set(
    host_apps: Path, headers: dict[str, str], status: int
) -> None:
    async with _client(host_apps, password=PASSWORD) as client:
        resp = await client.get("/desktop-apps", headers=headers)
        assert resp.status == status


@pytest.mark.asyncio
async def test_list_route_empty_when_no_apps(tmp_path: Path) -> None:
    """macOS / a bare host: no XDG data, so the picker's tab is just empty."""
    async with _client(tmp_path) as client:
        resp = await client.get("/desktop-apps")
        assert await resp.json() == {"ok": True, "apps": []}
