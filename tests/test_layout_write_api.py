"""HTTP write API tests for ``PUT /layouts/{id}`` (save) and ``POST /layouts``
(create) — issue #99, mirroring the #94 PUT contract.

Black-box at the aiohttp boundary (seam S4): auth gate, structured sanitized
``400``s, ``404`` unknown id, ``409`` rename / collision, and the ``200``
canonical re-read echo. A final test exercises the ``watchfiles`` watcher so
an editor save round-trips into the live layout store.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from conftest import make_test_server

PASSWORD = "s3cret"


def _default_yaml() -> str:
    return "match:\n  - default\nwidgets: []\n"


def _firefox_yaml() -> str:
    # The leading comment exercises comment preservation through a save.
    return (
        "# firefox layout — browser nav\n"
        "match:\n  - firefox\n"
        "widgets:\n"
        "  - id: back\n    kind: button\n    label: Back\n"
        "    action:\n      shell: echo back\n"
    )


def _firefox_snapshot(label: str = "Back") -> dict:
    return {
        "match": ["firefox"],
        "widgets": [
            {
                "id": "back",
                "kind": "button",
                "label": label,
                "action": {"shell": "echo back"},
            }
        ],
    }


async def _serve(tmp_path: Path, *, password: str | None = None):
    (tmp_path / "default.yaml").write_text(_default_yaml())
    (tmp_path / "firefox.yaml").write_text(_firefox_yaml())
    server, _scroll, _key, _dbus = make_test_server(
        layouts_dir=tmp_path, password=password
    )
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    return server, ts


# ---------------------------------------------------------------------------
# PUT /layouts/{id} — save
# ---------------------------------------------------------------------------


async def test_put_save_canonical_re_read(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.put(
                f"http://127.0.0.1:{port}/layouts/firefox",
                json=_firefox_snapshot(label="Backward"),
            ) as r:
                assert r.status == 200
                body = await r.json()
        assert body["ok"] is True
        assert body["layout"]["id"] == "firefox"
        assert body["layout"]["match"] == ["firefox"]
        assert body["layout"]["widgets"][0]["label"] == "Backward"

        # Comment preserved through the reconcile-and-write round-trip.
        text = (tmp_path / "firefox.yaml").read_text()
        assert "# firefox layout — browser nav" in text
        # The live store reloaded the edit (the watcher does this in
        # production; here we drive the same reload the watcher would).
        server.reload_layouts()
        assert server.layouts["firefox"].widgets[0].label == "Backward"
    finally:
        await ts.close()
        await server.scroll.close()


async def test_put_save_404_unknown_id(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.put(
                f"http://127.0.0.1:{port}/layouts/ghost",
                json={"match": ["ghost"], "widgets": []},
            ) as r:
                assert r.status == 404
                body = await r.json()
        assert body["ok"] is False
        assert "unknown" in body["error"]
    finally:
        await ts.close()
        await server.scroll.close()


async def test_put_save_409_when_match0_renames(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.put(
                f"http://127.0.0.1:{port}/layouts/firefox",
                json={"match": ["chrome"], "widgets": []},
            ) as r:
                assert r.status == 409
        # The original file is untouched on a rejected save.
        assert (tmp_path / "firefox.yaml").read_text() == _firefox_yaml()
        assert (tmp_path / "chrome.yaml").exists() is False
    finally:
        await ts.close()
        await server.scroll.close()


async def test_put_save_400_sanitized_validation_errors(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.put(
                f"http://127.0.0.1:{port}/layouts/firefox",
                json={
                    "match": ["firefox"],
                    "widgets": [
                        {"id": "w", "kind": "button"},
                        {"id": "w", "kind": "button"},
                    ],
                },
            ) as r:
                assert r.status == 400
                body = await r.json()
        assert body["ok"] is False
        assert body["error"] == "validation failed"
        assert isinstance(body["details"], list)
        assert body["details"]
        # Sanitization: only loc/msg/type, never the offending payload.
        detail = body["details"][0]
        assert set(detail.keys()) == {"loc", "msg", "type"}
        assert "duplicate widget id" in detail["msg"]
    finally:
        await ts.close()
        await server.scroll.close()


async def test_put_save_400_rejects_unknown_field_sanitized(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.put(
                f"http://127.0.0.1:{port}/layouts/firefox",
                json={"match": ["firefox"], "widgets": [], "bogus": 1},
            ) as r:
                assert r.status == 400
                body = await r.json()
        assert body["ok"] is False
        assert body["error"] == "validation failed"
        detail = body["details"][0]
        assert set(detail.keys()) == {"loc", "msg", "type"}
    finally:
        await ts.close()
        await server.scroll.close()


async def test_put_save_401_when_auth_configured(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path, password=PASSWORD)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.put(
                f"http://127.0.0.1:{port}/layouts/firefox",
                json=_firefox_snapshot(),
            ) as r:
                assert r.status == 401
    finally:
        await ts.close()
        await server.scroll.close()


async def test_put_save_200_with_auth_header(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path, password=PASSWORD)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.put(
                f"http://127.0.0.1:{port}/layouts/firefox",
                json=_firefox_snapshot(),
                headers={"X-Deckd-Password": PASSWORD},
            ) as r:
                assert r.status == 200
                body = await r.json()
        assert body["ok"] is True
    finally:
        await ts.close()
        await server.scroll.close()


# ---------------------------------------------------------------------------
# POST /layouts — create
# ---------------------------------------------------------------------------


def _slack_snapshot(label: str = "Snooze") -> dict:
    return {
        "match": ["Slack"],
        "widgets": [
            {"id": "snooze", "kind": "button", "label": label, "action": {"shell": "echo snooze"}}
        ],
    }


async def test_post_create_writes_new_file_canonical(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{port}/layouts", json=_slack_snapshot()
            ) as r:
                assert r.status == 200
                body = await r.json()
        assert body["ok"] is True
        # Filename derived from slugified match[0] (Slack -> slack.yaml);
        # canonical id = match[0] verbatim.
        assert body["layout"]["id"] == "Slack"
        assert body["layout"]["match"] == ["Slack"]
        on_disk = (tmp_path / "slack.yaml").read_text()
        assert "match:" in on_disk
        assert "- Slack" in on_disk
        # No stored id key — it's derived from match[0] on re-read.
        assert "\nid:" not in on_disk
    finally:
        await ts.close()
        await server.scroll.close()


async def test_post_create_409_on_existing_id(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{port}/layouts",
                json=_firefox_snapshot(),
            ) as r:
                assert r.status == 409
                body = await r.json()
        assert body["ok"] is False
        assert "already exists" in body["error"]
        # Rejected create must not write or clobber a file.
        assert (tmp_path / "firefox.yaml").read_text() == _firefox_yaml()
    finally:
        await ts.close()
        await server.scroll.close()


async def test_post_create_409_on_slug_collision_different_case(tmp_path: Path) -> None:
    # Existing id `Slack` (from a prior create) and a new `slack` slugify to the
    # same filename — the file-existence check catches it even though the ids
    # differ.
    server, ts = await _serve(tmp_path)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{port}/layouts", json=_slack_snapshot()
            ) as r:
                assert r.status == 200  # first create ok
            async with http.post(
                f"http://127.0.0.1:{port}/layouts",
                json={
                    "match": ["slack"],
                    "widgets": [],
                },
            ) as r:
                assert r.status == 409
    finally:
        await ts.close()
        await server.scroll.close()


async def test_post_create_400_empty_match(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{port}/layouts",
                json={"match": [], "widgets": []},
            ) as r:
                assert r.status == 400
                body = await r.json()
        # Mirrors PUT's sanitized structured 400 (issue #88): a derivation
        # failure rides the same {ok, error, details} envelope.
        assert body["ok"] is False
        assert body["error"] == "validation failed"
        assert set(body["details"][0].keys()) == {"loc", "msg", "type"}
        assert body["details"][0]["loc"] == ["match"]
        assert "match" in body["details"][0]["msg"]
    finally:
        await ts.close()
        await server.scroll.close()


async def test_post_create_400_unslugifiable_match_token(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{port}/layouts",
                json={"match": ["***"], "widgets": []},
            ) as r:
                assert r.status == 400
                body = await r.json()
        assert body["error"] == "validation failed"
        detail = body["details"][0]
        assert set(detail.keys()) == {"loc", "msg", "type"}
        assert detail["loc"] == ["match", 0]
    finally:
        await ts.close()
        await server.scroll.close()


async def test_post_create_400_sanitized_validation_errors(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{port}/layouts",
                json={"match": ["slack"], "bogus": 1},
            ) as r:
                assert r.status == 400
                body = await r.json()
        assert body["error"] == "validation failed"
        assert set(body["details"][0].keys()) == {"loc", "msg", "type"}
    finally:
        await ts.close()
        await server.scroll.close()


async def test_post_create_401_when_auth_configured(tmp_path: Path) -> None:
    server, ts = await _serve(tmp_path, password=PASSWORD)
    port = ts.port
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{port}/layouts", json=_slack_snapshot()
            ) as r:
                assert r.status == 401
        # Auth'd create still succeeds with the header.
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{port}/layouts",
                json=_slack_snapshot(),
                headers={"X-Deckd-Password": PASSWORD},
            ) as r:
                assert r.status == 200
    finally:
        await ts.close()
        await server.scroll.close()


async def test_post_create_reloads_via_watchfiles(tmp_path: Path) -> None:
    """A save round-trips through the watchfiles watcher into the live store."""
    server, ts = await _serve(tmp_path)
    port = ts.port
    server.start_layouts_watcher()
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{port}/layouts", json=_slack_snapshot()
            ) as r:
                assert r.status == 200
        # The watcher reloads asynchronously; poll for at most a couple seconds.
        for _ in range(40):
            if "Slack" in server.layouts:
                break
            await asyncio.sleep(0.05)
        assert "Slack" in server.layouts
        assert server.layouts["Slack"].widgets[0].label == "Snooze"
    finally:
        await server.stop()
        await ts.close()
        await server.scroll.close()