"""Action-time permission errors: toast + diagnostics (issue #196).

When a key action fails because an OS permission is missing, the sink
raises :class:`PermissionDenied`. The server must:

* tell the *requesting* session (``action_error``) so the client toasts,
* count it as ``outcome="permission_denied"`` in the ring buffer and
  ``/metrics``,
* re-poll health right away so the banner doesn't wait for the next tick.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import websockets
from aiohttp.test_utils import TestServer
from pydantic import TypeAdapter, ValidationError

from deckd import protocol as p
from deckd.input import PermissionDenied

from conftest import make_test_server

_server_adapter = TypeAdapter(p.ServerMessage)

ISSUE = "accessibility_missing"
MESSAGE = "Key press blocked: deckd.app needs Accessibility permission."

DECK = """
match:
  - default
widgets:
  - id: new-window
    kind: button
    label: New window
    action:
      key: "super+n"
  - id: hello
    kind: button
    label: Type hello
    action:
      text: "hi"
  - id: two-keys
    kind: button
    label: Two keys
    macro:
      steps:
        - type: key
          value: "a"
        - type: key
          value: "b"
  - id: launch
    kind: button
    label: Launch
    action:
      shell: "true"
"""


# ---------------------------------------------------------------------------
# Wire shape
# ---------------------------------------------------------------------------


def test_action_error_wire_shape() -> None:
    msg = p.ActionErrorMessage(
        type="action_error",
        id="new-window",
        reason="permission_denied",
        issue_id=ISSUE,
        message=MESSAGE,
    )
    assert msg.model_dump() == {
        "type": "action_error",
        "id": "new-window",
        "reason": "permission_denied",
        "issue_id": ISSUE,
        "message": MESSAGE,
    }
    parsed = _server_adapter.validate_python(msg.model_dump())
    assert isinstance(parsed, p.ActionErrorMessage)


def test_action_error_id_is_optional() -> None:
    """Manual-control keys and typed text have no widget id."""
    msg = p.ActionErrorMessage(
        type="action_error", reason="permission_denied", issue_id=ISSUE, message=MESSAGE
    )
    assert msg.id is None


def test_action_error_rejects_unknown_reason() -> None:
    with pytest.raises(ValidationError):
        p.ActionErrorMessage.model_validate(
            {"type": "action_error", "reason": "nope", "issue_id": ISSUE, "message": "x"}
        )


# ---------------------------------------------------------------------------
# Server behaviour
# ---------------------------------------------------------------------------


class _DenyingSink:
    """Key sink whose keystrokes are all refused by the OS."""

    def __init__(self, on_deny=None) -> None:
        self.calls = 0
        self._on_deny = on_deny

    def emit_key(self, keycodes: list[int]) -> None:
        self.calls += 1
        if self._on_deny is not None:
            self._on_deny()
        raise PermissionDenied(ISSUE, MESSAGE)

    def emit_pointer(self, dx: int, dy: int) -> None:
        pass

    def emit_click(self, button: str, pressed: bool) -> None:
        pass

    def close(self) -> None:
        pass


async def _boot(monkeypatch, tmp_path: Path, sink, backend=None):
    import deckd.actions as actions_mod

    async def fake_shell(_cmd: str) -> None:
        pass

    monkeypatch.setattr(actions_mod, "_run_shell", fake_shell)
    (tmp_path / "default.yaml").write_text(DECK)
    server, _scroll, _key, _dbus = make_test_server(decks_dir=tmp_path)
    server.key_sink = sink
    server.focus_backend = backend
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    return ts, server


async def _read_until(ws, msg_type: str, timeout: float = 2.0) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=deadline - loop.time())
        msg = json.loads(raw)
        if msg.get("type") == msg_type:
            return msg


@pytest.mark.parametrize(
    ("frame", "widget_id", "primitive"),
    [
        ({"type": "press", "id": "new-window"}, "new-window", "key"),
        ({"type": "press", "id": "hello"}, "hello", "text"),
        ({"type": "press", "id": "two-keys"}, "two-keys", "macro"),
        ({"type": "key", "combo": "super+n"}, None, "key"),
        ({"type": "type", "text": "hi"}, None, "type"),
    ],
)
async def test_permission_denied_toasts_the_requesting_session(
    monkeypatch, tmp_path: Path, frame: dict, widget_id: str | None, primitive: str
) -> None:
    sink = _DenyingSink()
    ts, server = await _boot(monkeypatch, tmp_path, sink)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await _read_until(ws, "deck")
            await ws.send(json.dumps(frame))
            err = await _read_until(ws, "action_error", timeout=1.0)
        assert err == {
            "type": "action_error",
            "id": widget_id,
            "reason": "permission_denied",
            "issue_id": ISSUE,
            "message": MESSAGE,
        }
        # One refused keystroke is enough: the rest of a macro / text
        # would be refused the same way, so it stops at the first.
        assert sink.calls == 1
        snap = server.recent_actions.snapshot()
        denied = [r for r in snap if r.outcome == "permission_denied"]
        assert len(denied) == 1
        assert denied[0].primitive == primitive
        assert denied[0].error == MESSAGE
        assert server.metrics.action_outcome_total[f"{primitive}/permission_denied"] == 1
        assert 'outcome="permission_denied"' in server.metrics.render()
    finally:
        await ts.close()
        await server.scroll.close()


async def test_permission_denied_is_not_broadcast(monkeypatch, tmp_path: Path) -> None:
    sink = _DenyingSink()
    ts, server = await _boot(monkeypatch, tmp_path, sink)
    try:
        async with (
            websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as presser,
            websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as bystander,
        ):
            await _read_until(presser, "deck")
            await _read_until(bystander, "deck")
            await presser.send(json.dumps({"type": "press", "id": "new-window"}))
            await _read_until(presser, "action_error", timeout=1.0)
            with pytest.raises(TimeoutError):
                await _read_until(bystander, "action_error", timeout=0.25)
    finally:
        await ts.close()
        await server.scroll.close()


async def test_permission_denied_refreshes_health_immediately(
    monkeypatch, tmp_path: Path
) -> None:
    """The banner comes up with the toast, not on the next poll tick."""
    state: dict[str, list[p.HealthIssue]] = {"issues": []}
    issue = p.HealthIssue(
        id=ISSUE,
        severity="error",
        title="Accessibility permission missing",
        detail="",
        fix_steps=[],
        affects=["key"],
    )

    def deny() -> None:
        state["issues"] = [issue]  # what the ledger now reports

    backend = SimpleNamespace(
        capabilities=lambda: frozenset({"watch_active_app"}),
        health_issues=lambda: list(state["issues"]),
    )
    ts, server = await _boot(monkeypatch, tmp_path, _DenyingSink(on_deny=deny), backend)
    try:
        # No watcher running: only the refresh can deliver the frame.
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await _read_until(ws, "deck")
            await ws.send(json.dumps({"type": "press", "id": "new-window"}))
            health = await _read_until(ws, "health", timeout=1.0)
        assert [i["id"] for i in health["issues"]] == [ISSUE]
    finally:
        await ts.close()
        await server.scroll.close()


async def test_other_primitives_still_run(monkeypatch, tmp_path: Path) -> None:
    """A missing keystroke grant doesn't touch shell buttons."""
    sink = _DenyingSink()
    ts, server = await _boot(monkeypatch, tmp_path, sink)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await _read_until(ws, "deck")
            await ws.send(json.dumps({"type": "press", "id": "launch"}))
            with pytest.raises(TimeoutError):
                await _read_until(ws, "action_error", timeout=0.25)
        assert not any(
            r.outcome == "permission_denied" for r in server.recent_actions.snapshot()
        )
    finally:
        await ts.close()
        await server.scroll.close()
