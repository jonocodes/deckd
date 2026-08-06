"""Tests for dbus action parsing and dispatch, plus url and text primitives.

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

from conftest import FakeDbusBusFactory, FakePointerSink

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


async def test_press_raise_calls_backend() -> None:
    class Backend:
        def capabilities(self):
            return frozenset({"raise_app"})

        async def raise_app(self, identity):
            self.identity = identity
            return True

    backend = Backend()
    widget = Widget(
        id="raise-btn", kind="button", action=Action.model_validate({"raise": "firefox"})
    )
    ctx = _ctx(FakeDbusBusFactory())
    ctx.focus_backend = backend
    await run_action(widget, ctx)
    assert backend.identity == "firefox"


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


# ---------------------------------------------------------------------------
# URL action dispatch
# ---------------------------------------------------------------------------


def _ctx_key_sink(sink: FakePointerSink) -> ActionContext:
    return ActionContext(
        send_layout=lambda: asyncio.sleep(0),
        get_current_layout=lambda: None,
        current_app="default",
        key_sink=sink,
        dbus_bus_factory=None,
    )


async def test_press_url_opens_via_xdg_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A url: action launches the opener with the URL as an argument."""
    import deckd.actions as actions_mod

    calls: list[tuple] = []

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(actions_mod.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(actions_mod.shutil, "which", lambda _name: "/usr/bin/xdg-open")

    widget = Widget(
        id="url-btn",
        kind="button",
        action=Action(url="https://example.com/path?q=1&frag=#top"),
    )
    await run_action(widget, _ctx_key_sink(FakePointerSink()))

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:2] == ("xdg-open", "https://example.com/path?q=1&frag=#top")
    assert kwargs.get("start_new_session") is True


async def test_press_url_falls_back_to_gio_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When xdg-open is missing, gio open is tried next."""
    import deckd.actions as actions_mod

    calls: list[tuple] = []

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(actions_mod.asyncio, "create_subprocess_exec", fake_exec)

    def fake_which(name: str) -> str | None:
        return None if name == "xdg-open" else "/usr/bin/gio"

    monkeypatch.setattr(actions_mod.shutil, "which", fake_which)

    widget = Widget(
        id="url-btn",
        kind="button",
        action=Action(url="https://example.com"),
    )
    await run_action(widget, _ctx_key_sink(FakePointerSink()))

    assert len(calls) == 1
    assert calls[0][0][:3] == ("gio", "open", "https://example.com")


async def test_url_scheme_validation_rejects_unknown_schemes() -> None:
    """Non-http/https/file schemes are rejected at model load time."""
    with pytest.raises(ValueError, match="url action only accepts"):
        Action(url="ftp://example.com")


async def test_url_scheme_accepts_http_https_file() -> None:
    """Valid URL schemes load without error."""
    for url in ("http://example.com", "https://example.com", "file:///tmp/x.html"):
        a = Action(url=url)
        assert a.url == url


# ---------------------------------------------------------------------------
# Text action dispatch — simulate mode
# ---------------------------------------------------------------------------


async def test_press_text_simulate_types_chars() -> None:
    """text: in simulate mode emits one key combo per character."""
    key_sink = FakePointerSink()
    widget = Widget(
        id="text-btn",
        kind="button",
        action=Action(text="hello", text_mode="simulate"),
    )
    await run_action(widget, _ctx_key_sink(key_sink))

    assert len(key_sink.events) == 5
    for e in key_sink.events:
        assert e["type"] == "key"
    assert key_sink.events[0]["keycodes"] == [35]  # h
    assert key_sink.events[1]["keycodes"] == [18]  # e
    assert key_sink.events[2]["keycodes"] == [38]  # l
    assert key_sink.events[3]["keycodes"] == [38]  # l
    assert key_sink.events[4]["keycodes"] == [24]  # o


async def test_press_text_simulate_defaults_to_simulate() -> None:
    """text without text_mode defaults to simulate."""
    key_sink = FakePointerSink()
    widget = Widget(
        id="text-btn",
        kind="button",
        action=Action(text="ab"),
    )
    await run_action(widget, _ctx_key_sink(key_sink))

    assert len(key_sink.events) == 2
    assert key_sink.events[0]["keycodes"] == [30]  # a
    assert key_sink.events[1]["keycodes"] == [48]  # b


async def test_press_text_falls_back_to_paste_for_multi_byte(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """When text contains chars not in the key maps, auto-fallback to paste."""
    import deckd.actions as actions_mod

    paste_calls: list[tuple] = []

    async def fake_paste(text, ctx, restore, delay_ms=1000):
        paste_calls.append((text, restore))

    monkeypatch.setattr(actions_mod, "_text_paste", fake_paste)

    key_sink = FakePointerSink()
    widget = Widget(
        id="text-btn",
        kind="button",
        action=Action(text="a🎉b"),
    )
    with caplog.at_level(logging.WARNING, logger="deckd.actions"):
        await run_action(widget, _ctx_key_sink(key_sink))

    assert len(paste_calls) == 1
    assert paste_calls[0][0] == "a🎉b"
    assert paste_calls[0][1] is True
    assert any("falling back to paste" in rec.message for rec in caplog.records)


async def test_press_text_explicit_simulate_drops_unknown_chars() -> None:
    """When text_mode: simulate is forced, unknown chars are dropped."""
    key_sink = FakePointerSink()
    widget = Widget(
        id="text-btn",
        kind="button",
        action=Action(text="aéb", text_mode="simulate"),
    )
    await run_action(widget, _ctx_key_sink(key_sink))

    assert len(key_sink.events) == 2
    assert key_sink.events[0]["keycodes"] == [30]
    assert key_sink.events[1]["keycodes"] == [48]


async def test_press_text_empty_string_rejected() -> None:
    """Empty text is rejected at model load time."""
    with pytest.raises(ValueError, match="text action must not be empty"):
        Action(text="")


# ---------------------------------------------------------------------------
# Text action dispatch — paste mode
# ---------------------------------------------------------------------------


async def test_press_text_paste_writes_clipboard_and_sends_ctrl_v(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """paste mode writes to clipboard, emits ctrl+v, and restores."""
    import deckd.actions as actions_mod
    from unittest.mock import AsyncMock

    exec_calls: list[dict] = []

    mock_stdin = AsyncMock()
    mock_stdout = AsyncMock()
    mock_stdout.communicate = AsyncMock(return_value=(b"previous clipboard", None))

    async def fake_exec(*args, stdin=None, stdout=None, stderr=None,
                         start_new_session=False):
        exec_calls.append({
            "args": args,
            "stdin": stdin is not None,
            "stdout": stdout is not None,
            "start_new_session": start_new_session,
        })
        mock = AsyncMock()
        mock.stdin = mock_stdin if stdin is not None else None
        mock.stdout = mock_stdout if stdout is not None else None
        mock.wait = AsyncMock()
        return mock

    monkeypatch.setattr(actions_mod.asyncio, "create_subprocess_exec", fake_exec)

    def fake_which(name: str) -> str | None:
        tools = {"wl-copy": "/usr/bin/wl-copy", "wl-paste": "/usr/bin/wl-paste"}
        return tools.get(name)

    monkeypatch.setattr(actions_mod.shutil, "which", fake_which)

    key_sink = FakePointerSink()
    widget = Widget(
        id="text-btn",
        kind="button",
        action=Action(text="hello world", text_mode="paste", restore_clipboard=True),
    )
    await run_action(widget, _ctx_key_sink(key_sink))

    write_calls = [c for c in exec_calls
                   if len(c["args"]) >= 1 and c["args"][0] == "/usr/bin/wl-copy"]
    assert len(write_calls) >= 1
    key_events = [e for e in key_sink.events if e["type"] == "key"]
    ctrlv = [e for e in key_events if e["keycodes"] == [29, 47]]  # ctrl+v
    assert len(ctrlv) == 1


async def test_press_text_paste_no_clipboard_tool_falls_back_to_simulate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no clipboard tool exists, paste falls back to simulate."""
    import deckd.actions as actions_mod

    monkeypatch.setattr(actions_mod.shutil, "which", lambda _name: None)

    key_sink = FakePointerSink()
    widget = Widget(
        id="text-btn",
        kind="button",
        action=Action(text="ab", text_mode="paste"),
    )
    await run_action(widget, _ctx_key_sink(key_sink))

    assert len(key_sink.events) == 2
    assert key_sink.events[0]["keycodes"] == [30]
    assert key_sink.events[1]["keycodes"] == [48]
