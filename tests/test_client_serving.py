"""Client-bundle freshness: fingerprint, ``/health`` field, cache headers.

The daemon serves the built client itself (``--client-dist``). A phone that
kept an old shell — especially an installed PWA — must not keep driving it
after a rebuild. The server side of that contract: a content fingerprint on
``/health``, ``no-store`` on the shell and other unhashed files, immutable
caching on Vite's content-hashed ``/assets/*``. The client side lives in
``client/src/update-check.ts`` (unit-tested in ``update-check.test.ts``).
"""
from __future__ import annotations

from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from conftest import LAYOUTS_DIR, ServerHandle, make_test_server
from deckd.__main__ import _add_client_routes, _client_build_id


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A miniature Vite build output: shell, manifest, one hashed asset."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>v1</html>")
    (root / "manifest.json").write_text("{}")
    (root / "assets" / "index-abc123.js").write_text("console.log(1)")
    return root


def test_client_build_id_is_stable_and_content_sensitive(dist: Path) -> None:
    first = _client_build_id(dist)
    assert _client_build_id(dist) == first
    (dist / "assets" / "index-abc123.js").write_text("console.log(2)")
    assert _client_build_id(dist) != first


def test_client_build_id_covers_unhashed_files(dist: Path) -> None:
    """``manifest.json`` isn't content-hashed by Vite, so the walk — not the
    filename — has to make its edits visible."""
    first = _client_build_id(dist)
    (dist / "manifest.json").write_text('{"name": "deckd"}')
    assert _client_build_id(dist) != first


async def test_health_reports_client_build() -> None:
    server, *_ = make_test_server(layouts_dir=LAYOUTS_DIR, client_build="abc123def456")
    async with TestClient(TestServer(server.app, host="127.0.0.1")) as client:
        r = await client.get("/health")
        body = await r.json()
    assert body["client_build"] == "abc123def456"


async def test_health_omits_client_build_without_dist(srv: ServerHandle) -> None:
    """Dev-server / headless daemons have no bundle to fingerprint; the
    absent field is the client's "don't check" signal."""
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/health") as r:
            body = await r.json()
    assert "client_build" not in body


async def test_client_routes_set_freshness_cache_headers(dist: Path) -> None:
    server, *_ = make_test_server(layouts_dir=LAYOUTS_DIR)
    _add_client_routes(server, dist)
    async with TestClient(TestServer(server.app, host="127.0.0.1")) as client:
        root = await client.get("/")
        manifest = await client.get("/manifest.json")
        asset = await client.get("/assets/index-abc123.js")
        health = await client.get("/health")

    assert root.headers["Cache-Control"] == "no-store"
    assert manifest.headers["Cache-Control"] == "no-store"
    assert asset.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    # Non-client routes are untouched by the middleware.
    assert "Cache-Control" not in health.headers


async def test_extensionless_deep_links_serve_the_shell(dist: Path) -> None:
    """Client view routes (``/settings``, ``/editor``, ``/now-playing`` …)
    must survive a hard reload — the auto-reload at a deep link depends on
    it — while real dotted files still come from the static handler.

    Regression guard: the previous fallback regex anchored ``^`` inside the
    named group, so it matched nothing and every deep link 404'd once served
    by the daemon.
    """
    server, *_ = make_test_server(layouts_dir=LAYOUTS_DIR)
    _add_client_routes(server, dist)
    async with TestClient(TestServer(server.app, host="127.0.0.1")) as client:
        for path in ("/settings", "/editor", "/now-playing", "/windows", "/trackpad"):
            deep = await client.get(path)
            assert deep.status == 200, path
            assert "<html>v1</html>" in await deep.text(), path
            assert deep.headers["Cache-Control"] == "no-store", path

        asset = await client.get("/assets/index-abc123.js")
        asset_text = await asset.text()
        missing = await client.get("/nope.json")

    # The fallback must not swallow dotted paths…
    assert asset.status == 200
    assert asset_text == "console.log(1)"
    # …nor invent a shell for a missing file.
    assert missing.status == 404
