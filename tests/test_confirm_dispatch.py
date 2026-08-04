"""Tests for the daemon's confirmation handshake (issues #69 / #107).

Seams under test:

- ``Server._dispatch_press`` withholds execution on a ``confirm: true``
  press, mints a ``confirm_id``, sends ``ConfirmRequestMessage`` to the
  client, and emits no action ring/event at press time.
- ``Server._dispatch`` on ``confirm_response`` with ``decision="confirm"``
  re-enters the normal ``run_action`` path (records the action ring
  record and emits the ``action`` event).
- ``confirm_response`` with ``decision="cancel"`` drops the pending
  action and records a ``cancelled`` ring record; no ``action`` event.
- Unknown / expired ``confirm_id`` is a no-op (never executes).
- A second press on a pending widget supersedes the first token.
- Disconnect mid-confirm drops pending state (action never runs).
- ~30s timeout expires the pending action without execution.
- Diagnostic events fire with the right ``outcome`` lifecycle and
  carry ``confirm_id`` correlation.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import websockets
from aiohttp.test_utils import TestServer

from conftest import (
    FakeDbusBusFactory,
    FakeFocusBackend,
    FakePointerSink,
    FakeScrollSink,
    ServerHandle,
    make_test_server,
)


CONFIRM_TIMEOUT_S = 0.5  # shorten the test backstop


CONFIRM_LAYOUT = """
match:
  - default
widgets:
  - id: rm-all
    kind: button
    label: Remove all
    confirm: true
    action:
      shell: "rm -rf /"
  - id: multi-shot
    kind: button
    label: Multi step
    confirm: true
    macro:
      steps:
        - type: key
          value: "a"
"""


async def _boot(monkeypatch, tmp_path: Path, *, layouts_yaml: str = CONFIRM_LAYOUT):
    """Boot a server with a confirm-enabled layout and a fake shell."""
    import deckd.actions as actions_mod

    called: list[tuple[str, str]] = []

    async def fake_shell(cmd: str) -> None:
        called.append(("shell", cmd))

    async def fake_terminal(target: bool | str = True) -> None:
        called.append(("terminal", str(target)))

    monkeypatch.setattr(actions_mod, "_run_shell", fake_shell)
    monkeypatch.setattr(actions_mod, "run_terminal", fake_terminal)
    # Shorten the confirm timeout so tests don't sleep 30s.
    monkeypatch.setattr("deckd.server.CONFIRM_TIMEOUT_S", CONFIRM_TIMEOUT_S)

    (tmp_path / "default.yaml").write_text(layouts_yaml)
    server, _scroll, _key, _dbus = make_test_server(layouts_dir=tmp_path)
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    return ts, server, called


async def _read_until(ws, predicate, *, timeout: float = 2.0):
    """Read frames until ``predicate(msg)`` returns truthy or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=deadline - asyncio.get_event_loop().time())
        msg = json.loads(raw)
        if predicate(msg):
            return msg
    raise AssertionError("timeout waiting for predicate")


async def _enable_events(ws) -> None:
    await ws.send(json.dumps({"type": "enable_events"}))
    await asyncio.sleep(0.05)


def _confirm_request_for(msg: dict, widget_id: str) -> dict | None:
    if msg.get("type") == "confirm_request" and msg.get("widget_id") == widget_id:
        return msg
    return None


# ---------------------------------------------------------------------------
# Schema round-trip
# ---------------------------------------------------------------------------


async def test_layout_push_carries_confirm_flag(monkeypatch, tmp_path: Path) -> None:
    ts, _server, _called = await _boot(monkeypatch, tmp_path)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            layout = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            widgets = {w["id"]: w for w in layout["widgets"]}
            assert widgets["rm-all"]["confirm"] is True
            assert widgets["multi-shot"]["confirm"] is True
    finally:
        await ts.close()
        await _server.scroll.close()


# ---------------------------------------------------------------------------
# Withholding at press time
# ---------------------------------------------------------------------------


async def test_confirm_press_withholds_and_sends_request(monkeypatch, tmp_path: Path) -> None:
    """A ``confirm: true`` press never runs the action; it sends a confirm_request."""
    ts, server, called = await _boot(monkeypatch, tmp_path)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)  # initial layout
            await ws.send(json.dumps({"type": "press", "id": "rm-all"}))
            req = await _read_until(ws, lambda m: bool(_confirm_request_for(m, "rm-all")))
            assert req["type"] == "confirm_request"
            assert req["widget_id"] == "rm-all"
            assert req["confirm_id"]
            await asyncio.sleep(0.1)
            assert called == []  # action never ran
    finally:
        await ts.close()
        await server.scroll.close()


async def test_confirm_press_emits_requested_event_no_action_event(
    monkeypatch, tmp_path: Path
) -> None:
    ts, server, _called = await _boot(monkeypatch, tmp_path)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
            await _enable_events(ws)
            await ws.send(json.dumps({"type": "press", "id": "rm-all"}))
            # Find a confirm/requested event (might not be the first frame).
            deadline = asyncio.get_event_loop().time() + 1.0
            saw_requested = False
            saw_action = False
            while asyncio.get_event_loop().time() < deadline and not saw_requested:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                msg = json.loads(raw)
                if msg.get("type") == "event" and msg.get("name") == "confirm":
                    if msg["data"].get("outcome") == "requested":
                        saw_requested = True
                        assert msg["data"]["widget_id"] == "rm-all"
                        assert msg["data"]["confirm_id"]
                if msg.get("type") == "event" and msg.get("name") == "action":
                    saw_action = True
            assert saw_requested, "expected confirm/requested event"
            assert not saw_action, "action event must NOT fire for a withheld press"
    finally:
        await ts.close()
        await server.scroll.close()


# ---------------------------------------------------------------------------
# Confirm / cancel response
# ---------------------------------------------------------------------------


async def test_confirm_response_confirm_runs_action_and_emits_action_event(
    monkeypatch, tmp_path: Path
) -> None:
    ts, server, called = await _boot(monkeypatch, tmp_path)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
            await _enable_events(ws)
            await ws.send(json.dumps({"type": "press", "id": "rm-all"}))
            req = await _read_until(ws, lambda m: bool(_confirm_request_for(m, "rm-all")))
            confirm_id = req["confirm_id"]

            await ws.send(json.dumps(
                {"type": "confirm_response", "confirm_id": confirm_id, "decision": "confirm"}
            ))
            # Drain until we see the action event.
            deadline = asyncio.get_event_loop().time() + 1.0
            saw_action = False
            saw_confirmed = False
            while asyncio.get_event_loop().time() < deadline and not (saw_action and saw_confirmed):
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                msg = json.loads(raw)
                if msg.get("type") == "event" and msg.get("name") == "action":
                    saw_action = True
                    assert msg["data"]["widget_id"] == "rm-all"
                    assert msg["data"].get("confirm_id") == confirm_id
                if msg.get("type") == "event" and msg.get("name") == "confirm":
                    if msg["data"].get("outcome") == "confirmed":
                        saw_confirmed = True
                        assert msg["data"]["confirm_id"] == confirm_id
            assert saw_action
            assert saw_confirmed
            await asyncio.sleep(0.05)
            assert any(kind == "shell" and "rm" in val for kind, val in called)
    finally:
        await ts.close()
        await server.scroll.close()


async def _read_events_until(
    ws,
    predicate,
    *,
    timeout: float = 2.0,
):
    """Read frames until ``predicate(msg)`` returns truthy or timeout.

    Silently skips ``TimeoutError`` from the per-receive wait — the
    outer deadline drives the loop and we don't want to crash on a
    transient empty window. Awaits the predicate when it's a
    coroutine so an async predicate can collect state across frames
    before deciding to bail out (used for the cancel test to
    accumulate frames without stopping on the first non-match).
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.3)
        except asyncio.TimeoutError:
            continue
        msg = json.loads(raw)
        result = predicate(msg)
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return msg
    raise AssertionError("timeout waiting for predicate")


async def test_confirm_response_cancel_does_not_run_action_records_cancelled(
    monkeypatch, tmp_path: Path
) -> None:
    ts, server, called = await _boot(monkeypatch, tmp_path)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
            await _enable_events(ws)
            await ws.send(json.dumps({"type": "press", "id": "rm-all"}))
            req = await _read_until(ws, lambda m: bool(_confirm_request_for(m, "rm-all")))
            confirm_id = req["confirm_id"]

            await ws.send(json.dumps(
                {"type": "confirm_response", "confirm_id": confirm_id, "decision": "cancel"}
            ))
            seen: list[dict] = []
            async def _collect_cancel(m: dict) -> bool:
                if m.get("type") == "event" and m.get("name") == "confirm":
                    if m["data"].get("outcome") == "cancelled":
                        seen.append(m)
                        return True
                if m.get("type") == "event" and m.get("name") == "action":
                    seen.append(m)
                return False

            await _read_events_until(ws, _collect_cancel, timeout=1.0)
            # No ``action`` event should ever have fired.
            assert not any(
                m.get("type") == "event" and m.get("name") == "action"
                for m in seen
            ), "cancelled press must NOT emit an action event"
            await asyncio.sleep(0.05)
            assert called == []
            # The recent-actions ring carries a cancelled record for the widget.
            snap = server.recent_actions.snapshot()
            assert any(
                r.widget_id == "rm-all" and r.outcome == "cancelled" for r in snap
            ), f"expected cancelled ring record, got: {snap}"
    finally:
        await ts.close()
        await server.scroll.close()


# ---------------------------------------------------------------------------
# Token failure modes
# ---------------------------------------------------------------------------


async def test_confirm_response_unknown_id_is_noop(monkeypatch, tmp_path: Path) -> None:
    ts, server, called = await _boot(monkeypatch, tmp_path)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
            await ws.send(json.dumps(
                {"type": "confirm_response", "confirm_id": "nope", "decision": "confirm"}
            ))
            await asyncio.sleep(0.1)
            assert called == []
    finally:
        await ts.close()
        await server.scroll.close()


async def test_confirm_response_after_timeout_is_noop(monkeypatch, tmp_path: Path) -> None:
    ts, server, called = await _boot(monkeypatch, tmp_path)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
            await ws.send(json.dumps({"type": "press", "id": "rm-all"}))
            req = await _read_until(ws, lambda m: bool(_confirm_request_for(m, "rm-all")))
            confirm_id = req["confirm_id"]
            # Wait for the timeout to expire.
            await asyncio.sleep(CONFIRM_TIMEOUT_S + 0.2)
            # Late confirm is a no-op.
            await ws.send(json.dumps(
                {"type": "confirm_response", "confirm_id": confirm_id, "decision": "confirm"}
            ))
            await asyncio.sleep(0.1)
            assert called == []
    finally:
        await ts.close()
        await server.scroll.close()


async def test_confirm_timeout_records_expired(monkeypatch, tmp_path: Path) -> None:
    ts, server, _called = await _boot(monkeypatch, tmp_path)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
            await _enable_events(ws)
            await ws.send(json.dumps({"type": "press", "id": "rm-all"}))
            await _read_until(ws, lambda m: bool(_confirm_request_for(m, "rm-all")))

            async def _saw_expired(m: dict) -> bool:
                return (
                    m.get("type") == "event"
                    and m.get("name") == "confirm"
                    and m["data"].get("outcome") == "expired"
                )

            await _read_events_until(ws, _saw_expired, timeout=CONFIRM_TIMEOUT_S + 1.0)
            snap = server.recent_actions.snapshot()
            assert any(
                r.widget_id == "rm-all" and r.outcome == "expired" for r in snap
            ), f"expected expired ring record, got: {snap}"
    finally:
        await ts.close()
        await server.scroll.close()


# ---------------------------------------------------------------------------
# Supersession on re-press
# ---------------------------------------------------------------------------


async def test_re_press_supersedes_pending_token(monkeypatch, tmp_path: Path) -> None:
    """A second press on the same widget cancels the previous pending token
    and replaces it with a fresh one. A late response to the old token is a
    no-op; the new token is the live one."""
    ts, server, called = await _boot(monkeypatch, tmp_path)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
            await ws.send(json.dumps({"type": "press", "id": "rm-all"}))
            req1 = await _read_until(ws, lambda m: bool(_confirm_request_for(m, "rm-all")))
            old_id = req1["confirm_id"]
            await ws.send(json.dumps({"type": "press", "id": "rm-all"}))
            req2 = await _read_until(
                ws,
                lambda m: bool(
                    _confirm_request_for(m, "rm-all") and m["confirm_id"] != old_id
                ),
            )
            new_id = req2["confirm_id"]
            # Late confirm on the old id is a no-op.
            await ws.send(json.dumps(
                {"type": "confirm_response", "confirm_id": old_id, "decision": "confirm"}
            ))
            await asyncio.sleep(0.05)
            assert called == []
            # Confirm the new id runs the action.
            await ws.send(json.dumps(
                {"type": "confirm_response", "confirm_id": new_id, "decision": "confirm"}
            ))
            await asyncio.sleep(0.1)
            assert any(kind == "shell" and "rm" in val for kind, val in called)
    finally:
        await ts.close()
        await server.scroll.close()


# ---------------------------------------------------------------------------
# Disconnect discards pending state
# ---------------------------------------------------------------------------


async def test_disconnect_discards_pending_confirm(monkeypatch, tmp_path: Path) -> None:
    """If the client drops mid-confirm, the pending action is dropped."""
    ts, server, called = await _boot(monkeypatch, tmp_path)
    try:
        ws = await websockets.connect(f"ws://127.0.0.1:{ts.port}/ws")
        await asyncio.wait_for(ws.recv(), timeout=2)
        await ws.send(json.dumps({"type": "press", "id": "rm-all"}))
        # Read until we see a confirm_request.
        deadline = asyncio.get_event_loop().time() + 1.0
        while asyncio.get_event_loop().time() < deadline:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            msg = json.loads(raw)
            if msg.get("type") == "confirm_request":
                break
        await ws.close()
        # Give the daemon a beat to settle the close.
        await asyncio.sleep(0.1)
        # Wait past the timeout window to ensure no late execution.
        await asyncio.sleep(CONFIRM_TIMEOUT_S + 0.2)
        assert called == []
    finally:
        await ts.close()
        await server.scroll.close()


# ---------------------------------------------------------------------------
# Macros under confirm
# ---------------------------------------------------------------------------


async def test_confirmed_macro_runs_full_sequence(monkeypatch, tmp_path: Path) -> None:
    """A confirmed press on a macro widget runs the entire sequence —
    one confirmation gates the whole macro."""
    ts, server, _called = await _boot(monkeypatch, tmp_path)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
            await ws.send(json.dumps({"type": "press", "id": "multi-shot"}))
            req = await _read_until(ws, lambda m: bool(_confirm_request_for(m, "multi-shot")))
            await ws.send(json.dumps(
                {"type": "confirm_response", "confirm_id": req["confirm_id"], "decision": "confirm"}
            ))
            # Macro runs, and a macro_result message lands.
            deadline = asyncio.get_event_loop().time() + 1.0
            saw_result = False
            while asyncio.get_event_loop().time() < deadline and not saw_result:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                msg = json.loads(raw)
                if msg.get("type") == "macro_result" and msg.get("id") == "multi-shot":
                    saw_result = True
                    assert msg["outcome"] == "ok"
            assert saw_result, "expected macro_result after confirmed macro"
    finally:
        await ts.close()
        await server.scroll.close()


# ---------------------------------------------------------------------------
# Plain (non-confirm) button still works
# ---------------------------------------------------------------------------


async def test_non_confirm_button_unaffected(monkeypatch, tmp_path: Path) -> None:
    """Regression: a press on a non-confirm widget runs immediately, no
    handshake, no extra confirm frames."""
    import deckd.actions as actions_mod

    called: list[tuple[str, str]] = []

    async def fake_shell(cmd: str) -> None:
        called.append(("shell", cmd))

    monkeypatch.setattr(actions_mod, "_run_shell", fake_shell)
    monkeypatch.setattr(actions_mod, "run_terminal", lambda t: None)
    monkeypatch.setattr("deckd.server.CONFIRM_TIMEOUT_S", CONFIRM_TIMEOUT_S)

    (tmp_path / "default.yaml").write_text("""
match:
  - default
widgets:
  - id: safe
    kind: button
    label: Safe
    action:
      shell: "echo hi"
""")
    server, _scroll, _key, _dbus = make_test_server(layouts_dir=tmp_path)
    ts = TestServer(server.app, host="127.0.0.1")
    await ts.start_server()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{ts.port}/ws") as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
            await ws.send(json.dumps({"type": "press", "id": "safe"}))
            await asyncio.sleep(0.1)
        assert any(kind == "shell" and "echo" in val for kind, val in called)
    finally:
        await ts.close()
        await server.scroll.close()
