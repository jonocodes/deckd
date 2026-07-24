"""Tests for dbus action parsing and dispatch.

Seam under test: pressing a button with a `dbus:` action causes a D-Bus method
call to be made with the correct destination, path, interface, method, and
arguments. Errors raised by the bus are caught and logged, never propagated
back to the client.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import pytest

from conftest import FakeDbusBusFactory

from deckd.actions import ActionContext, execute as run_action
from deckd.layouts import Action, Widget


def _ctx(factory: FakeDbusBusFactory) -> ActionContext:
    return ActionContext(
        send_layout=lambda: asyncio.sleep(0),
        get_current_layout=lambda: None,
        current_app="default",
        key_sink=None,
        dbus_bus_factory=cast(Any, factory),
    )


def _widget(dbus_value: str) -> Widget:
    return Widget(
        id="dbus-btn",
        kind="button",
        label="dbus",
        grid=[0, 0, 1, 1],
        action=Action(dbus=dbus_value),
    )


# ---------------------------------------------------------------------------
# Dispatch — correct call shape
# ---------------------------------------------------------------------------


async def test_press_dbus_calls_method_on_session_bus() -> None:
    factory = FakeDbusBusFactory()
    widget = _widget(
        "org.mpris.MediaPlayer2.vlc:/org/mpris/MediaPlayer2 "
        "org.mpris.MediaPlayer2.Player.PlayPause"
    )

    await run_action(widget, _ctx(factory))

    from dbus_fast import BusType

    assert len(factory.buses) == 1
    bus = factory.buses[0]
    assert bus.bus_type is BusType.SESSION
    assert factory.calls == [
        {
            "bus_type": BusType.SESSION,
            "destination": "org.mpris.MediaPlayer2.vlc",
            "path": "/org/mpris/MediaPlayer2",
            "interface": "org.mpris.MediaPlayer2.Player",
            "method": "PlayPause",
            "args": [],
        }
    ]


async def test_press_dbus_passes_string_arguments() -> None:
    factory = FakeDbusBusFactory()
    widget = _widget(
        "org.example.Service:/org/example "
        "org.example.I.Foo hello world"
    )

    await run_action(widget, _ctx(factory))

    call = factory.calls[0]
    assert call["method"] == "Foo"
    assert call["args"] == ["hello", "world"]


async def test_press_dbus_uses_system_bus_for_systemd_interfaces() -> None:
    factory = FakeDbusBusFactory()
    widget = _widget(
        "org.freedesktop.login1:/org/freedesktop/login1 "
        "org.freedesktop.login1.Manager.Suspend false"
    )

    await run_action(widget, _ctx(factory))

    from dbus_fast import BusType

    bus = factory.buses[0]
    assert bus.bus_type is BusType.SYSTEM
    call = factory.calls[0]
    assert call["interface"] == "org.freedesktop.login1.Manager"
    assert call["method"] == "Suspend"
    assert call["args"] == ["false"]


# ---------------------------------------------------------------------------
# Resource lifecycle
# ---------------------------------------------------------------------------


async def test_press_dbus_disconnects_bus_after_call() -> None:
    factory = FakeDbusBusFactory()
    widget = _widget(
        "org.example.Service:/org/example org.example.I.Foo"
    )

    await run_action(widget, _ctx(factory))

    bus = factory.buses[0]
    assert bus.connected is True
    assert bus.disconnected is True


# ---------------------------------------------------------------------------
# Error handling — never propagated to the client
# ---------------------------------------------------------------------------


async def test_press_dbus_swallows_errors_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    boom = RuntimeError("connection refused")
    factory = FakeDbusBusFactory(error=boom)
    widget = _widget(
        "org.example.Service:/org/example org.example.I.Foo"
    )

    with caplog.at_level(logging.WARNING, logger="deckd.actions"):
        # Must not raise — the dispatcher must catch and log.
        await run_action(widget, _ctx(factory))

    assert any("dbus" in rec.message.lower() for rec in caplog.records)
    # the exception itself was swallowed; we shouldn't re-raise it
    assert not any(
        rec.exc_info and rec.exc_info[1] is boom for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# Malformed action strings — also must not crash the dispatcher
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",  # empty
        "   ",  # whitespace
        "notenough",  # missing interface
        "no_dot_in_method",  # can't split interface.method
    ],
)
async def test_malformed_dbus_action_logged_and_ignored(
    caplog: pytest.LogCaptureFixture, value: str
) -> None:
    factory = FakeDbusBusFactory()
    widget = _widget(value)

    with caplog.at_level(logging.WARNING, logger="deckd.actions"):
        await run_action(widget, _ctx(factory))

    # No bus was ever opened for a malformed call
    assert factory.buses == []
    # And the error was logged
    assert any(rec.levelno >= logging.WARNING for rec in caplog.records)


# ---------------------------------------------------------------------------
# Shell action: fire-and-forget launcher (does not block on the child).
# ---------------------------------------------------------------------------


async def test_run_shell_does_not_wait_for_the_child() -> None:
    """A button press returns immediately; a long-running child must not
    block the dispatch coroutine."""
    import time

    from deckd.actions import _run_shell

    start = time.monotonic()
    await _run_shell("sleep 5")
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"_run_shell blocked for {elapsed:.2f}s"


async def test_run_shell_start_failure_is_logged(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A spawn failure (OSError) is caught and logged, never raised."""
    import deckd.actions as actions_mod

    async def boom(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(actions_mod.asyncio, "create_subprocess_shell", boom)
    with caplog.at_level(logging.ERROR, logger="deckd.actions"):
        await actions_mod._run_shell("whatever")
    assert any(rec.levelno >= logging.ERROR for rec in caplog.records)
