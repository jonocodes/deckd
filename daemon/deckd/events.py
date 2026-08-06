"""Diagnostic event bus and correlation IDs (issue #73).

Two responsibilities:

- :class:`EventBus` lets the daemon publish ``"focus_change"``,
  ``"layout_reload"``, ``"action"``, ``"auth"``, and ``"mpris"``
  events. Subscribers receive the :class:`DiagnosticEvent` payload
  on the event loop so they can fan it out to connected WebSocket
  sessions.
- :data:`correlation_id_var` is a ``ContextVar`` that the dispatcher
  sets on entry to ``_dispatch`` / ``_ws_handler`` so every log line,
  metrics increment, and event published during that call carries the
  same id. Clients can supply the id in their request via the
  ``X-Deckd-Trace`` header on HTTP and the ``trace`` field on a
  WebSocket hello; when absent the daemon generates a fresh UUID.

The context-var pattern keeps correlation IDs implicit at every call
site — every ``record_action`` / ``emit_event`` reads the var and
populates its own field, so callers don't have to thread the id
through. The var is per-task, so concurrent requests keep distinct
ids.
"""
from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import logging
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable

log = logging.getLogger("deckd.events")

#: Per-task correlation id. Set on every incoming request, every
#: press, every focus change. Read by every diagnostic surface.
correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "deckd_correlation_id", default=None
)


def new_correlation_id() -> str:
    """Generate a short, sortable, opaque id suitable for log fields."""
    return uuid.uuid4().hex[:12]


@contextlib.contextmanager
def correlation_scope(value: str | None):
    """Bind ``value`` to the current task's correlation id.

    Usage::

        with correlation_scope(trace_id):
            await handler(...)

    Restores the previous value on exit, so a nested scope shadows but
    does not leak.
    """
    token = correlation_id_var.set(value)
    try:
        yield value
    finally:
        correlation_id_var.reset(token)


def current_correlation_id() -> str | None:
    return correlation_id_var.get()


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DiagnosticEvent:
    """One daemon-side event delivered to diagnostic subscribers.

    The wire schema (``EventMessage`` in ``protocol.py``) mirrors this;
    the bus holds the dataclass and the wire envelope builder copies
    its fields.

    Fields are redacted: the bus never carries the shared password,
    raw injected input, or arbitrary URL payloads (only IDs and small
    scalars). Subscribers that need richer data fetch it from the
    appropriate daemon API (``server.current_layout``, ``mpris.row_ids``,
    etc).
    """

    name: str
    ts: float
    data: dict[str, Any]
    correlation_id: str | None = None

    def to_wire(self) -> dict[str, Any]:
        payload = {
            "type": "event",
            "name": self.name,
            "ts": self.ts,
            "data": self.data,
        }
        if self.correlation_id is not None:
            payload["trace_id"] = self.correlation_id
        return payload


Subscriber = Callable[[DiagnosticEvent], Awaitable[None]]


class EventBus:
    """In-process fan-out for :class:`DiagnosticEvent` instances.

    Single-loop (the server runs on a single asyncio loop), so
    registration and emit don't need locks. Subscribers can be
    coroutines; ``emit`` schedules each one as a task so a slow
    subscriber can't stall the publisher.
    """

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, subscriber: Subscriber) -> Callable[[], None]:
        self._subscribers.append(subscriber)

        def _unsub() -> None:
            try:
                self._subscribers.remove(subscriber)
            except ValueError:
                pass

        return _unsub

    async def emit(self, event: DiagnosticEvent) -> None:
        import asyncio

        # Snapshot the subscriber list so a subscriber unsubscribing
        # itself mid-emit doesn't mutate the iteration.
        # Each subscriber is scheduled as its own task so a slow
        # subscriber can't stall the publisher — a WebSocket send
        # that blocks on TCP backpressure must not delay a focus
        # change for every other session.
        for sub in list(self._subscribers):
            try:
                asyncio.ensure_future(sub(event))
            except Exception as exc:  # don't let one bad subscriber kill the bus
                log.warning("event subscriber failed: %s", exc)