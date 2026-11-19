"""Health issues: missing OS permissions surfaced to the client (issue #195).

The daemon already knows when an OS permission it needs is missing (the
macOS Accessibility probe); these tests pin the channel that carries that
knowledge to the client:

* backend -> issue mapping (``PlatformBackend.health_issues``),
* the wire shape (``HealthMessage``),
* change-only pushes plus the connect replay,
* the poller that clears an issue without a restart,
* ``/diag``'s ``health`` block.
"""
from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestServer
from pydantic import TypeAdapter, ValidationError

from deckd import protocol as p
from deckd.platform import PlatformBackend

from conftest import DECKS_DIR, make_test_server

_server_adapter = TypeAdapter(p.ServerMessage)


def _issue(issue_id: str = "accessibility_missing") -> p.HealthIssue:
    return p.HealthIssue(
        id=issue_id,
        severity="error",
        title="Accessibility permission missing",
        detail="Pointer events are dropped.",
        fix_steps=["Open System Settings"],
        affects=["pointer"],
    )


# ---------------------------------------------------------------------------
# Backend -> issue mapping
# ---------------------------------------------------------------------------


def test_base_backend_reports_no_issues() -> None:
    assert PlatformBackend().health_issues() == []


def test_mac_backend_reports_missing_accessibility(monkeypatch) -> None:
    import deckd.platform_macos as mac

    monkeypatch.setattr(mac, "_ax_trusted", lambda: False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)  # the packaged app

    issues = mac.MacFocusBackend().health_issues()

    assert [i.id for i in issues] == ["accessibility_missing"]
    issue = issues[0]
    assert issue.severity == "error"
    # The fix names the exact app to grant and the Settings path.
    text = " ".join([issue.title, issue.detail, *issue.fix_steps])
    assert "deckd.app" in text
    assert "Privacy & Security" in text
    assert "Accessibility" in text
    # An already-listed entry can be a stale grant for an older (ad-hoc)
    # build. macOS 26 offers no reliable way to remove it in Settings, so
    # the packaged app's steps give the command that clears it.
    assert any(
        "tccutil reset Accessibility com.deckd.daemon" in step for step in issue.fix_steps
    )
    assert set(issue.affects) == {"pointer", "scroll", "key", "raise_window"}


def test_mac_backend_from_a_checkout_names_the_terminal(monkeypatch) -> None:
    """From a source checkout the grant belongs to the terminal, whose
    bundle id deckd doesn't know, so no tccutil command is offered."""
    import deckd.platform_macos as mac

    monkeypatch.setattr(mac, "_ax_trusted", lambda: False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(mac, "_terminal_name", lambda: "iTerm.app")

    (issue,) = mac.MacFocusBackend().health_issues()
    assert "iTerm.app" in " ".join(issue.fix_steps)
    assert not any("tccutil" in step for step in issue.fix_steps)


def test_input_monitoring_hint_names_the_bundle_when_frozen(monkeypatch, caplog) -> None:
    """The startup hints named /sbin/launchd (the app's parent) instead of
    deckd.app, found on real hardware during #194 / #195 verification."""
    import logging

    import deckd.platform_macos as mac

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(mac, "_terminal_name", lambda: "/sbin/launchd")
    with caplog.at_level(logging.INFO, logger="deckd.platform_macos"):
        mac._log_input_monitoring_hint("[mac scroll]")
    assert "deckd.app" in caplog.text
    assert "/sbin/launchd" not in caplog.text


@pytest.mark.parametrize("trusted", [True, None])
def test_mac_backend_quiet_when_trusted_or_unknown(monkeypatch, trusted) -> None:
    """``None`` is "can't tell" (no PyObjC): never cry wolf."""
    import deckd.platform_macos as mac

    monkeypatch.setattr(mac, "_ax_trusted", lambda: trusted)
    assert mac.MacFocusBackend().health_issues() == []


def test_mac_backend_rechecks_trust_on_every_call(monkeypatch) -> None:
    """The poller relies on each call re-reading trust, so a grant made
    while the daemon runs clears the issue without a restart."""
    import deckd.platform_macos as mac

    trusted = {"value": False}
    monkeypatch.setattr(mac, "_ax_trusted", lambda: trusted["value"])
    monkeypatch.setattr(mac, "_responsible_app_name", lambda: "deckd.app")
    backend = mac.MacFocusBackend()

    assert backend.health_issues()
    trusted["value"] = True
    assert backend.health_issues() == []


def test_responsible_app_is_the_bundle_when_frozen(monkeypatch) -> None:
    """Inside the packaged app the grant belongs to ``deckd.app``, not
    whatever launched it (launchd)."""
    import deckd.platform_macos as mac

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert mac._responsible_app_name() == "deckd.app"


def test_responsible_app_is_the_terminal_from_a_checkout(monkeypatch) -> None:
    import deckd.platform_macos as mac

    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(mac, "_terminal_name", lambda: "iTerm.app")
    assert mac._responsible_app_name() == "iTerm.app"


# ---------------------------------------------------------------------------
# Wire shape
# ---------------------------------------------------------------------------


def test_health_message_wire_shape() -> None:
    msg = p.HealthMessage(type="health", issues=[_issue()])
    assert json.loads(msg.model_dump_json()) == {
        "type": "health",
        "issues": [
            {
                "id": "accessibility_missing",
                "severity": "error",
                "title": "Accessibility permission missing",
                "detail": "Pointer events are dropped.",
                "fix_steps": ["Open System Settings"],
                "affects": ["pointer"],
            }
        ],
    }


def test_health_message_is_in_server_union() -> None:
    parsed = _server_adapter.validate_python({"type": "health", "issues": []})
    assert isinstance(parsed, p.HealthMessage)


def test_health_issue_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        p.HealthIssue.model_validate({**_issue().model_dump(), "extra": 1})


def test_health_issue_rejects_unknown_severity() -> None:
    with pytest.raises(ValidationError):
        p.HealthIssue.model_validate({**_issue().model_dump(), "severity": "meh"})


# ---------------------------------------------------------------------------
# Server: change-only pushes, connect replay, poller
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _boot(backend=None):
    server, _, _, _ = make_test_server(decks_dir=DECKS_DIR)
    server.focus_backend = backend
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    try:
        yield server, ts.port
    finally:
        await server.stop()
        await ts.close()


async def _recv(ws, timeout: float = 2.0) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))


async def _no_frame(ws, timeout: float = 0.25) -> bool:
    try:
        await asyncio.wait_for(ws.recv(), timeout=timeout)
    except TimeoutError:
        return True
    return False


async def test_change_only_broadcast() -> None:
    import websockets as _ws

    async with _boot() as (server, port):
        async with _ws.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            assert (await _recv(ws))["type"] == "deck"

            await server._on_health_issues([_issue()])
            frame = await _recv(ws)
            assert frame["type"] == "health"
            assert [i["id"] for i in frame["issues"]] == ["accessibility_missing"]

            # The same list again is not news.
            await server._on_health_issues([_issue()])
            assert await _no_frame(ws)

            # Clearing is: the empty list is what takes the banner down.
            await server._on_health_issues([])
            assert await _recv(ws) == {"type": "health", "issues": []}


async def test_connect_replays_active_issues() -> None:
    import websockets as _ws

    async with _boot() as (server, port):
        await server._on_health_issues([_issue()])
        async with _ws.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            frames = [await _recv(ws) for _ in range(2)]
    health = [f for f in frames if f["type"] == "health"]
    assert len(health) == 1
    assert health[0]["issues"][0]["id"] == "accessibility_missing"


async def test_connect_sends_no_health_frame_when_healthy() -> None:
    """No issues -> no frame: the client's empty default already says it,
    and every pre-#195 connect contract stays intact."""
    import websockets as _ws

    async with _boot() as (_server, port):
        async with _ws.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            assert (await _recv(ws))["type"] == "deck"
            assert await _no_frame(ws)


async def test_watcher_clears_issue_without_restart() -> None:
    """Grant the permission while the daemon runs -> the issue clears on
    the next poll, no reconnect needed."""
    import websockets as _ws

    state = {"issues": [_issue()]}
    backend = SimpleNamespace(
        capabilities=lambda: frozenset({"watch_active_app"}),
        health_issues=lambda: list(state["issues"]),
    )
    async with _boot(backend) as (server, port):
        task = server.start_health_watcher(interval_s=0.01)
        assert task is not None
        async with _ws.connect(f"ws://127.0.0.1:{port}/ws") as ws:
            frames = [await _recv(ws) for _ in range(2)]
            assert any(f["type"] == "health" and f["issues"] for f in frames)

            state["issues"] = []
            assert await _recv(ws) == {"type": "health", "issues": []}


async def test_watcher_survives_a_failing_probe() -> None:
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("probe blew up")
        return [_issue()]

    backend = SimpleNamespace(
        capabilities=lambda: frozenset({"watch_active_app"}),
        health_issues=flaky,
    )
    async with _boot(backend) as (server, _port):
        server.start_health_watcher(interval_s=0.01)
        for _ in range(100):
            if server._health_issues:
                break
            await asyncio.sleep(0.01)
    assert [i.id for i in server._health_issues] == ["accessibility_missing"]


async def test_watcher_noop_without_backend() -> None:
    async with _boot(None) as (server, _port):
        assert server.start_health_watcher() is None


# ---------------------------------------------------------------------------
# /diag
# ---------------------------------------------------------------------------


async def test_diag_lists_active_issues() -> None:
    import aiohttp

    async with _boot() as (server, port):
        await server._on_health_issues([_issue()])
        async with aiohttp.ClientSession() as http:
            async with http.get(f"http://127.0.0.1:{port}/diag") as resp:
                body = await resp.json()
    assert [i["id"] for i in body["health"]["issues"]] == ["accessibility_missing"]
    assert body["health"]["issues"][0]["fix_steps"] == ["Open System Settings"]
