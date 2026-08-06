"""Daemon-side ``raise_window`` dispatch (issue #122, stage 3).

Seam under test: ``Server._dispatch_raise_window`` routes a validated
``RaiseWindowMessage`` to the active backend and, on any failure mode,
emits a diagnostic ``raise_failed`` event (#73) rather than tearing down
the websocket session. Four paths:

- happy path: backend raises, no event
- backend declines (``RaiseWindowFailed``): ``reason="declined"``
- backend lacks the capability: ``reason="unsupported"``
- backend raises an unexpected error: ``reason="error"``
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import deckd.protocol as p
from deckd.events import DiagnosticEvent
from deckd.platform import RaiseWindowFailed

from conftest import make_test_server


_DEFAULT_LAYOUT = """
match:
  - default
widgets: []
"""


def _layouts_dir(tmp_path: Path) -> Path:
    (tmp_path / "default.yaml").write_text(_DEFAULT_LAYOUT)
    return tmp_path


class _RaiseBackend:
    """Minimal backend duck-type exercising the raise_window seam."""

    def __init__(self, *, capabilities: frozenset[str], behaviour) -> None:
        self._capabilities = capabilities
        self._behaviour = behaviour
        self.calls: list[str] = []

    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    async def raise_window(self, window_id: str) -> None:
        self.calls.append(window_id)
        if self._behaviour is not None:
            raise self._behaviour


async def _collect_events(server, coro) -> list[DiagnosticEvent]:
    seen: list[DiagnosticEvent] = []

    async def _sink(event: DiagnosticEvent) -> None:
        seen.append(event)

    unsub = server.events.subscribe(_sink)
    try:
        await coro
        # ``EventBus.emit`` schedules each subscriber as its own task;
        # yield the loop so those tasks run before we snapshot.
        await asyncio.sleep(0)
    finally:
        unsub()
    return seen


@pytest.mark.asyncio
async def test_raise_window_happy_path_calls_backend_no_event(tmp_path: Path) -> None:
    backend = _RaiseBackend(capabilities=frozenset({"raise_window"}), behaviour=None)
    server, *_ = make_test_server(layouts_dir=_layouts_dir(tmp_path), focus_backend=backend)
    msg = p.RaiseWindowMessage(type="raise_window", window_id="42")
    events = await _collect_events(server, server._dispatch_raise_window(msg))
    assert backend.calls == ["42"]
    assert [e for e in events if e.name == "raise_failed"] == []


@pytest.mark.asyncio
async def test_raise_window_declined_emits_raise_failed(tmp_path: Path) -> None:
    backend = _RaiseBackend(
        capabilities=frozenset({"raise_window"}),
        behaviour=RaiseWindowFailed("gone"),
    )
    server, *_ = make_test_server(layouts_dir=_layouts_dir(tmp_path), focus_backend=backend)
    msg = p.RaiseWindowMessage(type="raise_window", window_id="gone")
    events = await _collect_events(server, server._dispatch_raise_window(msg))
    failed = [e for e in events if e.name == "raise_failed"]
    assert len(failed) == 1
    assert failed[0].data == {"window_id": "gone", "reason": "declined"}


@pytest.mark.asyncio
async def test_raise_window_unsupported_backend_emits_raise_failed(tmp_path: Path) -> None:
    backend = _RaiseBackend(capabilities=frozenset({"watch_active_app"}), behaviour=None)
    server, *_ = make_test_server(layouts_dir=_layouts_dir(tmp_path), focus_backend=backend)
    msg = p.RaiseWindowMessage(type="raise_window", window_id="1")
    events = await _collect_events(server, server._dispatch_raise_window(msg))
    # Never reaches the backend — the capability gate short-circuits.
    assert backend.calls == []
    failed = [e for e in events if e.name == "raise_failed"]
    assert failed[0].data["reason"] == "unsupported"


@pytest.mark.asyncio
async def test_raise_window_unexpected_error_emits_raise_failed(tmp_path: Path) -> None:
    backend = _RaiseBackend(
        capabilities=frozenset({"raise_window"}),
        behaviour=RuntimeError("bus down"),
    )
    server, *_ = make_test_server(layouts_dir=_layouts_dir(tmp_path), focus_backend=backend)
    msg = p.RaiseWindowMessage(type="raise_window", window_id="7")
    events = await _collect_events(server, server._dispatch_raise_window(msg))
    failed = [e for e in events if e.name == "raise_failed"]
    assert failed[0].data["reason"] == "error"
