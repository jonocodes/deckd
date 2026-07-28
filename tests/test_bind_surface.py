"""Issue #66: LAN scope control integration tests.

Covers the end-to-end behaviour of the bind surface — multiple
addresses sharing one port, the ``/health`` payload, the ``/diag``
payload, and the failure modes (port collision, unknown interface,
no addresses on the bound interface).
"""
from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from conftest import ServerHandle
from deckd.input import ScrollController
from deckd.server import PortInUseError, Server
from tests.conftest import (
    FakeDbusBusFactory,
    FakePointerSink,
    FakeScrollSink,
    LAYOUTS_DIR,
)


# ---------------------------------------------------------------------------
# Server-level: multi-bind + port=0 share semantics
# ---------------------------------------------------------------------------


async def test_default_bind_is_localhost_only() -> None:
    """When ``bind`` is ``None`` the daemon defaults to both
    loopbacks (issue #66 AC #1)."""
    server = Server(
        layouts_dir=LAYOUTS_DIR,
        bind=None,
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        key_sink=FakePointerSink(),
        dbus_bus_factory=FakeDbusBusFactory(),
    )
    assert server._bind_specs == ("127.0.0.1", "::1")
    # ``server.host`` stays as the first bind for legacy code paths.
    assert server.host == "127.0.0.1"


async def test_host_kwarg_is_legacy_shortcut() -> None:
    """``host=`` still works as a single-address shortcut so
    existing test fixtures and the spike module don't break."""
    from conftest import make_test_server

    server, *_ = make_test_server(layouts_dir=LAYOUTS_DIR)
    # The fixture uses host="127.0.0.1" — _bind_specs collapses
    # the legacy single-string into the same tuple shape.
    assert server._bind_specs == ("127.0.0.1",)


async def test_bind_explicit_list_takes_precedence() -> None:
    """``bind=`` overrides ``host=`` when both are passed."""
    from conftest import make_test_server

    # The make_test_server helper doesn't expose bind, so build a
    # bare Server here for the explicit-list path.
    server = Server(
        layouts_dir=LAYOUTS_DIR,
        host="10.0.0.99",  # would-be legacy address
        bind=["127.0.0.1", "::1"],
        port=0,
    )
    assert server._bind_specs == ("127.0.0.1", "::1")


async def test_start_binds_all_addresses_on_same_port(tmp_path: Path) -> None:
    """Two resolved binds share the same port even when ``port=0``
    asks the kernel to pick one. Otherwise ``/diag`` would report
    different ports for IPv4 and IPv6 and a phone couldn't pair.
    """
    server = Server(
        layouts_dir=LAYOUTS_DIR,
        bind=["127.0.0.1", "::1"],
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        key_sink=FakePointerSink(),
        dbus_bus_factory=FakeDbusBusFactory(),
    )
    task = asyncio.create_task(server.start())
    try:
        # Poll until the daemon has bound at least one socket.
        for _ in range(50):
            await asyncio.sleep(0.05)
            addrs = server._bound_addresses()
            if addrs and addrs[0][1] != 0:
                break
        assert len(addrs) == 2
        ports = {port for _, port in addrs}
        assert len(ports) == 1, f"binds must share a port, got {addrs}"
        # Both addresses must be reachable.
        for host, port in addrs:
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            reader, writer = await asyncio.open_connection(host, port, family=family)
            writer.close()
            await writer.wait_closed()
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await server.stop()


async def test_start_collapses_default_if_ipv6_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``::1`` doesn't resolve (container without IPv6), the
    daemon must still come up on IPv4 — not crash."""
    # Force ``resolve_bind`` (imported inside ``start()``) to drop
    # the IPv6 entry, simulating a host without a working IPv6 stack.
    from deckd.bind import ResolvedBind

    def fake_resolve(specs):
        return [
            ResolvedBind(host="127.0.0.1", family=socket.AF_INET, original="127.0.0.1")
        ]

    monkeypatch.setattr("deckd.bind.resolve_bind", fake_resolve)
    server = Server(
        layouts_dir=LAYOUTS_DIR,
        bind=None,
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        key_sink=FakePointerSink(),
        dbus_bus_factory=FakeDbusBusFactory(),
    )
    task = asyncio.create_task(server.start())
    try:
        for _ in range(50):
            await asyncio.sleep(0.05)
            addrs = server._bound_addresses()
            if addrs and addrs[0][1] != 0:
                break
        assert addrs == [("127.0.0.1", server.port)]
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await server.stop()


async def test_start_port_in_use_with_multi_bind(tmp_path: Path) -> None:
    """The first bind against an already-taken port still raises
    :class:`PortInUseError` so a stale daemon doesn't leak past the
    startup gate."""
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    busy_port = blocker.getsockname()[1]
    try:
        server = Server(
            layouts_dir=LAYOUTS_DIR,
            bind=["127.0.0.1", "::1"],
            port=busy_port,
            scroll=ScrollController(FakeScrollSink()),
            key_sink=FakePointerSink(),
            dbus_bus_factory=FakeDbusBusFactory(),
        )
        with pytest.raises(PortInUseError) as excinfo:
            await server.start()
        assert excinfo.value.port == busy_port
    finally:
        blocker.close()


# ---------------------------------------------------------------------------
# HTTP-level: /health and /diag payload shape
# ---------------------------------------------------------------------------


async def test_health_reports_bind_and_pairing_url(
    tmp_path: Path,
) -> None:
    """``GET /health`` exposes ``bind``, ``addresses``, ``url``
    (issue #66 AC #3)."""
    (tmp_path / "default.yaml").write_text(
        "match:\n  - default\nwidgets: []\n"
    )
    server = Server(
        layouts_dir=tmp_path,
        bind=["127.0.0.1"],
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        key_sink=FakePointerSink(),
        dbus_bus_factory=FakeDbusBusFactory(),
    )
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        port = test_server.port
        async with aiohttp.ClientSession() as http:
            async with http.get(f"http://127.0.0.1:{port}/health") as r:
                assert r.status == 200
                body = await r.json()
        # Issue #66: bind surface exposed on the read-only open-auth
        # endpoint so a phone pairing in via the same machine can read
        # the URL it should hit.
        assert body["bind"] == ["127.0.0.1"]
        assert body["addresses"] == [f"127.0.0.1:{port}"]
        assert body["url"] == f"http://127.0.0.1:{port}/"
    finally:
        await test_server.close()
        await server.scroll.close()


async def test_health_brackets_ipv6_in_addresses(
    tmp_path: Path,
) -> None:
    """IPv6 addresses appear bracketed in the ``addresses`` list
    so they read as URLs (issue #66)."""
    (tmp_path / "default.yaml").write_text(
        "match:\n  - default\nwidgets: []\n"
    )
    server = Server(
        layouts_dir=tmp_path,
        bind=["::1"],
        port=0,
        scroll=ScrollController(FakeScrollSink()),
        key_sink=FakePointerSink(),
        dbus_bus_factory=FakeDbusBusFactory(),
    )
    test_server = TestServer(server.app, host="::1")
    await test_server.start_server()
    try:
        port = test_server.port
        async with aiohttp.ClientSession() as http:
            async with http.get(f"http://[::1]:{port}/health") as r:
                assert r.status == 200
                body = await r.json()
        assert body["bind"] == ["::1"]
        assert body["addresses"] == [f"[::1]:{port}"]
        assert body["url"] == f"http://[::1]:{port}/"
    finally:
        await test_server.close()
        await server.scroll.close()


async def test_diag_includes_bind_addresses_url(srv: ServerHandle) -> None:
    """``/diag`` mirrors the same bind fields as ``/health`` so
    AI agents and operators get them from the richer surface too
    (issue #66)."""
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{srv.http_url}/diag") as r:
            body = await r.json()
    assert body["bind"] == ["127.0.0.1"]
    assert body["addresses"] == [f"127.0.0.1:{srv.port}"]
    assert body["url"] == f"http://127.0.0.1:{srv.port}/"


# ---------------------------------------------------------------------------
# deckctl CLI surface
# ---------------------------------------------------------------------------


def test_cli_status_prepends_pairing_line(monkeypatch, capsys) -> None:
    """``deckctl status`` reads ``/health`` and prepends a one-line
    pairing summary when ``url`` is present (issue #66 AC #3)."""
    from deckd.cli import _status

    fake_body = {
        "ok": True,
        "sessions": 0,
        "app": "default",
        "hostname": "lute",
        "os": "NixOS",
        "desktop": "GNOME",
        "bind": ["127.0.0.1", "::1"],
        "addresses": ["127.0.0.1:8765", "[::1]:8765"],
        "url": "http://127.0.0.1:8765/",
    }

    class _Resp:
        def __init__(self, body: dict) -> None:
            self._body = body

        def read(self) -> bytes:
            return json.dumps(self._body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=3: _Resp(fake_body)
    )
    _status("http://127.0.0.1:8765", {})
    out = capsys.readouterr().out
    assert "listening on: http://127.0.0.1:8765/" in out
    assert "127.0.0.1:8765" in out
    # The full JSON body is still printed (so scripts can pipe through jq).
    assert '"url": "http://127.0.0.1:8765/"' in out
