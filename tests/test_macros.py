"""Tests for macro execution: sequential steps, delays, error handling,
and the ``continue_on_error`` flag (issue #68)."""
from __future__ import annotations

import asyncio
import json
from typing import cast

import pytest

from conftest import FakeDbusBusFactory, requires_dbus

from deckd.actions import (
    ActionContext,
    MacroOutcome,
    execute as run_action,
    execute_macro,
)
from deckd.layouts import Action, Macro, MacroStep, Widget


def _ctx(factory: FakeDbusBusFactory | None = None) -> ActionContext:
    return ActionContext(
        send_layout=lambda: asyncio.sleep(0),
        get_current_layout=lambda: cast("Layout", None),
        current_app="default",
        key_sink=None,
        dbus_bus_factory=cast("Any", factory) if factory else None,
    )


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_macro_step_requires_non_empty_value() -> None:
    with pytest.raises(Exception):
        MacroStep(type="key", value="")


def test_macro_requires_at_least_one_step() -> None:
    with pytest.raises(Exception):
        Macro(steps=[])


def test_widget_with_macro_loads() -> None:
    widget = Widget(
        id="btn",
        kind="button",
        macro=Macro(steps=[MacroStep(type="key", value="a")]),
    )
    assert widget.macro is not None
    assert len(widget.macro.steps) == 1


def test_widget_with_action_and_macro_coexist() -> None:
    """Widget can have both action and macro; macro takes precedence at runtime."""
    widget = Widget(
        id="btn",
        kind="button",
        action=Action(shell="echo hi"),
        macro=Macro(steps=[MacroStep(type="key", value="a")]),
    )
    assert widget.action is not None
    assert widget.macro is not None


# ---------------------------------------------------------------------------
# Macro execution — key step
# ---------------------------------------------------------------------------


async def test_macro_executes_key_steps() -> None:
    macro = Macro(steps=[MacroStep(type="key", value="a")])
    outcome = await execute_macro(macro, _ctx())
    assert outcome.outcome == "ok"
    assert outcome.failed_step is None
    assert outcome.error is None


# ---------------------------------------------------------------------------
# Macro execution — delay step
# ---------------------------------------------------------------------------


async def test_macro_delay_step_waits() -> None:
    macro = Macro(steps=[
        MacroStep(type="delay", value="100"),
        MacroStep(type="delay", value="200"),
    ])
    t0 = asyncio.get_event_loop().time()
    outcome = await execute_macro(macro, _ctx())
    elapsed = (asyncio.get_event_loop().time() - t0) * 1000
    assert outcome.outcome == "ok"
    assert elapsed >= 290  # 100 + 200 = 300ms, with small measurement tolerance


async def test_macro_delay_invalid_value_fails() -> None:
    macro = Macro(steps=[MacroStep(type="delay", value="not-a-number")])
    outcome = await execute_macro(macro, _ctx())
    assert outcome.outcome == "failed-at-step"
    assert outcome.failed_step == 0
    assert "invalid delay" in (outcome.error or "")


async def test_macro_delay_negative_fails() -> None:
    macro = Macro(steps=[MacroStep(type="delay", value="-1")])
    outcome = await execute_macro(macro, _ctx())
    assert outcome.outcome == "failed-at-step"


# ---------------------------------------------------------------------------
# Macro execution — shell step
# ---------------------------------------------------------------------------


async def test_macro_executes_shell_step() -> None:
    macro = Macro(steps=[MacroStep(type="shell", value="true")])
    outcome = await execute_macro(macro, _ctx())
    assert outcome.outcome == "ok"


# ---------------------------------------------------------------------------
# Macro execution — dbus step
# ---------------------------------------------------------------------------


@requires_dbus
async def test_macro_executes_dbus_step() -> None:
    factory = FakeDbusBusFactory()
    macro = Macro(steps=[
        MacroStep(
            type="dbus",
            value=(
                "org.mpris.MediaPlayer2.vlc:/org/mpris/MediaPlayer2 "
                "org.mpris.MediaPlayer2.Player.PlayPause"
            ),
        )
    ])
    outcome = await execute_macro(macro, _ctx(factory))
    assert outcome.outcome == "ok"
    assert len(factory.buses) == 1


async def test_macro_dbus_step_without_factory_fails() -> None:
    macro = Macro(steps=[
        MacroStep(type="dbus", value="org.example.Interface.Method")
    ])
    outcome = await execute_macro(macro, _ctx(factory=None))
    assert outcome.outcome == "failed-at-step"
    assert outcome.failed_step == 0
    assert outcome.error is not None
    assert "bus factory" in (outcome.error or "")


# ---------------------------------------------------------------------------
# Sequential execution — multi-step
# ---------------------------------------------------------------------------


async def test_macro_executes_multiple_steps_in_order(monkeypatch) -> None:
    import deckd.actions as actions_mod

    order: list[str] = []

    async def trail_shell(step, _ctx):
        order.append(f"shell:{step.value}")

    async def trail_key(step, _ctx):
        order.append(f"key:{step.value}")

    async def trail_delay(step, _ctx):
        order.append(f"delay:{step.value}")

    monkeypatch.setitem(actions_mod._STEP_DISPATCH, "shell", trail_shell)
    monkeypatch.setitem(actions_mod._STEP_DISPATCH, "key", trail_key)
    monkeypatch.setitem(actions_mod._STEP_DISPATCH, "delay", trail_delay)

    macro = Macro(steps=[
        MacroStep(type="shell", value="step1"),
        MacroStep(type="delay", value="50"),
        MacroStep(type="key", value="step3"),
    ])
    outcome = await execute_macro(macro, _ctx())
    assert outcome.outcome == "ok"
    assert order == ["shell:step1", "delay:50", "key:step3"]


# ---------------------------------------------------------------------------
# Error handling — continue_on_error
# ---------------------------------------------------------------------------


async def test_macro_stops_on_first_failure_by_default(monkeypatch) -> None:
    import deckd.actions as actions_mod

    order: list[str] = []

    async def failing_step(step, _ctx):
        order.append(step.value)
        raise RuntimeError("boom")

    monkeypatch.setitem(actions_mod._STEP_DISPATCH, "shell", failing_step)
    monkeypatch.setitem(actions_mod._STEP_DISPATCH, "key",
                        lambda step, _ctx: order.append(f"key:{step.value}"))

    macro = Macro(steps=[
        MacroStep(type="shell", value="will-fail"),
        MacroStep(type="shell", value="should-not-run"),
        MacroStep(type="key", value="should-not-run"),
    ])
    outcome = await execute_macro(macro, _ctx())
    assert outcome.outcome == "failed-at-step"
    assert outcome.failed_step == 0
    assert "boom" in (outcome.error or "")
    assert order == ["will-fail"]


async def test_macro_continue_on_error_true_runs_remaining(monkeypatch) -> None:
    import deckd.actions as actions_mod

    order: list[str] = []

    async def step_maybe_fail(step, _ctx):
        order.append(step.value)
        if step.value == "will-fail":
            raise RuntimeError("boom")

    monkeypatch.setitem(actions_mod._STEP_DISPATCH, "key", step_maybe_fail)

    macro = Macro(
        steps=[
            MacroStep(type="key", value="will-fail"),
            MacroStep(type="key", value="should-run"),
            MacroStep(type="key", value="should-also-run"),
        ],
        continue_on_error=True,
    )
    outcome = await execute_macro(macro, _ctx())
    assert outcome.outcome == "ok"
    assert order == ["will-fail", "should-run", "should-also-run"]


async def test_macro_continue_on_error_stops_on_last_step() -> None:
    macro = Macro(
        steps=[MacroStep(type="delay", value="not-a-number")],
        continue_on_error=True,
    )
    outcome = await execute_macro(macro, _ctx())
    assert outcome.outcome == "ok"


# ---------------------------------------------------------------------------
# execute() dispatches to macro when present
# ---------------------------------------------------------------------------


async def test_execute_dispatches_to_macro_over_single_action(monkeypatch) -> None:
    import deckd.actions as actions_mod

    called: list[str] = []

    async def trail_key(step, _ctx):
        called.append(f"macro_key:{step.value}")

    monkeypatch.setitem(actions_mod._STEP_DISPATCH, "key", trail_key)

    widget = Widget(
        id="btn",
        kind="button",
        action=Action(shell="should-not-run"),
        macro=Macro(steps=[MacroStep(type="key", value="ctrl+t")]),
    )
    outcome = await run_action(widget, _ctx())
    assert isinstance(outcome, MacroOutcome)
    assert outcome.outcome == "ok"
    assert called == ["macro_key:ctrl+t"]


async def test_execute_falls_back_to_action_when_no_macro() -> None:
    widget = Widget(
        id="btn",
        kind="button",
        action=Action(shell="true"),
    )
    outcome = await run_action(widget, _ctx())
    assert outcome is None


# ---------------------------------------------------------------------------
# MacroResultMessage round-trips
# ---------------------------------------------------------------------------


def test_macro_result_message_roundtrips() -> None:
    from deckd.protocol import MacroResultMessage

    msg = MacroResultMessage(
        type="macro_result",
        id="btn",
        outcome="ok",
    )
    data = msg.model_dump()
    assert data["type"] == "macro_result"
    assert data["id"] == "btn"
    assert data["outcome"] == "ok"
    assert data["failed_step"] is None
    assert data["error"] is None
    # Round-trip
    parsed = MacroResultMessage.model_validate(data)
    assert parsed.id == "btn"
    assert parsed.outcome == "ok"


def test_macro_result_message_failure_roundtrips() -> None:
    from deckd.protocol import MacroResultMessage

    msg = MacroResultMessage(
        type="macro_result",
        id="btn",
        outcome="failed-at-step",
        failed_step=2,
        error="ValueError: boom",
    )
    data = msg.model_dump()
    parsed = MacroResultMessage.model_validate(data)
    assert parsed.outcome == "failed-at-step"
    assert parsed.failed_step == 2
    assert parsed.error == "ValueError: boom"


def test_macro_result_message_rejects_extra_fields() -> None:
    from deckd.protocol import MacroResultMessage

    with pytest.raises(Exception):
        MacroResultMessage.model_validate(
            {"type": "macro_result", "id": "btn", "outcome": "ok", "bonus": 42}
        )


# ---------------------------------------------------------------------------
# Server integration: macro result is sent to client
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_macro_press_sends_result_to_client(tmp_path) -> None:
    """Press a macro widget and confirm the client receives a MacroResultMessage."""
    import deckd.actions as actions_mod

    order: list[str] = []

    async def trail_step(step, _ctx):
        order.append(step.value)

    actions_mod._STEP_DISPATCH["key"] = trail_step

    layouts_dir = tmp_path / "layouts"
    layouts_dir.mkdir()
    (layouts_dir / "default.yaml").write_text("""
match:
  - default
widgets:
  - id: macro-btn
    kind: button
    label: Macro
    macro:
      steps:
        - type: key
          value: a
        - type: key
          value: b
""")

    from conftest import make_test_server

    server, _scroll, _key, _dbus = make_test_server(layouts_dir=layouts_dir)

    from aiohttp.test_utils import TestServer as _TestServer
    test_srv = _TestServer(server.app, host="127.0.0.1")
    await test_srv.start_server()
    try:
        import websockets
        ws_url = f"ws://127.0.0.1:{test_srv.port}/ws"

        async with websockets.connect(ws_url) as ws:
            _ = await asyncio.wait_for(ws.recv(), timeout=2)
            await ws.send(json.dumps({"type": "press", "id": "macro-btn"}))

            messages = []
            try:
                while len(messages) < 3:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    messages.append(json.loads(raw))
            except asyncio.TimeoutError:
                pass

            results = [m for m in messages if m.get("type") == "macro_result"]
            assert len(results) >= 1, f"Expected at least one macro_result, got messages: {messages}"
            result = results[0]
            assert result["id"] == "macro-btn"
            assert result["outcome"] == "ok"
    finally:
        await test_srv.close()
        await server.scroll.close()


@pytest.mark.asyncio
async def test_macro_failure_sends_result_with_error(tmp_path) -> None:
    """A failing macro step sends a failed-at-step result to the client."""
    import deckd.actions as actions_mod

    async def failing_step(step, _ctx):
        raise ValueError("simulated failure")

    actions_mod._STEP_DISPATCH["key"] = failing_step

    layouts_dir = tmp_path / "layouts"
    layouts_dir.mkdir()
    (layouts_dir / "default.yaml").write_text("""
match:
  - default
widgets:
  - id: fail-btn
    kind: button
    label: Fail
    macro:
      steps:
        - type: key
          value: a
""")

    from conftest import make_test_server

    server, _scroll, _key, _dbus = make_test_server(layouts_dir=layouts_dir)

    from aiohttp.test_utils import TestServer as _TestServer
    test_srv = _TestServer(server.app, host="127.0.0.1")
    await test_srv.start_server()
    try:
        import websockets
        ws_url = f"ws://127.0.0.1:{test_srv.port}/ws"

        async with websockets.connect(ws_url) as ws:
            _ = await asyncio.wait_for(ws.recv(), timeout=2)
            await ws.send(json.dumps({"type": "press", "id": "fail-btn"}))

            messages = []
            try:
                while len(messages) < 3:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    messages.append(json.loads(raw))
            except asyncio.TimeoutError:
                pass

            results = [m for m in messages if m.get("type") == "macro_result"]
            assert len(results) >= 1, f"Expected macro_result in: {messages}"
            result = results[0]
            assert result["outcome"] == "failed-at-step"
            assert result["failed_step"] == 0
            assert "simulated failure" in (result.get("error") or "")
    finally:
        await test_srv.close()
        await server.scroll.close()
