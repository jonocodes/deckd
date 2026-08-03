"""HTTP integration tests for the diagnostic endpoints (issue #70/71/72).

Covers ``/diag``, ``/layouts``, ``/actions/recent``, ``/metrics``,
``/mpris/players``, ``/mpris/events/recent``, and
``POST /mpris/{row}/command``. The fixture loads the stable
``tests/fixtures/layouts/`` YAML so widget ids and action shapes stay
deterministic across runs.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp
import pytest

from conftest import ServerHandle

from deckd import PASSWORD_HEADER


# ---------------------------------------------------------------------------
# /diag
# ---------------------------------------------------------------------------


async def test_diag_open_auth(srv: ServerHandle) -> None:
    """/diag must work without the password (issue #70). Issue #66
    adds ``bind``, ``addresses``, and ``url`` to the same surface so
    operators can confirm the bind list without a separate call."""
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/diag") as r:
            assert r.status == 200
            body = await r.json()
    assert body["ok"] is True
    for field in (
        "version",
        "uptime_s",
        "pid",
        "hostname",
        "os",
        "desktop",
        "host",
        "port",
        "auth",
        "focus",
        "input",
        "layouts",
        "sessions",
        "tasks",
        # Issue #66
        "bind",
        "addresses",
        "url",
    ):
        assert field in body, f"/diag missing {field!r}"
    assert body["host"] == "127.0.0.1"
    # When the daemon binds to ``port=0`` (``aiohttp`` picks one),
    # ``/diag`` should still surface the actually-listening port. The
    # fixture uses ``port=0`` so we assert ``body["port"]`` matches
    # the test server's bound port. The /health endpoint and the
    # ServerHandle agree on the port (``srv.port``).
    assert body["port"] == srv.port
    # Bind surface (issue #66). The fixture passes ``host="127.0.0.1"``
    # so the daemon resolves to a single IPv4 loopback bind.
    assert body["bind"] == ["127.0.0.1"]
    assert body["addresses"] == [f"127.0.0.1:{srv.port}"]
    assert body["url"] == f"http://127.0.0.1:{srv.port}/"


async def test_diag_reports_input_fallback(srv: ServerHandle) -> None:
    """The fixture's key sink is a ``FakePointerSink`` (no uinput),
    so ``/diag`` must report ``sink: FakePointerSink`` and the
    corresponding ``/metrics`` gauge must read 0."""
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/diag") as r:
            body = await r.json()
        async with http.get(f"{srv.http_url}/metrics") as r:
            text = await r.text()
    assert body["input"]["sink"] == "FakePointerSink"
    assert body["input"]["uinput_devnode"] is None
    assert "deckd_uinput_available 0" in text


async def test_diag_redacts_password(srv: ServerHandle) -> None:
    """The /diag block carries auth state but never the secret."""
    srv.server.password = "topsecret"
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/diag") as r:
            body = await r.json()
    assert body["auth"]["enabled"] is True
    raw = json.dumps(body)
    assert "topsecret" not in raw
    srv.server.password = None


async def test_diag_layouts_block_lists_loaded_layout_ids(srv: ServerHandle) -> None:
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/diag") as r:
            body = await r.json()
    assert "default" in body["layouts"]["ids"]
    assert "firefox" in body["layouts"]["ids"]


# ---------------------------------------------------------------------------
# /layouts
# ---------------------------------------------------------------------------


async def test_layouts_endpoint_hides_action_bodies(srv: ServerHandle) -> None:
    """``/layouts`` is safe to expose without the password: widget summaries,
    no shell/dbus strings. The editor's full dump (action/macro bodies) is
    gated on auth so the diagnostics page stays safe to open."""
    srv.server.password = "hunter2"
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/layouts") as r:
            body = await r.json()
    assert body["ok"] is True
    ids = {l["id"] for l in body["layouts"]}
    assert "default" in ids
    # Find one widget that has an action and confirm only the
    # ``has_action`` boolean is reported, not the action body.
    default_layout = next(l for l in body["layouts"] if l["id"] == "default")
    pressed = [w for w in default_layout["widgets"] if w.get("has_action")]
    assert pressed, "expected at least one widget with an action"
    for widget in pressed:
        assert "action" not in widget
        assert "shell" not in widget
        assert "dbus" not in widget
        assert "key" not in widget
    raw = json.dumps(body)
    assert "xdg-open" not in raw  # the shell action value
    assert "ctrl+t" not in raw  # the key action value


async def test_layouts_endpoint_includes_action_bodies_when_authenticated(
    srv: ServerHandle,
) -> None:
    """The editor's opaque pass-through (#89) needs the unrendered fields:
    an authenticated ``GET /layouts`` includes action/macro bodies."""
    srv.server.password = "hunter2"
    async with aiohttp.ClientSession() as http:
        async with http.get(
            f"{srv.http_url}/layouts", headers={PASSWORD_HEADER: "hunter2"}
        ) as r:
            body = await r.json()
    assert body["ok"] is True
    default_layout = next(l for l in body["layouts"] if l["id"] == "default")
    with_action = [w for w in default_layout["widgets"] if w.get("action")]
    assert with_action, "expected at least one widget with an action body"
    raw = json.dumps(body)
    assert "xdg-open" in raw  # the shell action value is now visible
    # Unset defaults are not materialised (#85 round-trip fidelity).
    assert "restore_clipboard" not in raw
    assert "restore_clipboard_delay_ms" not in raw


async def test_layouts_endpoint_includes_kind_specific_fields(srv: ServerHandle) -> None:
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/layouts") as r:
            body = await r.json()
    default_layout = next(l for l in body["layouts"] if l["id"] == "default")
    by_kind = {w["kind"]: w for w in default_layout["widgets"]}
    assert by_kind["jogstrip"]["kind"] == "jogstrip"


# ---------------------------------------------------------------------------
# /actions/recent
# ---------------------------------------------------------------------------


async def test_actions_recent_records_a_press(srv: ServerHandle) -> None:
    """A successful press records a recent-action entry."""
    import websockets

    async with websockets.connect(srv.ws_url) as ws:
        await ws.recv()  # initial layout
        await ws.send(json.dumps({"type": "press", "id": "open-url"}))
        await asyncio.sleep(0.05)

    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/actions/recent") as r:
            body = await r.json()
    assert body["ok"] is True
    assert body["events"], "expected at least one recent action"
    entry = body["events"][-1]
    assert entry["widget_id"] == "open-url"
    assert entry["layout_id"] == "default"
    assert entry["primitive"] == "shell"
    assert entry["outcome"] == "ok"
    # Action's command text is never exposed on the wire.
    raw = json.dumps(body)
    assert "xdg-open" not in raw


async def test_actions_recent_limit(srv: ServerHandle) -> None:
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/actions/recent?limit=2") as r:
            body = await r.json()
    assert len(body["events"]) <= 2


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------


async def test_metrics_renders_prometheus_text(srv: ServerHandle) -> None:
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/metrics") as r:
            assert r.status == 200
            assert r.content_type.startswith("text/plain")
            text = await r.text()
    # Required Prometheus preamble
    assert "# HELP deckd_up" in text
    assert "# TYPE deckd_up gauge" in text
    assert "deckd_up 1" in text
    assert "deckd_sessions_active" in text
    # Counters always render even at zero
    assert "deckd_layout_reload_total" in text
    assert "deckd_action_total" in text
    assert "deckd_mpris_command_total" in text


async def test_metrics_reflects_a_press(srv: ServerHandle) -> None:
    import websockets

    async with websockets.connect(srv.ws_url) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "press", "id": "send-key"}))
        await asyncio.sleep(0.05)

    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/metrics") as r:
            text = await r.text()
    # The send-key widget has a ``key`` action primitive; the action
    # counter should reflect at least one key/ok outcome.
    assert 'deckd_action_total{primitive="key"}' in text


# ---------------------------------------------------------------------------
# /mpris/* — exercised against the daemon's no-mpris default
# ---------------------------------------------------------------------------


async def test_mpris_players_no_backend(srv: ServerHandle) -> None:
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/mpris/players") as r:
            body = await r.json()
    assert body == {"ok": True, "available": False, "players": []}


async def test_mpris_events_recent_no_backend(srv: ServerHandle) -> None:
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/mpris/events/recent") as r:
            body = await r.json()
    assert body == {"ok": True, "events": []}


async def test_mpris_command_no_backend(srv: ServerHandle) -> None:
    async with aiohttp.ClientSession() as http:
        async with http.post(
            f"{srv.http_url}/mpris/vlc/command",
            json={"command": "play-pause"},
        ) as r:
            assert r.status == 503
            body = await r.json()
    assert body["ok"] is False
    assert "no MPRIS backend" in body["error"]


# ---------------------------------------------------------------------------
# /mpris/* with an injected FakeMprisBackend
# ---------------------------------------------------------------------------


async def test_mpris_players_with_fake_backend(monkeypatch, tmp_path) -> None:
    """With a fake backend wired, ``/mpris/players`` reports the rows
    without leaking ``art_url``."""
    from aiohttp.test_utils import TestServer
    from deckd.media import MediaState
    from deckd.mpris import FakeMprisBackend
    from conftest import FakeScrollSink, FakePointerSink, FakeDbusBusFactory

    fake = FakeMprisBackend(
        states={
            "vlc": MediaState(available=True, playing=True, title="track"),
            "firefox": MediaState(available=True, playing=False),
        }
    )
    fake.art_urls["vlc"] = "file:///secret/cover.jpg"

    (tmp_path / "default.yaml").write_text(
        """
match: [default]
widgets:
  - id: mpris
    kind: mediabrowser
    size: [4, 1]
"""
    )

    server = type("S", (), {})()
    from deckd.server import Server
    from deckd.input import ScrollController

    server = Server(
        layouts_dir=tmp_path,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        key_sink=FakePointerSink(),
        dbus_bus_factory=FakeDbusBusFactory(),
        mpris_backend=fake,
    )

    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(f"http://127.0.0.1:{test_server.port}/mpris/players") as r:
                body = await r.json()
        assert body["ok"] is True
        assert body["available"] is True
        assert {p["row_id"] for p in body["players"]} == {"vlc", "firefox"}
        assert any(p["has_art"] for p in body["players"])
        raw = json.dumps(body)
        assert "secret/cover.jpg" not in raw
    finally:
        await test_server.close()


async def test_mpris_command_dispatch_with_fake_backend(monkeypatch, tmp_path) -> None:
    from aiohttp.test_utils import TestServer
    from deckd.media import MediaState
    from deckd.mpris import FakeMprisBackend
    from deckd.server import Server
    from deckd.input import ScrollController
    from conftest import FakeScrollSink, FakePointerSink, FakeDbusBusFactory

    fake = FakeMprisBackend(states={"vlc": MediaState(available=True)})
    (tmp_path / "default.yaml").write_text("match: [default]\nwidgets: []\n")

    server = Server(
        layouts_dir=tmp_path,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        key_sink=FakePointerSink(),
        dbus_bus_factory=FakeDbusBusFactory(),
        mpris_backend=fake,
    )
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{ts.port}/mpris/vlc/command",
                json={"command": "play-pause"},
            ) as r:
                assert r.status == 200
                body = await r.json()
        assert body == {"ok": True, "row_id": "vlc", "command": "play-pause"}
        assert fake.commands == [("vlc", "play-pause")]
    finally:
        await ts.close()


async def test_mpris_command_rejects_unknown_command(tmp_path) -> None:
    from aiohttp.test_utils import TestServer
    from deckd.mpris import FakeMprisBackend
    from deckd.server import Server
    from deckd.input import ScrollController
    from conftest import FakeScrollSink, FakePointerSink, FakeDbusBusFactory

    fake = FakeMprisBackend(states={"vlc": None})
    (tmp_path / "default.yaml").write_text("match: [default]\nwidgets: []\n")
    server = Server(
        layouts_dir=tmp_path,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        key_sink=FakePointerSink(),
        dbus_bus_factory=FakeDbusBusFactory(),
        mpris_backend=fake,
    )
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{ts.port}/mpris/vlc/command",
                json={"command": "format-hard-drive"},
            ) as r:
                assert r.status == 400
    finally:
        await ts.close()


async def test_mpris_command_rejects_unknown_row(tmp_path) -> None:
    """A command for a row the backend doesn't list still goes through
    (the backend logs and no-ops), but the endpoint returns 200."""
    from aiohttp.test_utils import TestServer
    from deckd.mpris import FakeMprisBackend
    from deckd.server import Server
    from deckd.input import ScrollController
    from conftest import FakeScrollSink, FakePointerSink, FakeDbusBusFactory

    fake = FakeMprisBackend(states={"vlc": None})
    (tmp_path / "default.yaml").write_text("match: [default]\nwidgets: []\n")
    server = Server(
        layouts_dir=tmp_path,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        key_sink=FakePointerSink(),
        dbus_bus_factory=FakeDbusBusFactory(),
        mpris_backend=fake,
    )
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{ts.port}/mpris/spotify/command",
                json={"command": "play-pause"},
            ) as r:
                assert r.status == 200
    finally:
        await ts.close()


async def test_mpris_command_respects_auth(monkeypatch, tmp_path) -> None:
    """When the daemon runs with auth on, the endpoint demands the
    password header."""
    from aiohttp.test_utils import TestServer
    from deckd.media import MediaState
    from deckd.mpris import FakeMprisBackend
    from deckd.server import Server
    from deckd.input import ScrollController
    from conftest import FakeScrollSink, FakePointerSink, FakeDbusBusFactory

    fake = FakeMprisBackend(states={"vlc": MediaState(available=True)})
    (tmp_path / "default.yaml").write_text("match: [default]\nwidgets: []\n")
    server = Server(
        layouts_dir=tmp_path,
        host="127.0.0.1",
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        key_sink=FakePointerSink(),
        dbus_bus_factory=FakeDbusBusFactory(),
        mpris_backend=fake,
        password="hunter2",
    )
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    try:
        async with aiohttp.ClientSession() as http:
            # No password: 401
            async with http.post(
                f"http://127.0.0.1:{ts.port}/mpris/vlc/command",
                json={"command": "play-pause"},
            ) as r:
                assert r.status == 401
            # Wrong password: 401
            async with http.post(
                f"http://127.0.0.1:{ts.port}/mpris/vlc/command",
                json={"command": "play-pause"},
                headers={"X-Deckd-Password": "wrong"},
            ) as r:
                assert r.status == 401
            # Correct password: 200
            async with http.post(
                f"http://127.0.0.1:{ts.port}/mpris/vlc/command",
                json={"command": "play-pause"},
                headers={"X-Deckd-Password": "hunter2"},
            ) as r:
                assert r.status == 200
                body = await r.json()
                assert body["ok"] is True
    finally:
        await ts.close()


# ---------------------------------------------------------------------------
# dbcall timing — a press with a dbus action records a sample
# ---------------------------------------------------------------------------


async def test_metrics_records_dbcall_latency(srv: ServerHandle) -> None:
    import websockets

    # audio-toggle is the dbus: action in fixtures/default.yaml
    async with websockets.connect(srv.ws_url) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "press", "id": "audio-toggle"}))
        await asyncio.sleep(0.05)

    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/metrics") as r:
            text = await r.text()
    assert "deckd_dbcall_seconds_count" in text
    assert "deckd_dbcall_seconds_sum" in text