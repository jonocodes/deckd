from __future__ import annotations

import asyncio
import contextlib
import errno
import hmac
import json
import logging
import os
import platform
import secrets
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Sequence

from aiohttp import WSMsgType, web
from pydantic import ValidationError

from . import protocol as p
from .actions import ActionContext, MacroOutcome, execute as run_action
from .input import ScrollController, parse_key_combo, text_to_combos
from .layouts import (
    Layout,
    LayoutStore,
    load_layout,
    load_layouts,
    reconcile_and_write_layout,
    resolve_layout,
    slugify_layout_id,
)
from .media import MediaManager, MediaState, effective_art_token
from .mpris import ChromeMediaState, DbusMprisBackend, MprisBackend, connect_mpris_backend
from .mpris_art import resolve_mpris_art_async
from .diagnostics import (
    ActionRecord,
    MprisEventRecord,
    Metrics,
    MprisEvents,
    RecentActions,
    build_diag_snapshot,
    build_layouts_snapshot,
    build_mpris_players_snapshot,
)
from .events import (
    DiagnosticEvent,
    EventBus,
    correlation_id_var,
    correlation_scope,
    current_correlation_id,
    new_correlation_id,
)

if TYPE_CHECKING:
    from dbus_fast import BusType as BusTypeT
    from dbus_fast.aio import MessageBus

    from .input import KeySink
    from .layouts import Action, Widget
    from .platform import AppInfo, PlatformBackend, SensorManager, SensorReading

from . import PASSWORD_HEADER

log = logging.getLogger("deckd.server")

DEFAULT_APP_ID = "default"

# How long a WebSocket has to send its authenticating ``hello`` before we
# drop it. Generous — a real client sends it immediately on open.
WS_AUTH_TIMEOUT_S = 10.0

# Backstop timeout for the confirmation handshake (issues #69 / #107).
# The daemon-withheld action is dropped after this elapses with no
# ``confirm_response`` from the client; the client mirrors the same
# window so its modal auto-dismisses in lockstep. Generous by design
# (~30 s) so a careful user has time to read the prompt; see
# ``Session._pending_confirms`` for the per-token task bookkeeping.
CONFIRM_TIMEOUT_S = 30.0

# Application-defined WebSocket close code (private-use range 4000-4999)
# meaning "auth rejected". Mnemonic for HTTP 401. The client keys off this
# in onclose so a browser that dropped the rejection frame still learns it
# was unauthorized and shows the password gate.
WS_CLOSE_UNAUTHORIZED = 4401

# Beat between sending the rejection frame and closing, so browsers deliver
# the frame to onmessage as its own event instead of coalescing it with the
# close frame and dropping it.
WS_AUTH_REJECT_GRACE_S = 0.25


def _validation_failed(exc: ValidationError) -> web.Response:
    """``400`` with sanitized Pydantic errors (issue #84 / #99).

    The editor highlights the offending field inline from ``details``, so
    the structure is kept; the values are stripped to ``loc`` / ``msg`` /
    ``type`` only. Pydantic's raw errors carry ``input`` (the value the
    client sent) and ``ctx`` (which can echo ``shell`` / ``dbus`` / ``text``
    action strings), both of which leak payloads across the never-leak
    rule the #70 HTTP routes enforce — so only the three safe fields ride
    to the wire.
    """
    details = [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
        for err in exc.errors()
    ]
    return web.json_response(
        {"ok": False, "error": "validation failed", "details": details}, status=400
    )


def _derivation_failed(loc: list[str | int], msg: str) -> web.Response:
    """``400`` for a non-Pydantic derivation failure, in the same sanitized shape.

    ``POST /layouts`` can fail ``match[0]``-to-filename derivation in ways
    Pydantic doesn't catch (empty ``match``; a token that slugifies to the
    empty string). #88 requires the create endpoint to mirror ``PUT``'s
    structured ``400``, so these ride the same ``{ok, error, details}``
    envelope with a single ``loc``/``msg``/``type`` entry rather than a
    bare string error.
    """
    return web.json_response(
        {
            "ok": False,
            "error": "validation failed",
            "details": [{"loc": loc, "msg": msg, "type": "value_error"}],
        },
        status=400,
    )


class PortInUseError(RuntimeError):
    """The daemon's listen port is already bound by another process.

    Raised from :meth:`Server.start` instead of letting aiohttp's raw
    ``OSError: [Errno 98] address already in use`` traceback escape. The
    message names the port and the one-liners to find and stop the
    offender (almost always a stale deckd instance) so a Vite dev server
    left pointing at a dead backend is diagnosable at a glance rather than
    a wall of asyncio frames. ``__main__`` catches this and exits 1 with
    just the message.
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        super().__init__(
            f"cannot bind {host}:{port} — another process is already "
            f"listening there (usually a stale deckd instance).\n"
            f"  find it:  ss -ltnp | grep {port}   (or: pgrep -af bin/deckd)\n"
            f"  stop it:  pkill -f bin/deckd\n"
            f"  or use another port:  deckd --port <N>"
        )


# ---------------------------------------------------------------------------
# Sensor-source helpers. A widget can reference sensor sources two ways: a
# ``meter`` binds one (``w.source``); a ``stats`` widget binds several (one
# per entry in ``w.metrics``). These fold both shapes into a single view so
# the subscription/pump code doesn't special-case the widget kind.
# ---------------------------------------------------------------------------


def _widget_sources(widget: "Widget") -> list[str]:
    """Every sensor source a widget displays, in declaration order."""
    if widget.kind == "meter" and widget.source:
        return [widget.source]
    if widget.kind == "stats" and widget.metrics:
        return [m.source for m in widget.metrics if m.source]
    return []


def _widget_uses_source(widget: "Widget", source: str) -> bool:
    return source in _widget_sources(widget)


# ---------------------------------------------------------------------------
# Host-identity helpers used by /health. Cheap to compute per-request; no
# caching needed. Broken out so the tests can pin them via monkeypatch.
# ---------------------------------------------------------------------------


def _action_primitive(action: "Action | None", macro: "Macro | None" = None) -> tuple[str, str | None]:
    """Map a widget to ``(primitive, command_text)``.

    Used to populate the recent-action ring buffer and the
    ``action`` diagnostic event. When the widget has a macro, the
    primitive is ``"macro"`` and the command text is the step count.
    For single actions the primitive is ``shell`` / ``key`` /
    ``dbus`` / ``terminal``; ``"press"`` is the fallback.
    """
    from .layouts import Macro
    if macro is not None:
        return "macro", f"{len(macro.steps)} steps"
    if action is None:
        return "press", None
    if action.shell is not None:
        return "shell", action.shell
    if action.terminal:
        return "terminal", None
    if action.key is not None:
        return "key", action.key
    if action.dbus is not None:
        return "dbus", action.dbus
    if action.url is not None:
        return "url", action.url
    if action.text is not None:
        mode = action.text_mode or "simulate"
        return "text", f"[{mode}] {action.text[:40]}"
    return "press", None


def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def _os_pretty() -> str:
    """Best human-readable OS string: PRETTY_NAME from /etc/os-release when
    available, ``uname``-derived fallback otherwise."""
    try:
        info = platform.freedesktop_os_release()
        return info.get("PRETTY_NAME") or info.get("NAME") or platform.system()
    except (OSError, AttributeError):
        return f"{platform.system()} {platform.release()}".strip()


def _desktop_env() -> str:
    """XDG_CURRENT_DESKTOP / XDG_SESSION_DESKTOP if the daemon runs under a
    graphical session, ``"unknown"`` otherwise (headless, TTY, container)."""
    for var in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION"):
        val = os.environ.get(var)
        if val:
            return val
    return "unknown"


def _url_host_for_log(bind: "ResolvedBind") -> str:
    """Format a bind address for log lines / URLs.

    IPv6 literals are bracketed so ``http://[::1]:8765/`` reads as
    one URL, not four ambiguous colons. Issue #66.
    """
    return f"[{bind.host}]" if bind.is_ipv6 else bind.host


def _open_bind_sockets(
    binds: list["ResolvedBind"], port: int
) -> list[socket.socket]:
    """Pre-create one listening socket per resolved bind.

    All sockets share the same port. When ``port=0`` the kernel
    assigns an ephemeral port to the first socket, and we re-bind
    the rest to that exact port — otherwise ``/diag`` would report
    different ports per address and a phone couldn't pair.

    IPv6 sockets use ``IPV6_V6ONLY`` so a single socket can serve
    IPv4-mapped IPv6 if needed; we always open separate v4/v6
    sockets to keep the listener clear and the diagnostic output
    honest.

    Issue #66. Returns ``[]`` when every socket fails — the caller
    surfaces the error.
    """
    opened: list[socket.socket] = []
    actual_port: int | None = None
    failed_host: str | None = None
    for bind in binds:
        family = bind.family
        # Strip the trailing ``%iface`` scope so socket.bind doesn't
        # reject it; bind only needs the address.
        host = bind.host
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            sock.bind((host, actual_port if actual_port is not None else port))
            sock.listen(128)
        except OSError as exc:
            sock.close()
            if exc.errno == errno.EADDRINUSE:
                # The first bind against the operator's explicit
                # port hit a busy one — surface it to the caller
                # which will raise ``PortInUseError`` with the host
                # and port that collided. After that, a per-socket
                # EADDRINUSE is unexpected (we're using the same
                # port that just succeeded), so just warn and skip.
                if actual_port is None:
                    for s in opened:
                        s.close()
                    failed_host = host
                    break
                log.warning("bind on %s:%d failed: %s", host, port, exc)
                continue
            log.warning("bind on %s:%d failed: %s", host, port, exc)
            continue
        # Lock the port after the first socket succeeds so every
        # subsequent bind uses the same number (whether the
        # operator specified one or the kernel picked one).
        if actual_port is None:
            actual_port = int(sock.getsockname()[1])
        opened.append(sock)
    if not opened and failed_host is not None:
        # Stash the failing host on the exception so the caller can
        # turn it into a ``PortInUseError``. We deliberately raise a
        # plain ``OSError`` with ``errno=EADDRINUSE`` to keep the
        # contract simple.
        raise OSError(
            errno.EADDRINUSE, f"bind {failed_host}:{port} address already in use"
        )
    return opened


def _match_resolved(binds: list["ResolvedBind"], host: str) -> "ResolvedBind":
    """Find the ``ResolvedBind`` whose ``host`` matches ``sockname``.

    Used by :meth:`Server.start` to label ``SockSite`` records with
    the originating bind spec so the log line keeps ``iface:wlan0``
    semantics. Falls back to the first bind if nothing matches —
    better than raising in a startup code path.
    """
    host = host.split("%", 1)[0]
    for b in binds:
        if b.host == host:
            return b
    return binds[0]


# ---------------------------------------------------------------------------
# Confirmation-handshake pending state (issues #69 / #107).
# ---------------------------------------------------------------------------


@dataclass
class PendingConfirm:
    """A withheld ``confirm: true`` press waiting on the client's verdict.

    Lives on the originating :class:`Session`, keyed by ``confirm_id``
    (which is what the wire frame carries — not the widget id, so
    overlapping presses of the same widget stay distinct). The
    ``timeout_task`` is a scheduled coroutine that fires
    ``CONFIRM_TIMEOUT_S`` after the press; cancelling it (on response,
    supersession, or session close) prevents the timeout path. ``ctx``
    is the :class:`ActionContext` the dispatch loop built; it's
    captured here so the response handler can re-enter the run path
    without rebuilding plumbing.

    The dataclass is mutable by design: ``record_event`` etc. don't
    need it to be frozen, and we don't hash / share it across tasks.
    """

    confirm_id: str
    widget_id: str
    widget: "Widget"
    ctx: "ActionContext"
    primitive: str
    command_text: str | None
    timeout_task: asyncio.Task[None]


class Session:
    """Per-WebSocket-connection state."""

    def __init__(self, ws: web.WebSocketResponse, server: "Server") -> None:
        self.ws = ws
        self.server = server
        # Demo pin (``?layout=<name>`` in the client URL): when set to a loaded
        # layout id, this session always renders that layout and ignores
        # focus-driven changes. None = normal focus-following behaviour.
        self.pinned_layout_id: str | None = None
        # Chrome view pin (issue #50): when set to a loaded layout id, this
        # session always renders that view's layout (regardless of host
        # focus) and the ``LayoutMessage`` carries ``view=<name>``. Set by
        # the client's ``select_view`` message; cleared by ``clear_view``.
        # Per-session because the chrome icon's affordance is per-client.
        self.view: str | None = None
        # Diagnostic-event subscription (issue #73). ``None`` until the
        # client sends ``enable_events``; a list of event names acts as
        # an allow-list (empty list means "no events"). The session's
        # ``events_unsub`` is the bus callback that forwards events to
        # this client.
        self.events_enabled: list[str] | None = None
        self.events_unsub: Callable[[], None] | None = None
        # Correlation id for this session. Set on connect (from the
        # hello ``trace`` field, an ``X-Deckd-Trace`` header, or a
        # generated UUID) and reused for every diagnostic surface that
        # touches this session — recent-action entries, log fields,
        # and event pushes carry the id.
        self.trace_id: str | None = None
        # Pending confirmation presses (issues #69 / #107). Keyed by
        # ``confirm_id`` so a stale response whose token has already
        # been superseded degrades to an unknown-id no-op on lookup.
        # All timeout tasks here are cancelled on session teardown
        # (see ``_ws_loop``'s ``finally``) so a disconnect mid-confirm
        # drops the pending action without executing it.
        self.pending_confirms: dict[str, PendingConfirm] = {}

    @property
    def app_id(self) -> str:
        return self.server.current_app_id

    async def send(self, message: p.ServerMessage) -> None:
        # Issue #73: when the message carries a ``trace_id`` (currently
        # only :class:`p.EventMessage`), stamp this session's id on so
        # the client can correlate the wire frame back to the
        # diagnostic surfaces. Other message kinds have no ``trace_id``
        # field and ride through unchanged.
        payload = message.model_dump()
        if isinstance(message, p.EventMessage) and self.trace_id:
            payload.setdefault("trace_id", self.trace_id)
        await self.ws.send_json(payload)

    async def send_event(self, event: DiagnosticEvent) -> None:
        """Push a diagnostic event to this session if subscribed.

        Respects the per-session allow-list (``events_enabled``) and
        silently drops events the session didn't opt into. Never raises
        — a dead connection is already torn down by ``push_current``'s
        caller.
        """
        if self.events_enabled is None:
            return
        if self.events_enabled and event.name not in self.events_enabled:
            return
        msg = p.EventMessage(
            type="event",
            name=event.name,
            ts=event.ts,
            data=event.data,
            trace_id=event.correlation_id,
        )
        try:
            await self.send(msg)
        except (ConnectionResetError, RuntimeError, ConnectionError):
            pass

    async def push_current(self) -> None:
        layout = self.server.current_layout
        app_id = self.server.current_app_id
        error = self.server.current_error
        # Pinned demo session: render the named layout regardless of host focus.
        # Re-resolved from the store each push, so a layout-file edit + reload
        # refreshes the pinned view; if the layout was removed on reload, fall
        # back to the focus-driven layout above.
        pin = self.pinned_layout_id
        if pin is not None and pin in self.server.layouts:
            layout = self.server.layouts[pin]
            app_id = pin
            error = None
        # Chrome view pin (issue #50): render the selected view's layout
        # regardless of host focus, with ``view`` set so the client knows to
        # stay on this chrome view. The view id is the synthetic token the
        # client sends in ``select_view``; for the shipping ``mpris.yaml``
        # the id and the first ``match`` token are the same string
        # (``"mpris"``), so the lookup is ``layouts[view]``. If the view
        # id no longer resolves (a reload removed the layout file), keep
        # rendering the focused-app layout and surface
        # ``error: "view not found"`` so the chrome can show the failure
        # without dropping the user out of their normal chrome.
        view_id: str | None = None
        view_error: str | None = None
        if self.view is not None:
            if self.view in self.server.layouts:
                layout = self.server.layouts[self.view]
                app_id = self.view
                error = None
                view_id = self.view
            else:
                view_id = self.view
                view_error = "view not found"
        # Chrome app badge fields are relayed from the active layout even in
        # the error path: the bottom chrome remains the chrome, and a branded
        # badge is more useful than a bare match token while the user fixes
        # on-disk YAML. ``app`` still carries the match token so the chrome
        # can fall back to it when ``display_name`` is None.
        icon = p.Icon.model_validate(layout.icon.model_dump()) if layout.icon else None
        # Web-app badge: this layout is a *web app* only when the focused app is
        # a browser AND the layout claimed it by window title. Computed against
        # the layout actually being sent, so a pinned chrome view (e.g. mpris)
        # or demo pin — which has no ``title:`` token — stays false.
        focus_app = self.server.current_app
        web_app = bool(
            focus_app is not None
            and focus_app.is_browser
            and layout.matches_title(focus_app)
        )
        # Focused-app identity for the editor's new-layout creation flow (#104).
        # Populated from the daemon's last-known focus; None before the first
        # focus event. The editor uses this to prefill match tokens in the
        # detect-and-offer prompt and the browser-vs-site branch.
        focused_app = None
        if focus_app is not None:
            focused_app = p.FocusedAppInfo(
                app_id=focus_app.app_id,
                wm_class=focus_app.wm_class,
                title=focus_app.title,
                is_browser=focus_app.is_browser,
            )
        # Issue #123 / stage 1: ``is_default`` rides on the wire so the
        # client can append ``(program)`` to the layout name on a genuine
        # focus-driven default fallback. Forced false whenever this
        # session is serving a pinned layout/view — a pin means
        # "frozen, don't report what's underneath" even if the pinned
        # layout happens to be the default.
        is_default = (
            self.server._current_is_default and pin is None and view_id is None
        )
        if error is not None:
            # Bad on-disk config: send widgets=[] plus the error text so the
            # client swaps the grid for a diagnostic message.
            msg = p.LayoutMessage(
                type="layout",
                app=app_id,
                view=view_id,
                overflow=layout.overflow,
                jogstrip_enabled=layout.jogstrip,
                display_name=layout.display_name,
                theme=layout.theme,
                icon=icon,
                web_app=web_app,
                focused_app=focused_app,
                is_default=is_default,
                widgets=[],
                error=error,
            )
        else:
            widgets = [w.model_dump() for w in layout.widgets]
            msg = p.LayoutMessage(
                type="layout",
                app=app_id,
                view=view_id,
                overflow=layout.overflow,
                jogstrip_enabled=layout.jogstrip,
                display_name=layout.display_name,
                theme=layout.theme,
                icon=icon,
                web_app=web_app,
                focused_app=focused_app,
                is_default=is_default,
                widgets=widgets,
                # View-resolution errors ride alongside the focused-app
                # widgets so the chrome stays usable while the user sees
                # the failure (``view not found``). Distinct from a
                # ``layout error`` (bad YAML) which replaces the grid.
                error=view_error,
            )
        await self.send(msg)


class Server:
    def __init__(
        self,
        *,
        layouts_dir: Path,
        host: str | None = None,
        port: int = 8765,
        bind: Sequence[str] | None = None,
        scroll: ScrollController | None = None,
        key_sink: "KeySink | None" = None,
        dbus_bus_factory: "Callable[[BusTypeT], MessageBus] | None" = None,
        focus_backend: "PlatformBackend | None" = None,
        overlay_dir: Path | None = None,
        password: str | None = None,
        sensor_manager: "SensorManager | None" = None,
        media_manager: MediaManager | None = None,
        mpris_backend: MprisBackend | None = None,
        mpris_art_resolver: "Callable[[str | None], Awaitable[tuple[str, bytes] | None]] | None" = None,
    ) -> None:
        self.layouts_dir = layouts_dir
        self.overlay_dir = overlay_dir
        # ``None``/empty disables auth entirely (every connection is treated
        # as authorized). When set, every client must present it.
        self.password = password or None
        # Bind addresses (issue #66). ``bind`` is the modern knob:
        # a list of address specs (``127.0.0.1``, ``::1``, ``iface:wlan0``,
        # …). ``host``/``port`` is the legacy single-address shortcut
        # kept so existing tests and the spike module keep working; if
        # ``bind`` is supplied it wins and ``host`` is ignored.
        from .bind import parse_bind_specs

        if bind is not None:
            self._bind_specs: tuple[str, ...] = parse_bind_specs(bind)
        elif host is not None:
            self._bind_specs = parse_bind_specs([host])
        else:
            self._bind_specs = parse_bind_specs(None)
        # ``self.host`` is kept as the first bind's literal address
        # so legacy code paths (``PortInUseError``, the start-up log
        # line, anything that reads ``server.host`` directly) keep
        # working. The full list lives on ``self._bind_resolved`` once
        # ``start()`` has run.
        self.host = self._bind_specs[0]
        self.port = port
        self.app = web.Application()
        # The ``/mpris/<row>/art`` proxy uses an injectable resolver so
        # tests can stub out filesystem / network I/O. Production
        # wires :func:`deckd.mpris_art.resolve_mpris_art_async` (issue
        # #57).
        self._mpris_art_resolver: Callable[[str | None], Awaitable[tuple[str, bytes] | None]] = (
            mpris_art_resolver or resolve_mpris_art_async
        )
        # Diagnostic surface (issue #70/71/72/73). Constructed before
        # ``_setup_routes`` so the route handlers can reference the
        # metrics / event bus / ring buffers they read from.
        self.metrics = Metrics()
        self.events = EventBus()
        self.recent_actions = RecentActions()
        self.mpris_events = MprisEvents()
        self._started_at = self.metrics.uptime_started_at
        self._last_focus: "AppInfo | None" = None
        self._focus_started_ok: bool | None = None
        self._focus_platform: str | None = None
        self._setup_routes()
        self._sessions: set[Session] = set()
        self.layouts: LayoutStore = load_layouts(layouts_dir, overlay_dir)
        self._current_app_id: str = DEFAULT_APP_ID
        self._current_layout: Layout = self.layouts.default()
        # Issue #123 / stage 1: True while the focus-driven resolution
        # is parked on the default layout. ``Session.push_current``
        # reads this to decide whether to set ``is_default`` on the
        # ``LayoutMessage`` — forced false for pinned views there.
        self._current_is_default: bool = True
        self.mpris = mpris_backend
        # Issue #52: when no mpris backend was injected, auto-build
        # one iff a loaded layout uses ``mediabrowser``. Keeps the
        # cost of opening the session bus off the path of users who
        # don't enable the feature. The explicit injection
        # (``mpris_backend=...``) is always honoured, so
        # :class:`FakeMprisBackend` and the pre-configured
        # :class:`DbusMprisBackend` tests bypass this path.
        self._dbus_bus_factory = dbus_bus_factory
        if mpris_backend is None and dbus_bus_factory is not None:
            default = connect_mpris_backend(self.layouts, dbus_bus_factory)
            if default is not None:
                self.mpris = default
        # Issue #47: wire the chrome-media passive indicator listener
        # on whichever backend is now active. The backend fires the
        # listener on ``NameOwnerChanged`` transitions and on
        # ``PlaybackStatus`` boundary crossings; we translate each
        # snapshot into a ``ChromeMediaMessage`` broadcast to every
        # connected session. The listener is sync (the bus signals
        # are too); we schedule the broadcast as a task on the same
        # event loop so the frame lands on the wire immediately,
        # without going through the 1-second media-pump tick.
        if self.mpris is not None:
            self.mpris.set_chrome_media_listener(self._on_chrome_media_change)
            # Diagnostic ring buffer of MPRIS events (issue #72).
            # The backend's ``NameOwnerChanged`` and
            # ``PropertiesChanged`` handlers call this hook; we
            # translate each into a small redacted event so the
            # ``/mpris/events/recent`` endpoint can show a timeline
            # without the watcher needing a live bus.
            self.mpris.set_diagnostic_listener(self._on_mpris_diagnostic_event)
        self.scroll = scroll if scroll is not None else ScrollController()
        self.key_sink = key_sink
        self.dbus_bus_factory = dbus_bus_factory
        # Wrap the supplied ``dbus_bus_factory`` so every ``bus.call()``
        # is timed and the result is recorded on ``self.metrics``. The
        # wrapper preserves the original factory's signature and bus
        # object identity so tests that hand-roll a fake factory
        # (``FakeDbusBusFactory``) keep working unchanged — the
        # ``call()`` they patch still gets observed.
        if dbus_bus_factory is not None:
            from dbus_fast.message import Message as DbusMessage

            original_factory = dbus_bus_factory

            def _timing_factory(bus_type: "BusTypeT") -> "MessageBus":
                bus = original_factory(bus_type)
                original_call = bus.call

                async def _timed_call(message: "DbusMessage") -> "DbusMessage":
                    import asyncio
                    start = asyncio.get_event_loop().time()
                    try:
                        return await original_call(message)
                    finally:
                        self.metrics.record_dbcall(
                            asyncio.get_event_loop().time() - start
                        )

                # ``bus.call`` accepts a single ``Message`` at runtime;
                # reassigning the bound method to a wrapper is the
                # least-bad way to instrument latency from outside
                # dbus_fast.
                bus.call = _timed_call  # type: ignore[method-assign,assignment]
                return bus

            self.dbus_bus_factory = _timing_factory
        self.focus_backend = focus_backend
        self._focus_task: asyncio.Task[None] | None = None
        self._layouts_task: asyncio.Task[None] | None = None
        self._sensor_task: asyncio.Task[None] | None = None
        self._media_task: asyncio.Task[None] | None = None
        self._current_error: str | None = None
        self._deckd_window_focused = False
        # Sensor subscriptions for the active layout. Re-derived whenever
        # the active layout changes (focus change or hot reload) so the
        # daemon only polls sensors the current view is actually using.
        # ``None`` means "use the platform default"; explicit ``None``
        # tests can pass a fake manager. ``_subscribed_sources`` is the
        # set we currently hold refcounts on, used to keep
        # subscribe/unsubscribe balanced across layout changes.
        self.sensors: "SensorManager | None" = sensor_manager
        self._subscribed_sources: set[str] = set()
        self.media = media_manager
        # ``UinputSink`` is a private class (see input.py) so duck-type
        # on the device attribute; anything else counts as the
        # ``LoggingKeySink`` fallback (issue #70 ``input`` block).
        self.metrics.uinput_available = (
            1 if (key_sink is not None and hasattr(key_sink, "_device")) else 0
        )

    # -- layout state --------------------------------------------------------

    @property
    def current_layout(self) -> Layout:
        return self._current_layout

    @property
    def current_app_id(self) -> str:
        return self._current_app_id

    @property
    def current_app(self) -> "AppInfo | None":
        """The most recent focused app (``None`` before the first focus)."""
        return self._last_focus

    @property
    def current_error(self) -> str | None:
        return self._current_error

    def reload_layouts(self) -> None:
        """Re-read every layout YAML in ``layouts_dir`` (and overlay_dir).

        On success: rebuild the store, keep the current app_id if it still
        resolves, else fall back to default, and clear any prior error.

        On failure (bad YAML, schema violation): keep the previous store and
        current layout intact, but record the error on ``current_error`` so
        the next push tells the client to render an error state instead of
        the grid. Callers should not have to catch anything.
        """
        self.metrics.layout_reload_total += 1
        try:
            new_store = load_layouts(self.layouts_dir, self.overlay_dir)
        except SystemExit as exc:
            self._current_error = str(exc)
            self.metrics.layout_error_total += 1
            log.error("layout reload failed (keeping last-good): %s", exc)
            return
        self.layouts = new_store
        try:
            new_layout = self.layouts[self._current_app_id]
        except KeyError:
            self._current_app_id = DEFAULT_APP_ID
            new_layout = self.layouts.default()
        self._current_layout = new_layout
        # Issue #123 / stage 1: a reload can shift the resolved layout
        # between default and identity-matched. Re-derive the flag from
        # the resolved object identity so the wire stays truthful.
        self._current_is_default = new_layout is self.layouts.default()
        self._current_error = None
        self.metrics.layout_reload_ok_total += 1
        # A layout reload can change which meter sources the active
        # layout uses (a meter added in the new YAML, an old one
        # removed). Reconcile subscriptions so the manager polls only
        # what's now in use.
        self._sync_sensor_subscriptions()
        self._sync_media_subscriptions()
        log.info(
            "reloaded layouts from %s%s",
            self.layouts_dir,
            f" + {self.overlay_dir}" if self.overlay_dir else "",
        )
        # Issue #73: emit a diagnostic event so subscribers see the
        # reload. The ``data`` is the directory pair so an AI agent can
        # correlate the reload to the user-edited file.
        asyncio.create_task(
            self.events.emit(
                DiagnosticEvent(
                    name="layout_reload",
                    ts=time.time(),
                    data={
                        "dir": str(self.layouts_dir),
                        "overlay_dir": str(self.overlay_dir)
                        if self.overlay_dir
                        else None,
                        "current_app_id": self._current_app_id,
                        "ok": True,
                    },
                    correlation_id=current_correlation_id(),
                )
            )
        )

    async def _push_to_all(self) -> None:
        """Push the current layout to every live session.

        Stale-connection failures are silently dropped; the session is
        already in the process of being torn down.
        """
        for session in list(self._sessions):
            try:
                await session.push_current()
            except ConnectionResetError:
                pass

    async def reload_and_push(self) -> None:
        self.reload_layouts()
        await self._push_to_all()

    # -- focus watcher -------------------------------------------------------

    def _is_deckd_window(self, app: "AppInfo") -> bool:
        """True if ``app`` is the deckd client browser gaining focus.

        The defining signal is the daemon's own port appearing in the
        focused window's title (the deckd client is served at that port,
        so browsers that surface the URL in the title reveal it). The
        page-title fallback is an exact match on the client's ``<title>``
        (``"deckd"``), which avoids false positives on any tab whose
        title merely contains "deckd" as a substring (e.g. a GitHub tab
        for the deckd repo).
        """
        title = (app.title or "").strip()
        port = self.port
        if port and port > 0 and str(port) in title:
            return True
        return title.lower() == "deckd"

    async def _on_focus(self, app: "AppInfo") -> None:
        self._last_focus = app
        if self._is_deckd_window(app):
            self._deckd_window_focused = True
            self.metrics.focus_deckd_window_guard_total += 1
            log.debug("holding layout; deckd client window focused (%s)", app)
            return
        self._deckd_window_focused = False
        # A genuine (non-deckd) focus change re-resolves the layout, so a
        # `deckctl layout` override never sticks past the next real switch.
        new_layout = resolve_layout(self.layouts, app)
        new_app_id = new_layout.id
        if new_app_id == self._current_app_id and new_layout is self._current_layout:
            return
        self.metrics.focus_events_total += 1
        log.info("focus -> %s (layout=%s)", app, new_app_id)
        self._current_app_id = new_app_id
        self._current_layout = new_layout
        # Issue #123 / stage 1: True iff the focus-driven resolution
        # parked on the default layout. Identity / title matches leave
        # it false so the client suppresses the ``(program)`` suffix.
        self._current_is_default = new_layout is self.layouts.default()
        # Different layouts reference different meter sources (e.g.
        # switching from a desktop to a terminal layout that monitors
        # something else). Resubscribe so the manager's polling tracks
        # the active view.
        self._sync_sensor_subscriptions()
        self._sync_media_subscriptions()
        await self._push_to_all()
        # Issue #73: emit a diagnostic event so subscribers see the
        # focus change. The data is intentionally redacted to the
        # match tokens the layout resolver consumes (``app_id`` /
        # ``wm_class``); ``title`` and ``pid`` ride along but no
        # passwords / typed input.
        asyncio.create_task(
            self.events.emit(
                DiagnosticEvent(
                    name="focus_change",
                    ts=time.time(),
                    data={
                        "app_id": app.app_id,
                        "wm_class": app.wm_class,
                        "title": app.title,
                        "pid": app.pid,
                        "new_layout_id": new_app_id,
                    },
                    correlation_id=current_correlation_id(),
                )
            )
        )

    async def run_focus_watcher(self) -> None:
        """Long-running task: react to focus changes from the backend.

        Reads the initial focus before entering the loop so the daemon
        starts with the correct layout instead of ``default``. Errors
        from the backend on any single iteration are logged but do not
        stop the watcher.

        Backends that own a session-bus name (the KDE KWin-script
        backend, issue #31) override ``PlatformBackend.start``; we
        await it before the first poll so the KWin push target
        (``org.deckd.Focus``) is up before the script's initial
        ``push(workspace.activeWindow)`` arrives. A start failure
        surfaces as ``FocusBackendUnavailable`` and we keep the daemon
        alive on the default layout rather than crashing.
        """
        if self.focus_backend is None:
            return
        backend = self.focus_backend
        self._focus_platform = (
            getattr(backend, "platform", None)
            or getattr(backend, "_platform", None)
        )
        try:
            await backend.start()
        except Exception as exc:
            hint = getattr(exc, "hint", "")
            if hint:
                log.warning("focus backend start failed: %s (hint: %s)", exc, hint)
            else:
                log.warning("focus backend start failed: %s", exc)
            self._focus_started_ok = False
            return
        self._focus_started_ok = True
        try:
            initial = await backend.get_active_app()
        except Exception as exc:
            hint = getattr(exc, "hint", "")
            if hint:
                log.warning("initial focus query failed: %s (hint: %s)", exc, hint)
            else:
                log.warning("initial focus query failed: %s", exc)
            initial = None
        if initial is not None:
            await self._on_focus(initial)
        async for app in backend.watch_active_app():
            try:
                await self._on_focus(app)
            except Exception as exc:
                log.warning("focus handler error: %s", exc)

    def start_focus_watcher(self) -> asyncio.Task[None] | None:
        if self.focus_backend is None or self._focus_task is not None:
            return None
        self._focus_task = asyncio.create_task(self.run_focus_watcher())
        return self._focus_task

    # -- layouts-dir watcher -------------------------------------------------

    async def run_layouts_watcher(self) -> None:
        """Long-running task: reload layouts when a YAML file in the layouts
        directory (or its platform overlay) is created, edited, or removed.

        Layouts are user configuration, not just a dev-only artifact —
        watching them is on by default so a user can iterate on their YAML
        while the daemon is running. Bad edits do not crash the daemon
        (``reload_layouts`` traps parse errors and surfaces them via
        ``current_error``).
        """
        try:
            from watchfiles import awatch
        except ImportError:
            log.warning("watchfiles not installed; layouts hot-reload disabled")
            return
        watch_paths = [self.layouts_dir]
        if self.overlay_dir is not None and self.overlay_dir.is_dir():
            watch_paths.append(self.overlay_dir)
        yaml_suffixes = {".yaml", ".yml"}
        async for changes in awatch(*watch_paths):
            if not any(Path(p).suffix in yaml_suffixes for _, p in changes):
                continue
            log.info("layouts dir changed -> reload")
            try:
                await self.reload_and_push()
            except Exception as exc:
                # reload_layouts already traps parse errors; anything reaching
                # here is a bug we want to see but not kill the watcher for.
                log.exception("unexpected reload failure: %s", exc)

    def start_layouts_watcher(self) -> asyncio.Task[None] | None:
        if self._layouts_task is not None:
            return None
        self._layouts_task = asyncio.create_task(self.run_layouts_watcher())
        return self._layouts_task

    # -- sensor pump ---------------------------------------------------------
    #
    # The :class:`SensorManager` polls sources on its own task and keeps
    # the latest reading in ``_last[name]``. The server's only job is to
    # notice when a reading changes and push a ``widget_update`` frame
    # to every connected session whose active layout has a meter bound
    # to that source. Polling frequency is bounded by the source's
    # ``interval_s``; the pump itself runs at 100ms so a 1s source
    # produces up to one push per second, and we don't notice a
    # millisecond late.

    def _meters_for_source(self, source: str) -> list[Widget]:
        """Return every widget in the active layout that displays ``source``.

        Covers both single-value ``meter`` widgets (``w.source == source``)
        and multi-value ``stats`` widgets (``source`` appears in their
        ``metrics``). Used by the pump to know which widget ``id`` to send
        in the push. Order matches the layout's declaration order so the
        wire is deterministic for tests.
        """
        return [
            w
            for w in self._current_layout.widgets
            if _widget_uses_source(w, source)
        ]

    def _active_sources(self) -> set[str]:
        """Names of every sensor referenced by a meter in the active layout.

        Excludes unknown source names (no such source registered with
        the manager) so a typo in a layout YAML doesn't crash the
        pump — the meter just stays stale. The exclusion is best-effort
        at this layer; the manager's ``is_available`` check is the
        authoritative gate.
        """
        sources: set[str] = set()
        manager = self.sensors
        for w in self._current_layout.widgets:
            for name in _widget_sources(w):
                if manager is None or manager.has(name):
                    sources.add(name)
        return sources

    def _sync_sensor_subscriptions(self) -> None:
        """Reconcile :class:`SensorManager` subscriptions with the active layout.

        Idempotent: calling it back-to-back is a no-op. Drops
        subscriptions to sources no longer referenced; adds new ones.
        Layouts with no meter widgets clear all subscriptions so the
        daemon idles its polling.
        """
        manager = self.sensors
        if manager is None:
            return
        wanted = self._active_sources()
        for name in self._subscribed_sources - wanted:
            manager.unsubscribe(name)
        for name in wanted - self._subscribed_sources:
            manager.subscribe(name)
        self._subscribed_sources = wanted

    async def run_sensor_pump(self) -> None:
        """Watch :class:`SensorManager` and push widget_update frames.

        Compares the manager's ``_last`` against the last value pushed
        for each ``(source, widget_id)`` pair and emits a frame on
        change. Stale-flag flips (``True`` after a sensor error) also
        count as a change so the UI can show the unknown treatment.

        A meter bound to an unknown source simply never produces a
        push — the client renders no value at all. This is intentional:
        the alternative (one push per pump tick with the error
        surfaced) would spam a layout YAML typo across the WebSocket
        forever. The :meth:`_active_sources` filter is the gate that
        keeps unknown sources out of the subscription set in the first
        place.
        """
        manager = self.sensors
        if manager is None:
            return
        manager.start()
        last_pushed: dict[tuple[str, str], tuple[float, bool, str]] = {}
        try:
            while True:
                # Snapshot subscriptions so a layout change that drops a
                # source mid-iteration doesn't reach into a stale entry.
                for name in list(self._subscribed_sources):
                    reading = manager.latest(name)
                    for widget in self._meters_for_source(name):
                        key = (name, widget.id)
                        if reading is None:
                            # No reading yet: don't push until the
                            # source produces one. Avoids spamming an
                            # unknown-value frame at connect time when
                            # the first poll is still pending.
                            continue
                        payload = (reading.value, reading.stale, reading.unit)
                        if last_pushed.get(key) == payload:
                            continue
                        # Only cache the payload once a session has
                        # actually received it. Without this, a pump
                        # tick that runs before any client is connected
                        # would burn the first push — the next tick
                        # (with sessions attached) would see the same
                        # value as already-pushed and silently skip it,
                        # leaving the first client staring at an empty
                        # meter until the value actually changes.
                        if not await self._broadcast_widget_update(widget, reading):
                            continue
                        last_pushed[key] = payload
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            return

    async def _broadcast_widget_update(
        self, widget: Widget, reading: "SensorReading"
    ) -> bool:
        """Send a WidgetUpdateMessage to every connected session.

        Returns ``True`` when at least one session actually received
        the frame. ``False`` when there are no sessions (a pump tick
        that ran before any client connected) or every send errored
        out — the pump uses the False return to skip caching the
        payload so the next tick still sees the same value as new and
        pushes it once a client arrives.

        Stale-connection failures are silently dropped; the session
        is already being torn down. ``stale=True`` messages are sent
        so the client can stop claiming the value is fresh.
        """
        if not self._sessions:
            return False
        msg = p.WidgetUpdateMessage(
            type="widget_update",
            id=widget.id,
            source=reading.source,
            value=reading.value,
            unit=reading.unit,
            stale=reading.stale,
        )
        sent = 0
        dead: list[Session] = []
        for session in list(self._sessions):
            try:
                await session.send(msg)
                sent += 1
            except (ConnectionResetError, RuntimeError, ConnectionError):
                dead.append(session)
        for session in dead:
            self._sessions.discard(session)
        return sent > 0

    def _media_widgets(self) -> list[Widget]:
        return [w for w in self._current_layout.widgets if w.kind == "media"]

    def _has_mediabrowser(self) -> bool:
        # Gate on *any* loaded layout, not the focus-driven current one:
        # the ``mediabrowser`` widget lives in the ``mpris`` chrome view,
        # which a client pins per-session and which is never the focused
        # app's layout. Checking ``_current_layout`` (e.g. the ``vlc``
        # layout while VLC is focused) would starve the pump so the
        # browser stays empty even though a client has it open. Mirrors
        # the ``connect_mpris_backend`` discovery gate.
        return any(
            w.kind == "mediabrowser"
            for layout in self.layouts.layouts
            for w in layout.widgets
        )

    def _sync_media_subscriptions(self) -> None:
        return None

    async def run_media_pump(self) -> None:
        if self.media is None and self.mpris is None:
            return
        last: dict[str, MediaState] = {}
        try:
            while True:
                if self.media is not None:
                    for widget in self._media_widgets():
                        config = widget.media_http
                        if config is None:
                            continue
                        state = await self.media.read(
                            widget.id,
                            host=config.host,
                            port=config.port,
                            password_ref=config.password_ref,
                        )
                        if last.get(widget.id) == state:
                            continue
                        if await self._broadcast_media_state(widget.id, state, widget.art_source or ["vlc"]):
                            last[widget.id] = state
                if self.mpris is not None and self._has_mediabrowser():
                    for row_id in self.mpris.row_ids():
                        state = await self.mpris.read_state(row_id)
                        if state is None or last.get(f"mpris.{row_id}") == state:
                            continue
                        if await self._broadcast_media_state(f"mpris.{row_id}", state, []):
                            last[f"mpris.{row_id}"] = state
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    def _media_message(
        self, widget_id: str, state: MediaState, art_sources: list[str]
    ) -> "p.MediaStateMessage":
        # The art token the client sees depends on the enabled sources: VLC's
        # own art, or an online-lookup identity token when itunes is enabled.
        # ``art_url`` is server-only (the proxy uses it, the client must
        # never see it) so we pop it from ``state.__dict__`` before passing
        # the rest to the wire model. ``art_token`` is computed from the
        # enabled sources, so the raw state field is overwritten last
        # (issue #57).
        fields = dict(state.__dict__)
        fields.pop("art_url", None)
        fields["art_token"] = effective_art_token(state, art_sources)
        return p.MediaStateMessage(type="media_state", id=widget_id, **fields)

    def _chrome_message(self, state: "ChromeMediaState") -> "p.ChromeMediaMessage":
        """Build a ``chrome_media`` frame from a backend snapshot (issue #47).

        Extracted so the broadcast and snapshot paths share one
        constructor — they take different inputs (an event-driven
        snapshot vs. a just-connected session's current view) but
        produce the same wire shape. Mirrors :meth:`_media_message`'s
        role for the per-row ``media_state`` stream.
        """
        return p.ChromeMediaMessage(
            type="chrome_media",
            available=state.available,
            playing=state.playing,
            playing_count=state.playing_count,
        )

    async def _broadcast_media_state(self, widget_id: str, state: MediaState, art_sources: list[str]) -> bool:
        if not self._sessions:
            return False
        msg = self._media_message(widget_id, state, art_sources)
        sent = 0
        dead: list[Session] = []
        for session in list(self._sessions):
            try:
                await session.send(msg)
                sent += 1
            except (ConnectionResetError, RuntimeError, ConnectionError):
                dead.append(session)
        for session in dead:
            self._sessions.discard(session)
        return sent > 0

    def _on_chrome_media_change(self, state: "ChromeMediaState") -> None:
        """Backend listener: schedule a chrome-media broadcast on the
        running event loop (issue #47).

        The backend's signal handlers are synchronous; the broadcast
        is async (it iterates sessions and awaits each ``send``).
        Schedule it as a task so we don't block the bus dispatcher
        thread. ``create_task`` requires a running loop, which is
        guaranteed here because the listener only fires from signals
        delivered through ``dbus_fast.aio.MessageBus`` on the same
        loop the server runs.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        asyncio.create_task(self._broadcast_chrome_media(state))

    def _on_mpris_diagnostic_event(
        self, kind: str, row_id: str | None, data: dict[str, object]
    ) -> None:
        """Backend diagnostic listener (issue #72).

        Appends one :class:`MprisEventRecord` to the server's bounded
        ring buffer. Also increments the matching
        :class:`Metrics` counters so ``/metrics`` reflects the bus
        activity without needing to scan the ring buffer.
        """
        if kind == "player_added":
            self.metrics.mpris_player_added_total += 1
        elif kind == "player_removed":
            self.metrics.mpris_player_removed_total += 1
        elif kind == "playback_changed":
            self.metrics.mpris_playback_changed_total += 1
        elif kind == "metadata_changed":
            self.metrics.mpris_metadata_changed_total += 1
        elif kind == "command":
            pass  # command counter is incremented at the route layer
        elif kind == "dbus_error":
            self.metrics.mpris_dbus_error_total += 1
        elif kind == "art_error":
            self.metrics.mpris_art_errors_total += 1
        self.mpris_events.add(
            MprisEventRecord(ts=time.time(), kind=kind, row_id=row_id, data=data)
        )
        # Issue #73: also emit a ``DiagnosticEvent`` so the WebSocket
        # event stream (``subscribe_to_events``) sees MPRIS changes,
        # not just the bounded ring buffer. ``data`` carries the same
        # row id + structured payload as the ring entry, redacted
        # upstream by the backend (no secret / typed input).
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        asyncio.create_task(
            self.events.emit(
                DiagnosticEvent(
                    name="mpris",
                    ts=time.time(),
                    data={"kind": kind, "row_id": row_id, **data},
                    correlation_id=current_correlation_id(),
                )
            )
        )

    async def _broadcast_chrome_media(self, state: "ChromeMediaState") -> None:
        """Push a ``ChromeMediaMessage`` to every connected session.

        The chrome icon is global chrome (acceptance criterion 3):
        every client receives the frame regardless of which view it
        has pinned. Sessions whose send fails are dropped from the
        set, mirroring the per-session cleanup ``_broadcast_media_state``
        does for the per-row stream.

        No debounce here — the backend already debounces
        (NameOwnerChanged + Playing-boundary transitions only), so
        every listener call is meaningful. The server-side loop
        doesn't add a time window.
        """
        if not self._sessions:
            return
        msg = self._chrome_message(state)
        dead: list[Session] = []
        for session in list(self._sessions):
            try:
                await session.send(msg)
            except (ConnectionResetError, RuntimeError, ConnectionError):
                dead.append(session)
        for session in dead:
            self._sessions.discard(session)

    async def push_chrome_media_snapshot(self, session: Session) -> None:
        """Replay the current chrome-media state to a just-connected session.

        The chrome-media broadcast fires on event-type transitions
        only — a session that connects mid-lifetime would never see
        the current ``playing`` / ``available`` otherwise (e.g. a
        phone that joins while a track is already playing). Mirrors
        :meth:`push_media_snapshot` for the per-row stream.

        Empty cache is fine: the snapshot just reports
        ``available=True`` (or False) and ``playing=False`` until the
        backend's first ``read_state`` populates the per-row cache.
        A freshly-started daemon correctly reports non-playing until
        a real ``Playing`` boundary transition arrives.
        """
        if self.mpris is None:
            return
        await session.send(self._chrome_message(self.mpris.chrome_media_snapshot()))

    async def push_media_snapshot(self, session: Session) -> None:
        """Replay the current MPRIS state to a single just-connected (or
        just-view-switched) session.

        The media pump only broadcasts on *change*, against a global
        ``last`` cache shared by all sessions. A session that connects
        after the last change would otherwise never receive the existing
        players' state — and MPRIS state is static while a track plays the
        same, so "never" is the common case (unlike the VLC ``media``
        widget, whose ``position`` ticks every second and keeps
        re-broadcasting). Replaying a snapshot on connect / ``select_view``
        closes that gap so a reload or a second client shows the players
        immediately instead of "no players detected"."""
        if self.mpris is None or not self._has_mediabrowser():
            return
        for row_id in self.mpris.row_ids():
            state = await self.mpris.read_state(row_id)
            if state is None:
                continue
            with contextlib.suppress(
                ConnectionResetError, RuntimeError, ConnectionError
            ):
                await session.send(self._media_message(f"mpris.{row_id}", state, []))

    def start_sensor_pump(self) -> asyncio.Task[None] | None:
        if self.sensors is None or self._sensor_task is not None:
            return None
        # Make sure the manager is subscribed to whatever the active
        # layout uses before the pump task starts polling. ``__init__``
        # deliberately doesn't subscribe (no event loop yet), and
        # ``reload_layouts`` / ``_on_focus`` keep the set in sync as
        # the layout changes; this call bridges the gap on first start
        # so the very first ``widget_update`` push isn't delayed by a
        # missing subscription.
        self._sync_sensor_subscriptions()
        self._sensor_task = asyncio.create_task(self.run_sensor_pump())
        return self._sensor_task

    def start_media_pump(self) -> asyncio.Task[None] | None:
        if (self.media is None and self.mpris is None) or self._media_task is not None:
            return None
        self._media_task = asyncio.create_task(self.run_media_pump())
        return self._media_task

    #
    # Every WebSocket and HTTP control connection must present the shared
    # password (issue #16). There is no source-address exemption: the check
    # only looks at the password carried in the ``hello`` frame / the
    # ``X-Deckd-Password`` header, never at the peer IP. That keeps it correct
    # behind any proxy (the Vite dev proxy, a TLS terminator) — the password
    # rides in the message, which proxies forward verbatim. ``--no-auth``
    # (``password is None``) turns the whole thing off for local development.

    @property
    def _auth_required(self) -> bool:
        return self.password is not None

    def _check_password(self, candidate: str | None) -> bool:
        """Constant-time compare against the shared password. Always True
        when auth is disabled; always False for a missing candidate."""
        if not self._auth_required:
            return True
        if candidate is None:
            return False
        return hmac.compare_digest(candidate, self.password or "")

    def _http_authorized(self, req: web.Request) -> bool:
        if not self._auth_required:
            return True
        ok = self._check_password(req.headers.get(PASSWORD_HEADER))
        if not ok:
            self.metrics.http_auth_failures_total += 1
            self._publish_auth_event(
                "http_rejected", reason="bad_password", path=req.path
            )
        return ok

    def _publish_auth_event(self, name: str, **data: object) -> None:
        """Issue #73: emit an ``auth`` event when a credentials check fails.

        Subscribed sessions can watch the auth failure stream without
        having to scrape the metrics counter. The ``reason`` field
        always rides along; ``path`` rides for HTTP rejections. The
        event is fire-and-forget — no session alive when it fires
        simply doesn't get it.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        asyncio.create_task(
            self.events.emit(
                DiagnosticEvent(
                    name="auth",
                    ts=time.time(),
                    data={"outcome": name, **data},
                    correlation_id=current_correlation_id(),
                )
            )
        )

    async def _authenticate_ws(self, ws: web.WebSocketResponse) -> dict | None:
        """Read the first frame and require it to be a ``hello`` carrying the
        correct password. Returns the parsed hello (so the caller can apply a
        demo pin) on success, or ``None`` when auth fails."""
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=WS_AUTH_TIMEOUT_S)
        except (asyncio.TimeoutError, ConnectionError):
            return None
        if msg.type != WSMsgType.TEXT:
            return None
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            return None
        if data.get("type") != "hello":
            self.metrics.ws_auth_failures_total += 1
            self._publish_auth_event("ws_rejected", reason="bad_hello_frame")
            return None
        if not self._check_password(data.get("password")):
            self.metrics.ws_auth_failures_total += 1
            self._publish_auth_event("ws_rejected", reason="bad_password")
            return None
        return data

    def _pin_session(self, session: "Session", data: dict) -> bool:
        """Apply the ``?layout=<name>`` demo pin from a hello frame. Returns
        True if the session's pin changed (so the caller re-pushes). An unknown
        or absent name is a no-op — the session keeps following focus. The name
        is resolved leniently (id / display_name / any match token,
        case-insensitively) so friendly names like ``tilix`` work even when the
        layout id is a reverse-DNS token like ``com.gexperts.Tilix``."""
        name = data.get("layout")
        if not isinstance(name, str) or not name:
            return False
        layout_id = self.layouts.resolve_id(name)
        if layout_id is None:
            log.warning("ignoring unknown demo pin layout: %s", name)
            return False
        if session.pinned_layout_id == layout_id:
            return False
        session.pinned_layout_id = layout_id
        log.info("session pinned to layout %s (demo, requested %r)", layout_id, name)
        return True

    # -- routes / lifecycle --------------------------------------------------

    def _setup_routes(self) -> None:
        self.app.router.add_get("/ws", self._ws_handler)
        self.app.router.add_get("/health", self._health)
        # Diagnostic surface (issue #70). Read-only, unauthenticated
        # (matches ``/health``'s posture — no secret leak; cross-origin
        # friendly for the dev client). The route handler builds the
        # snapshot from the server's live state on every request, so
        # there is no stale-cache failure mode.
        self.app.router.add_get("/diag", self._diag)
        self.app.router.add_get("/layouts", self._layouts_list)
        self.app.router.add_get("/actions/recent", self._actions_recent)
        self.app.router.add_get("/metrics", self._metrics)
        self.app.router.add_post("/reload", self._reload)
        self.app.router.add_post("/layout/{layout_id}", self._set_layout)
        # Layout write API (issues #84 / #99). Save and create sit on the
        # same authed aiohttp control surface as ``/reload`` / ``_set_layout``
        # plural ``/layouts`` pairs with the read-only ``GET /layouts`` and
        # distances the write path from the runtime-override
        # ``POST /layout/{id}`` (singular). PUT = idempotent full-snapshot
        # replace of an existing file; POST = create-on-first-save deriving
        # id/filename from slugified ``match[0]``. Validation, sanitized
        # structured errors, and the canonical re-read echo are shared.
        self.app.router.add_put("/layouts/{layout_id}", self._put_layout)
        self.app.router.add_post("/layouts", self._post_layout)
        # Album-art proxy. Deliberately unauthenticated (art is low-value and
        # an <img> tag can't carry the password header): the daemon fetches
        # the current item's art from VLC's own HTTP interface and streams it
        # back so the phone never needs VLC's credentials or a local file path.
        self.app.router.add_get("/media/{widget_id}/art", self._media_art)
        # MPRIS album-art proxy (issue #57). Same rationale as
        # ``/media/<id>/art`` — unauthenticated, server-side fetch —
        # but the URL the proxy serves is the row's current
        # ``Metadata.mpris:artUrl`` (``file://`` / ``http(s)://`` /
        # ``data:``), never a client-supplied path. An ``<img>`` tag
        # can't carry the password header, and the art itself is
        # low-value; the proxy's only safety constraint is the one
        # above (the row id is the only thing the URL is keyed on).
        self.app.router.add_get("/mpris/{row_id}/art", self._mpris_art)
        # MPRIS diagnostic endpoints (issue #72). Players and recent
        # events stay read-only and unauthenticated; ``POST .../command``
        # is gated the same as ``/reload`` — the command list is the
        # validated small set the wire protocol already accepts, so
        # nothing arbitrary can be invoked.
        self.app.router.add_get("/mpris/players", self._mpris_players)
        self.app.router.add_get("/mpris/events/recent", self._mpris_events_recent)
        self.app.router.add_post("/mpris/{row_id}/command", self._mpris_command)

    async def _health(self, _req: web.Request) -> web.Response:
        # The one endpoint left open when auth is on: the web client's
        # Settings panel fetches /health for host-identity diagnostics
        # (often before the user has entered the password), and unlike
        # /reload and /layout it neither mutates state nor injects input.
        # The only exposure is hostname/OS/desktop/session-count plus
        # the bind surface (issue #66) so a phone pairing in via the
        # same machine can read the URL it should hit.
        #
        # On the Vite dev path (:5173 -> :8765) that fetch is cross-origin,
        # so the browser needs an explicit allow header or it drops the
        # response; ``*`` is fine for a read-only diagnostic.
        from .bind import ResolvedBind, url_for as _bind_url_for

        binds = self._bound_addresses(_req)
        port = self._bound_port(_req)
        # Rebuild ResolvedBind records from ``(host, port)`` pairs so
        # ``url_for`` can apply its IPv4-over-IPv6 preference. The
        # family is detected from the address itself — the daemon
        # never needs an explicit AF_INET6 flag because bind
        # resolution already collapsed v4 vs v6 into the host string.
        family_lookup = {
            "127.0.0.1": socket.AF_INET,
            "0.0.0.0": socket.AF_INET,
        }
        resolved_for_url = [
            ResolvedBind(
                host=host,
                family=family_lookup.get(host, socket.AF_INET6 if ":" in host else socket.AF_INET),
                original=self._bind_specs[i] if i < len(self._bind_specs) else host,
            )
            for i, (host, _) in enumerate(binds)
        ]
        body = {
            "ok": True,
            "sessions": len(self._sessions),
            "app": self._current_app_id,
            "hostname": _hostname(),
            "os": _os_pretty(),
            "desktop": _desktop_env(),
            # ``bind`` is the operator-configured bind surface
            # (``127.0.0.1``, ``::1``, ``iface:wlan0``, …) — what
            # they asked for, not what got resolved. ``addresses`` is
            # the post-resolution ``[host:port, …]`` list. ``url`` is
            # a single pairing URL pointing at the preferred bind
            # (IPv4 wins; IPv6 only when nothing else is bound).
            "bind": list(self._bind_specs),
            "addresses": [f"{_url_host_for_log(b)}:{port}" for b in resolved_for_url],
            "url": _bind_url_for(resolved_for_url, port),
        }
        return web.json_response(body, headers={"Access-Control-Allow-Origin": "*"},
        )

    async def _diag(self, req: web.Request) -> web.Response:
        # Issue #70: read-only snapshot of every subsystem that
        # affects a button press or layout switch. Mirrors ``/health``'s
        # open-auth stance (no secret leak — host identity, focus, input
        # sink, layouts, sessions, tasks, MPRIS). The dict is built
        # fresh on every request; intentionally no caching, so a user
        # watching with ``watch -n1 curl`` sees live values.
        self.metrics.sessions_active = len(self._sessions)
        # Resolve the actually-bound port at request time. ``self.port``
        # holds the configured value; a daemon launched with ``--port 0``
        # gets a real port from ``site.start()`` and updates it in
        # place. The runner check covers tests that go through
        # ``aiohttp.test_utils.TestServer`` and never call ``start()``;
        # those surface the runner's bound port via ``self._runner``.
        # The request-transport fallback handles TestServer, which has
        # its own runner and never sets ``self._runner``.
        bound_port = self._bound_port(req)
        body = await build_diag_snapshot(
            server=self, started_at=self._started_at, bound_port=bound_port
        )
        return web.json_response(body, headers={"Access-Control-Allow-Origin": "*"})

    def _bound_port(self, req: web.Request | None = None) -> int:
        """The port the daemon is actually listening on.

        Tries the runner first (production path: ``start()`` updates
        ``self.port``), then falls back to the aiohttp runner's
        first ``SockSite``/``TCPSite`` for the ``TestServer`` path,
        then to the request transport's ``getsockname()``. ``self.port``
        itself is the final fallback.
        """
        # ``_bind_resolved`` is the post-start source of truth (issue
        # #66) and contains the actually-listening port already.
        resolved = getattr(self, "_bind_resolved", None)
        if resolved:
            return self.port
        runner = getattr(self, "_runner", None)
        if runner is not None and getattr(runner, "sites", None):
            # ``AppRunner.sites`` is a ``set`` — index access isn't
            # valid. Sort by the underlying socket's ``getsockname``
            # so the diagnostic output is deterministic.
            for site in runner.sites:
                try:
                    abstract_server = site._server  # type: ignore[attr-defined]
                    sockets = (
                        getattr(abstract_server, "sockets", None)
                        if abstract_server is not None
                        else None
                    )
                    if sockets:
                        return int(sockets[0].getsockname()[1])
                except Exception:  # pragma: no cover -- defensive
                    continue
        if req is not None:
            try:
                sock = req.transport.get_extra_info("sockname")  # type: ignore[union-attr]
                if sock:
                    return int(sock[1])
            except Exception:
                pass
        return self.port

    def _bound_addresses(self, req: web.Request | None = None) -> list[tuple[str, int]]:
        """The ``(host, port)`` tuples the daemon is currently bound to.

        Returns the resolved bind list after ``start()`` has run.
        Falls back to ``(self.host, self._bound_port(req))`` when the
        runner isn't wired yet (TestServer fixtures, ``/health``
        before ``start()`` returns). The ``req`` argument lets the
        fallback path learn the actually-listening port from the
        request's transport when ``self.port`` is still ``0``.

        Issue #66: this is what ``/health`` and ``/diag`` surface so
        operators can confirm the listening surface matches what
        they configured.
        """
        resolved = getattr(self, "_bind_resolved", None)
        if resolved:
            return [(b.host, self.port) for b, _ in resolved]
        return [(self.host, self._bound_port(req))]

    async def _layouts_list(self, req: web.Request) -> web.Response:
        # Authenticated editors need full widget data (including action/macro
        # bodies). Unauthenticated callers (diagnostics page) get the safe
        # summary: no shell/dbus/key strings.
        full = self._http_authorized(req)
        body = build_layouts_snapshot(self.layouts, full=full)
        return web.json_response(body, headers={"Access-Control-Allow-Origin": "*"})

    async def _actions_recent(self, req: web.Request) -> web.Response:
        # Issue #70: bounded history of the most recent action
        # attempts. The wire entries never carry the action's command
        # text (a typed-string ``type:`` injection could leak keystrokes
        # via this route); ``/actions/recent`` exposes only ids and
        # outcomes so an AI agent can answer "did the press happen?"
        # without seeing the payload.
        try:
            limit = int(req.query.get("limit", "64"))
        except ValueError:
            limit = 64
        records = self.recent_actions.snapshot(limit)
        body = {"ok": True, "events": [r.to_wire() for r in records]}
        return web.json_response(body, headers={"Access-Control-Allow-Origin": "*"})

    async def _metrics(self, _req: web.Request) -> web.Response:
        # Issue #71: Prometheus text-format scrape target. The renderer
        # is intentionally stdlib-only (the format is one page; adding
        # a client library would pull a multiprocess mode that doesn't
        # apply to a single-process daemon). Counters live on the
        # Server's ``metrics`` attribute; tests can construct one and
        # call ``render()`` directly.
        self.metrics.sessions_active = len(self._sessions)
        body = self.metrics.render()
        return web.Response(
            text=body,
            content_type="text/plain",
            charset="utf-8",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def _mpris_players(self, _req: web.Request) -> web.Response:
        # Issue #72: read-only enumeration of discovered MPRIS players
        # with redacted state and metadata. ``art_url`` itself never
        # leaves the daemon (the proxy resolves it). Mirrors
        # ``/health``'s open-auth stance.
        body = await build_mpris_players_snapshot(self.mpris)
        return web.json_response(body, headers={"Access-Control-Allow-Origin": "*"})

    async def _mpris_events_recent(self, req: web.Request) -> web.Response:
        # Issue #72: bounded history of MPRIS subsystem events.
        try:
            limit = int(req.query.get("limit", "64"))
        except ValueError:
            limit = 64
        records = self.mpris_events.snapshot(limit)
        body = {"ok": True, "events": [r.to_wire() for r in records]}
        return web.json_response(body, headers={"Access-Control-Allow-Origin": "*"})

    async def _mpris_command(self, req: web.Request) -> web.Response:
        # Issue #72: dispatch a validated MPRIS command to the named
        # row. Auth-gated (``X-Deckd-Password``) like ``/reload``. The
        # command list is the literal set the wire protocol accepts
        # (``play-pause`` / ``next`` / ``previous`` / ``raise``); anything
        # else is a 400, so a bug in a caller can't invoke an arbitrary
        # D-Bus method. ``raise`` is reserved for future MPRIS Raise()
        # support and currently returns 400 (no-op).
        if not self._http_authorized(req):
            self.metrics.http_auth_failures_total += 1
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        if self.mpris is None:
            return web.json_response({"ok": False, "error": "no MPRIS backend"}, status=503)
        row_id = req.match_info["row_id"]
        try:
            payload = p.MprisCommandRequest.model_validate(await req.json() or {})
        except Exception as exc:
            return web.json_response(
                {"ok": False, "error": f"invalid body: {exc}"}, status=400
            )
        if payload.command == "raise":
            # Kept in the model on purpose; the spec's acceptance
            # criterion mentions ``raise`` so callers sending the
            # literal get a meaningful ``400`` instead of a 422 from
            # pydantic. Will land in a follow-up alongside the
            # MPRIS Raise() support ticket.
            return web.json_response(
                {"ok": False, "error": "raise not implemented"}, status=400
            )
        trace = req.headers.get("X-Deckd-Trace") or new_correlation_id()
        with correlation_scope(trace):
            try:
                await self.mpris.send_command(row_id, payload.command)
                self.metrics.record_mpris_command(payload.command, ok=True)
                return web.json_response(
                    {"ok": True, "row_id": row_id, "command": payload.command}
                )
            except Exception as exc:
                self.metrics.record_mpris_command(payload.command, ok=False)
                log.warning("MPRIS command %s on %s failed: %s", payload.command, row_id, exc)
                return web.json_response(
                    {"ok": False, "error": repr(exc)}, status=502
                )

    async def _media_art(self, req: web.Request) -> web.StreamResponse:
        widget = self._find_widget(req.match_info["widget_id"])
        if widget is None or self.media is None or widget.media_http is None:
            raise web.HTTPNotFound()
        config = widget.media_http
        art = await self.media.art(
            widget.id,
            host=config.host,
            port=config.port,
            password_ref=config.password_ref,
            sources=widget.art_source or ["vlc"],
        )
        if art is None:
            raise web.HTTPNotFound()
        content_type, data = art
        # The client cache-busts with ?token=<art_token>, so a given URL is
        # immutable — let the browser cache it hard and skip refetching until
        # the track (and thus the token) changes.
        return web.Response(
            body=data,
            content_type=content_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    async def _mpris_art(self, req: web.Request) -> web.StreamResponse:
        # MPRIS art proxy (issue #57). Two layers of indirection keep
        # the proxy safe by construction:
        #   1. The URL the proxy serves is the row's current
        #      ``art_url`` — the resolver never reads a URL off the
        #      request, so a client can't redirect it. A query string
        #      like ``?file=...`` is silently ignored.
        #   2. The resolver itself only handles ``file://`` /
        #      ``http(s)://`` / ``data:`` and 404s on anything else
        #      (including missing / malformed input), so even a
        #      crafted artUrl can't make the daemon read arbitrary
        #      paths.
        if self.mpris is None:
            raise web.HTTPNotFound()
        row_id = req.match_info["row_id"]
        art_url = self.mpris.art_url(row_id)
        if art_url is None:
            raise web.HTTPNotFound()
        art = await self._mpris_art_resolver(art_url)
        if art is None:
            raise web.HTTPNotFound()
        content_type, data = art
        # Same cache-busting story as ``/media/<id>/art``:
        # ``?token=<art_token>`` makes the URL immutable until the
        # track changes, so the browser can keep the cover.
        return web.Response(
            body=data,
            content_type=content_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    async def _reload(self, req: web.Request) -> web.Response:
        if not self._http_authorized(req):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        await self.reload_and_push()
        body: dict = {
            "ok": self._current_error is None,
            "sessions": len(self._sessions),
            "app": self._current_app_id,
        }
        if self._current_error is not None:
            body["error"] = self._current_error
        return web.json_response(body, status=200 if self._current_error is None else 400)

    async def _set_layout(self, req: web.Request) -> web.Response:
        if not self._http_authorized(req):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        layout_id = req.match_info["layout_id"]
        try:
            layout = self.layouts[layout_id]
        except KeyError:
            return web.json_response(
                {"ok": False, "error": f"unknown layout: {layout_id}"}, status=404
            )
        await self._apply_layout_override(layout_id, layout)
        return web.json_response(
            {"ok": True, "app": layout_id, "sessions": len(self._sessions)}
        )

    # -- layout write API (issues #84 / #99) --------------------------------

    async def _read_and_validate_layout(
        self, req: web.Request
    ) -> tuple[dict, Layout] | web.Response:
        """Shared ``PUT``/``POST`` preamble: auth, JSON parse, schema validate.

        Returns the parsed snapshot and the validated :class:`Layout` on
        success, or a ready-to-send ``401``/``400`` response. Centralising
        the auth gate, the JSON-body requirement, and the sanitized
        validation-error path keeps the never-leak-payloads rule in one
        place both endpoints share. The validated ``Layout`` is returned
        alongside even though the reconcile writes the raw snapshot —
        callers that want coerced/defaults use it; the write path keeps
        the raw dict for full-snapshot omitted-field semantics (issue #85).
        """
        if not self._http_authorized(req):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        try:
            snapshot = await req.json()
        except Exception:
            return web.json_response(
                {"ok": False, "error": "request body must be JSON"}, status=400
            )
        if not isinstance(snapshot, dict):
            return _derivation_failed([], "request body must be a JSON object")
        try:
            layout = Layout.model_validate(snapshot)
        except ValidationError as exc:
            return _validation_failed(exc)
        return snapshot, layout

    async def _put_layout(self, req: web.Request) -> web.Response:
        """``PUT /layouts/{id}`` — idempotent full-snapshot save (issue #84).

        The URL ``{id}`` is authoritative and must equal the body's
        ``match[0]``; a ``match[0]`` change is a rename (create-shaped) and
        is rejected with ``409``. The body is validated as a full
        :class:`Layout` (so the #85 duplicate-widget-id validator and every
        per-widget invariant run), reconciled onto a fresh on-disk re-read
        per #85 (comments ride along, widgets matched by ``id``), and
        written atomically. The response echoes the canonical re-read; the
        ``watchfiles`` watcher independently refreshes the live deck.
        """
        layout_id = req.match_info["layout_id"]
        path = self.layouts.source_path(layout_id)
        if path is None:
            return web.json_response(
                {"ok": False, "error": f"unknown layout: {layout_id}"}, status=404
            )
        parsed = await self._read_and_validate_layout(req)
        if isinstance(parsed, web.Response):
            return parsed
        snapshot, _layout = parsed
        match = snapshot.get("match") or []
        if not match or match[0] != layout_id:
            return web.json_response(
                {"ok": False, "error": "match[0] must equal the layout id in the URL; use the create endpoint to rename"},
                status=409,
            )
        return self._write_and_echo(path, snapshot)

    async def _post_layout(self, req: web.Request) -> web.Response:
        """``POST /layouts`` — create-on-first-save (issue #99).

        Derives id/filename from slugified ``match[0]``; ``409`` if the id
        (or a slugified filename) already exists. Validation and the
        canonical re-read echo mirror :meth:`_put_layout`; the brand-new
        file has no comments to preserve so the reconcile writes the
        snapshot fresh. Derivation failures (empty ``match``, an
        unsigilable token) return the same sanitized structured ``400`` as
        Pydantic validation failures so the editor sees one 400 shape.
        """
        parsed = await self._read_and_validate_layout(req)
        if isinstance(parsed, web.Response):
            return parsed
        snapshot, _layout = parsed
        match = snapshot.get("match") or []
        if not match:
            return _derivation_failed(["match"], "match must be non-empty to derive a layout id")
        try:
            stem = slugify_layout_id(match[0])
        except ValueError as exc:
            return _derivation_failed(["match", 0], str(exc))
        new_path = self.layouts_dir / f"{stem}.yaml"
        # The canonical id equals match[0] verbatim (load_layout assigns it
        # on re-read); collision-check both the in-memory store and the
        # target file so a differently-cased match token can't shadow an
        # existing file via the slugified filename.
        if match[0] in self.layouts or new_path.exists():
            return web.json_response(
                {"ok": False, "error": f"layout already exists: {match[0]}"}, status=409
            )
        return self._write_and_echo(new_path, snapshot)

    def _write_and_echo(self, path: Path, snapshot: dict) -> web.Response:
        """Reconcile-and-write ``snapshot`` to ``path``; echo the canonical re-read.

        Shared by ``PUT`` (existing file) and ``POST`` (new file). On a
        disk/write failure surfaces a ``5xx`` rather than a partial state;
        the request/response owns editor state-sync while the
        ``watchfiles`` watcher owns the live-deck reload.
        """
        try:
            reconcile_and_write_layout(path, snapshot)
            canonical = load_layout(path)
        except SystemExit as exc:
            log.error("layout write/re-read failed for %s: %s", path, exc)
            return web.json_response(
                {"ok": False, "error": f"layout write failed: {exc}"}, status=500
            )
        except OSError as exc:
            log.error("layout write failed for %s: %s", path, exc)
            return web.json_response(
                {"ok": False, "error": f"layout write failed: {exc}"}, status=500
            )
        log.info("layout saved -> %s", path)
        return web.json_response(
            {"ok": True, "layout": canonical.model_dump()}
        )

    async def _apply_layout_override(self, layout_id: str, layout: Layout) -> None:
        """Force every connected client to ``layout`` (addressed by ``layout_id``).

        Bypasses focus detection entirely. The override is not sticky: the
        next genuine (non-deckd-window) focus change re-resolves the layout
        and switches as normal.
        """
        self._current_app_id = layout_id
        self._current_layout = layout
        # Issue #123 / stage 1: an override is not focus-driven, so the
        # ``is_default`` wire flag is always false here — even if the
        # override target happens to be the default layout. The next
        # genuine focus event in ``_on_focus`` restores the flag to the
        # true resolution state.
        self._current_is_default = False
        log.info("layout override -> %s", layout_id)
        await self._push_to_all()

    async def _ws_handler(self, req: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(req)
        # Clients must authenticate before we add the session or leak any
        # layout. The authenticating ``hello`` frame is consumed here;
        # subsequent frames flow through the normal dispatch loop.
        session = Session(ws, self)
        # Issue #73: bind a correlation id for the lifetime of this
        # connection. The ``trace`` field on a hello frame (or the
        # ``X-Deckd-Trace`` header on the upgrade) lets the client
        # supply its own; absent that we mint a fresh short id. The id
        # rides on every diagnostic surface touched by the connection
        # — recent-action entries, log fields, and event pushes.
        trace = req.headers.get("X-Deckd-Trace")
        if self._auth_required:
            hello = await self._authenticate_ws(ws)
            if hello is None:
                log.info("ws auth failed from %s; closing", req.remote)
                # A client that failed (or abandoned) auth has often already
                # closed the socket, so the rejection frame races the teardown.
                # Suppress the write-to-closing-transport error: the rejection
                # is best-effort and the connection is going away regardless.
                with contextlib.suppress(ConnectionError, RuntimeError):
                    await ws.send_json({"type": "error", "reason": "unauthorized"})
                    # Browsers coalesce a data frame with an immediately
                    # following close frame and drop the data one, so the
                    # client's onmessage never sees the rejection and it just
                    # reconnect-loops without ever showing the password gate.
                    # Two defences: (1) a short beat so the data frame is
                    # delivered as its own event before the close, and (2) a
                    # dedicated close code the client also treats as
                    # unauthorized — the close code survives the race even if
                    # the frame is still dropped. (A raw ws client tolerates
                    # the coalescing; a browser does not.)
                    await asyncio.sleep(WS_AUTH_REJECT_GRACE_S)
                    await ws.close(code=WS_CLOSE_UNAUTHORIZED, message=b"unauthorized")
                return ws
            # Auth consumed the hello, so apply its demo pin before the initial
            # push. (No-auth clients' hellos arrive via _dispatch instead.)
            self._pin_session(session, hello)
            if isinstance(hello, dict):
                if not trace and isinstance(hello.get("trace"), str):
                    trace = hello["trace"]
        if not trace:
            trace = new_correlation_id()
        session.trace_id = trace
        token = correlation_id_var.set(trace)
        try:
            await self._ws_loop(req, ws, session)
        finally:
            correlation_id_var.reset(token)
            if session.events_unsub is not None:
                session.events_unsub()
                session.events_unsub = None
        return ws

    async def _ws_loop(
        self, req: web.Request, ws: web.WebSocketResponse, session: Session
    ) -> None:
        self._sessions.add(session)
        log.info(
            "client connected (%d, app=%s)", len(self._sessions), self._current_app_id
        )
        try:
            await session.push_current()
            # The media pump only broadcasts on change, so replay a
            # snapshot to this fresh session — otherwise a reload / second
            # client sees "no players detected" until the state next
            # changes (which for a steadily-playing MPRIS track is never).
            await self.push_media_snapshot(session)
            # Issue #47: same snapshot rationale for the chrome-media
            # indicator. A second client connecting while a track is
            # already playing would otherwise never see ``playing=true``
            # until the next boundary transition (which is rare).
            await self.push_chrome_media_snapshot(session)
            async for raw in ws:
                if raw.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(raw.data)
                except json.JSONDecodeError:
                    log.warning("invalid JSON from client; ignoring")
                    continue
                await self._dispatch(session, data)
        finally:
            self._sessions.discard(session)
            # Issue #69 / #107: cancel every pending confirmation's
            # timeout task so a mid-confirm disconnect never lets a
            # dangerous action slip through after the timeout window
            # (the action was already withheld; this is the second
            # line of defence in case ``_dispatch_press``'s finally
            # ordering changes in a future refactor).
            for pending in list(session.pending_confirms.values()):
                pending.timeout_task.cancel()
            session.pending_confirms.clear()
            log.info("client disconnected (%d remaining)", len(self._sessions))

    async def _dispatch(self, session: Session, data: dict) -> None:
        msg_type = data.get("type")
        if msg_type == "hello":
            log.info("client hello (token=%s)", bool(data.get("token")))
            # Issue #73: the no-auth path receives the hello here
            # (after the initial push). A client-supplied ``trace``
            # field becomes the session's id; absent it the daemon
            # keeps the id minted at connect time.
            trace = data.get("trace")
            if isinstance(trace, str) and trace:
                session.trace_id = trace
                correlation_id_var.set(trace)
            # No-auth path: the hello arrives here (after the initial push), so
            # applying a demo pin needs a re-push to switch this client over.
            if self._pin_session(session, data):
                await session.push_current()
            return
        if msg_type == "jog":
            msg = p.JogMessage.model_validate(data)
            self.scroll.jog(msg.id, msg.delta)
            return
        if msg_type == "jog_end":
            jog_end = p.JogEndMessage.model_validate(data)
            self.scroll.jog_end(jog_end.id, jog_end.velocity)
            return
        if msg_type == "pad":
            pad = p.PadMessage.model_validate(data)
            if self.key_sink is not None:
                self.key_sink.emit_pointer(pad.dx, pad.dy)
            return
        if msg_type == "pad_tap":
            tap = p.PadTapMessage.model_validate(data)
            if self.key_sink is not None:
                button = "right" if tap.fingers == 2 else "left"
                self.key_sink.emit_click(button, True)
                self.key_sink.emit_click(button, False)
            return
        if msg_type == "pad_drag":
            drag = p.PadDragMessage.model_validate(data)
            if self.key_sink is not None:
                self.key_sink.emit_click("left", drag.state == "start")
            return
        if msg_type == "type":
            tmsg = p.TypeMessage.model_validate(data)
            if self._injection_blocked(tmsg.text):
                return
            if self.key_sink is not None:
                for combo in text_to_combos(tmsg.text):
                    self.key_sink.emit_key(combo)
            return
        if msg_type == "key":
            kmsg = p.KeyMessage.model_validate(data)
            if self._injection_blocked(kmsg.combo):
                return
            if self.key_sink is not None:
                self.key_sink.emit_key(parse_key_combo(kmsg.combo))
            return
        if msg_type == "media_command":
            media_command = p.MediaCommandMessage.model_validate(data)
            if media_command.id.startswith("mpris."):
                if self.mpris is None:
                    return
                try:
                    await self.mpris.send_command(
                        media_command.id.removeprefix("mpris."), media_command.command
                    )
                    self.metrics.record_mpris_command(media_command.command, ok=True)
                except Exception as exc:
                    self.metrics.record_mpris_command(media_command.command, ok=False)
                    log.warning("MPRIS command %s failed: %s", media_command.command, exc)
                return
            widget = self._find_widget(media_command.id)
            if widget is None or self.media is None or widget.media_http is None:
                return
            config = widget.media_http
            try:
                await self.media.command(
                    widget.id,
                    media_command.command,
                    media_command.value,
                    host=config.host,
                    port=config.port,
                    password_ref=config.password_ref,
                )
            except Exception as exc:
                # A failed/unsupported media command must not tear down the
                # websocket session (which would reset the client UI).
                log.warning("media command %s failed: %s", media_command.command, exc)
            return
        if msg_type == "select_view":
            select_view = p.SelectViewMessage.model_validate(data)
            log.info("session selected view %r", select_view.view)
            session.view = select_view.view
            await session.push_current()
            # Tapping the media icon switches to the browser view; replay
            # the current players so they appear immediately rather than
            # waiting for the pump's next state change.
            await self.push_media_snapshot(session)
            return
        if msg_type == "clear_view":
            log.info("session cleared view")
            session.view = None
            await session.push_current()
            return
        if msg_type == "enable_events":
            enable = p.EnableEventsMessage.model_validate(data)
            session.events_enabled = enable.events or []
            if session.events_unsub is None:
                async def _forward(event: DiagnosticEvent) -> None:
                    await session.send_event(event)

                session.events_unsub = self.events.subscribe(_forward)
            return
        if msg_type == "disable_events":
            if session.events_unsub is not None:
                session.events_unsub()
                session.events_unsub = None
            session.events_enabled = None
            return
        if msg_type == "confirm_response":
            response = p.ConfirmResponseMessage.model_validate(data)
            await self._handle_confirm_response(session, response)
            return
        if msg_type != "press":
            log.debug("ignoring %s", msg_type)
            return
        await self._dispatch_press(session, data)

    def _injection_blocked(self, what: str) -> bool:
        if not self._deckd_window_focused:
            return False
        log.info("[guard] dropping %r; deckd window focused", what)
        # Issue #70/73: track guard-dropped outcomes so the agent can
        # tell "button pressed but suppressed because the user focused
        # the chrome window" apart from "button pressed and ran". A
        # single recent-actions record per drop keeps the ring-buffer
        # cost bounded.
        self.metrics.record_action("press", "guard_dropped")
        self.recent_actions.add(
            ActionRecord(
                ts=time.time(),
                layout_id=self._current_app_id,
                widget_id=str(what)[:64],
                primitive="press",
                outcome="guard_dropped",
                command_text=None,
                error=None,
            )
        )
        return True

    async def _dispatch_press(self, session: Session, data: dict) -> None:
        press = p.PressMessage.model_validate(data)
        widget = self._find_widget(press.id)
        action_widget_id = press.id
        if widget is None and ":" in press.id:
            base_id, control = press.id.rsplit(":", 1)
            widget = self._find_widget(base_id)
            if widget is not None and control in {"previous", "next", "volume_up", "volume_down"}:
                action_widget_id = control
        if widget is None:
            log.warning("press for unknown widget id=%s", press.id)
            self.metrics.record_action("press", "no_widget")
            self.recent_actions.add(
                ActionRecord(
                    ts=time.time(),
                    layout_id=self._current_app_id,
                    widget_id=press.id,
                    primitive="press",
                    outcome="no_widget",
                    command_text=None,
                    error="unknown widget id",
                )
            )
            return
        ctx = ActionContext(
            send_layout=session.push_current,
            get_current_layout=lambda: self._current_layout,
            current_app=session.app_id,
            key_sink=self.key_sink,
            dbus_bus_factory=self.dbus_bus_factory,
        )
        if action_widget_id in {"previous", "next", "volume_up", "volume_down"}:
            # Media sub-actions are intentionally NEVER gated by
            # ``widget.confirm`` (issue #108): transport is high-frequency
            # / low-stakes and a confirm on "next track" is absurd. The
            # ``confirm`` field itself is rejected on media widgets at
            # load time; this branch is the runtime guard for the
            # ``confirm: true`` on a non-media widget whose transport
            # sub-actions are also obviously not dangerous.
            action = getattr(widget, f"{action_widget_id}_action")
            if action is None:
                self.metrics.record_action("press", "skipped")
                return
            original = widget.action
            widget.action = action
            try:
                await run_action(widget, ctx)
            finally:
                widget.action = original
            return
        # Issue #69 / #108: a ``confirm: true`` press is withheld at
        # the seam BEFORE the action runs AND before any of the
        # recording / event bookkeeping fires (the ring buffer and the
        # ``action`` event both describe a real execution; a withheld
        # press hasn't happened). The handshake (minted token,
        # ``ConfirmRequestMessage``, timeout) lives on
        # ``_handle_confirm_response`` and the timeout task; nothing
        # about the press is recorded here.
        if widget.confirm:
            await self._begin_confirm(session, widget, ctx)
            return
        # Issue #70/73: record every press in the recent-actions ring
        # and bump the action metric. The primitive / outcome fields
        # let ``/actions/recent`` answer "which shell/dbus/key was
        # attempted" without grepping logs.
        await self._run_confirmed_action(session, widget, ctx)

    async def _begin_confirm(
        self, session: Session, widget: "Widget", ctx: ActionContext
    ) -> None:
        """Issue the confirmation request and arm a timeout (issues #69 / #107).

        Side effects on the session:

        - supersedes any existing pending confirm for the same widget
          (cancels the old timeout; the old ``confirm_id`` becomes a
          no-op lookup on any late response);
        - emits a ``confirm{outcome: "requested"}`` diagnostic event
          carrying the new ``confirm_id`` so watchers can correlate the
          round-trip;
        - sends ``ConfirmRequestMessage`` to the originating client.
        """
        confirm_id = secrets.token_urlsafe(12)
        primitive, command_text = _action_primitive(widget.action, widget.macro)
        # Supersession: a second press on the same widget cancels the
        # prior pending token's timeout. The old token's response (if
        # it ever arrives) degrades to an unknown-id no-op, which the
        # response handler turns into silence.
        for old in [
            p for p in session.pending_confirms.values() if p.widget_id == widget.id
        ]:
            old.timeout_task.cancel()
            session.pending_confirms.pop(old.confirm_id, None)
        timeout_task = asyncio.create_task(
            self._confirm_timeout(session, confirm_id, widget.id)
        )
        pending = PendingConfirm(
            confirm_id=confirm_id,
            widget_id=widget.id,
            widget=widget,
            ctx=ctx,
            primitive=primitive,
            command_text=command_text,
            timeout_task=timeout_task,
        )
        session.pending_confirms[confirm_id] = pending
        self._emit_confirm_event(pending, "requested")
        # Best-effort send: a session that drops between the press and
        # the response will be reaped by the disconnect path; the
        # pending task is cancelled and the action never runs.
        with contextlib.suppress(ConnectionResetError, RuntimeError, ConnectionError):
            await session.send(
                p.ConfirmRequestMessage(
                    type="confirm_request",
                    confirm_id=confirm_id,
                    widget_id=widget.id,
                )
            )

    async def _confirm_timeout(
        self, session: Session, confirm_id: str, widget_id: str
    ) -> None:
        """Backstop: drop the pending confirm after ``CONFIRM_TIMEOUT_S``.

        Sleeps in cancellable steps so a ``Task.cancel()`` (from a
        confirm response, supersession, or disconnect) returns control
        promptly instead of waiting out the full timeout. On fire:
        record an ``expired`` ring entry and emit the matching event;
        the action never runs — silence = no dangerous action.
        """
        try:
            await asyncio.sleep(CONFIRM_TIMEOUT_S)
        except asyncio.CancelledError:
            return
        # Look the pending entry up by id; supersession removes it
        # by id (not widget id), so a stale widget_id param can't
        # accidentally hit a freshly-replaced token.
        pending = session.pending_confirms.pop(confirm_id, None)
        if pending is None:
            return
        self._record_confirm_outcome(pending, "expired")

    async def _handle_confirm_response(
        self, session: Session, response: p.ConfirmResponseMessage
    ) -> None:
        """Client answered a ``confirm_request`` (issues #69 / #107).

        Unknown / expired / superseded tokens are a silent no-op — they
        never execute. A matching token cancels its timeout, removes
        itself from the session's pending map, and either runs the
        action (decision ``"confirm"``) or records the cancelled ring
        entry (decision ``"cancel"``). The diagnostic event's outcome
        is ``"confirmed"`` / ``"cancelled"``; only the confirmed path
        also emits the normal ``action`` event.
        """
        pending = session.pending_confirms.pop(response.confirm_id, None)
        if pending is None:
            # Unknown / expired / already-resolved token — silence.
            log.debug("confirm_response for unknown id=%s; dropping", response.confirm_id)
            return
        pending.timeout_task.cancel()
        if response.decision == "confirm":
            # Emit the confirm/confirmed event before running so an
            # event-stream watcher sees the verdict land first; the
            # normal ``action`` event (with ``confirm_id`` tagged)
            # follows from ``_run_confirmed_action``.
            self._emit_confirm_event(pending, "confirmed")
            await self._run_confirmed_action(
                session, pending.widget, pending.ctx, confirm_id=pending.confirm_id
            )
            return
        # decision == "cancel"
        self._record_confirm_outcome(pending, "cancelled")

    def _record_confirm_outcome(self, pending: PendingConfirm, outcome: str) -> None:
        """Ring + event bookkeeping for ``cancelled`` / ``expired``.

        ``confirmed`` is the normal execution record emitted by
        ``_run_confirmed_action`` (with the ``ok`` outcome); the
        confirm/confirmed event is emitted separately by
        ``_handle_confirm_response`` so a watcher sees the verdict
        first. Here we only handle the two outcomes that need a
        distinct ring record (the action never ran, so ``outcome``
        carries the verdict rather than the execution result).
        """
        assert outcome in {"cancelled", "expired"}
        self.recent_actions.add(
            ActionRecord(
                ts=time.time(),
                layout_id=self._current_app_id,
                widget_id=pending.widget_id,
                primitive=pending.primitive,
                outcome=outcome,
                command_text=pending.command_text,
                error=None,
            )
        )
        self._emit_confirm_event(pending, outcome)

    def _emit_confirm_event(self, pending: PendingConfirm, outcome: str) -> None:
        """Fan out one ``confirm`` diagnostic event.

        Every lifecycle point (requested / confirmed / cancelled /
        expired) uses the same wire shape so a watcher can branch on
        ``data.outcome`` alone. The ``confirm_id`` rides along on
        every event so a single round-trip's three lifecycle points
        can be joined in a stream consumer.
        """
        asyncio.create_task(
            self.events.emit(
                DiagnosticEvent(
                    name="confirm",
                    ts=time.time(),
                    data={
                        "outcome": outcome,
                        "widget_id": pending.widget_id,
                        "layout_id": self._current_app_id,
                        "confirm_id": pending.confirm_id,
                    },
                    correlation_id=current_correlation_id(),
                )
            )
        )

    async def _run_confirmed_action(
        self,
        session: Session,
        widget: "Widget",
        ctx: ActionContext,
        *,
        confirm_id: str | None = None,
    ) -> None:
        """The shared "action really runs" path (issues #69 / #107).

        Used directly by ``_dispatch_press`` for non-confirm widgets
        and by ``_handle_confirm_response`` for the confirmed branch.
        Records the ``ok`` ring entry, emits the ``action`` event
        (optionally tagged with ``confirm_id`` for cross-surface
        correlation), runs the action, and forwards the macro result
        to the client when applicable.
        """
        action = widget.action
        macro = widget.macro
        primitive, command_text = _action_primitive(action, macro)
        self.metrics.record_action(primitive, "ok")
        self.recent_actions.add(
            ActionRecord(
                ts=time.time(),
                layout_id=self._current_app_id,
                widget_id=widget.id,
                primitive=primitive,
                outcome="ok",
                command_text=command_text,
                error=None,
            )
        )
        action_event_data: dict[str, object] = {
            "widget_id": widget.id,
            "layout_id": self._current_app_id,
            "primitive": primitive,
        }
        if confirm_id is not None:
            action_event_data["confirm_id"] = confirm_id
        asyncio.create_task(
            self.events.emit(
                DiagnosticEvent(
                    name="action",
                    ts=time.time(),
                    data=action_event_data,
                    correlation_id=current_correlation_id(),
                )
            )
        )
        outcome = await run_action(widget, ctx)
        if isinstance(outcome, MacroOutcome) and outcome.outcome != "ok":
            self.metrics.record_action(primitive, outcome.outcome)
            self.recent_actions.add(
                ActionRecord(
                    ts=time.time(),
                    layout_id=self._current_app_id,
                    widget_id=widget.id,
                    primitive=primitive,
                    outcome=outcome.outcome,
                    command_text=command_text,
                    error=outcome.error,
                )
            )
        if outcome is not None:
            result_msg = p.MacroResultMessage(
                type="macro_result",
                id=widget.id,
                outcome=outcome.outcome,
                failed_step=outcome.failed_step,
                error=outcome.error,
            )
            with contextlib.suppress(ConnectionResetError, RuntimeError, ConnectionError):
                await session.send(result_msg)

    def _find_widget(self, widget_id: str) -> Widget | None:
        for w in self._current_layout.widgets:
            if w.id == widget_id:
                return w
        return None

    async def start(self) -> None:
        from .bind import ResolvedBind, resolve_bind

        # Issue #66: resolve the bind specs into one ``TCPSite`` per
        # address. ``iface:wlan0`` may expand to multiple addresses
        # (one IPv4 + one IPv6 link-local); each becomes its own site
        # so the socket layer is the gate the AC refers to
        # ("An attempt to connect from a non-bound interface is
        # refused at the socket level").
        resolved = resolve_bind(self._bind_specs)
        runner = web.AppRunner(self.app, access_log=None)
        await runner.setup()
        # Open one socket per resolved bind so they all share the
        # same port (kernel-assigned when ``port=0``). ``TCPSite``
        # with the default ``port=0`` lets each site pick its own
        # ephemeral port, which would mean ``/diag`` reports
        # different ports for IPv4 and IPv6 — useless for pairing.
        # Pre-binding the socket ourselves gives us control.
        try:
            server_sockets = _open_bind_sockets(resolved, self.port)
        except OSError as exc:
            await runner.cleanup()
            if exc.errno == errno.EADDRINUSE:
                raise PortInUseError(resolved[0].host, self.port) from exc
            raise
        if not server_sockets:
            await runner.cleanup()
            raise OSError(
                errno.EADDRINUSE,
                f"could not bind any of: {', '.join(self._bind_specs)}:{self.port}",
            )
        # All sockets share the same port (we either used the
        # operator's ``self.port`` literally, or the first socket's
        # kernel-assigned port). ``_open_bind_sockets`` already
        # pulled the port from the first socket.
        actual_port = int(server_sockets[0].getsockname()[1])
        if actual_port != self.port:
            self.port = actual_port
        opened: list[tuple[ResolvedBind, web.TCPSite]] = []
        for sock in server_sockets:
            site = web.SockSite(runner, sock)
            try:
                await site.start()
            except OSError as exc:
                if exc.errno == errno.EADDRINUSE:
                    await runner.cleanup()
                    raise PortInUseError(sock.getsockname()[0], self.port) from exc
                raise
            host, _port, *_ = sock.getsockname()
            # Match back to the originating ``ResolvedBind`` by host
            # so the log line keeps ``iface:wlan0`` semantics.
            bind = _match_resolved(resolved, host)
            opened.append((bind, site))
        self._bind_resolved = opened
        # The log line lists every bound address so operators can
        # see the bind surface at a glance. ``socket.AF_INET6``
        # addresses are bracketed so the URL is unambiguous.
        addresses = ", ".join(
            f"http://{_url_host_for_log(b)}:{self.port}/" for b, _ in opened
        )
        log.info(
            "listening on %s (ws=%s/ws); bind specs: %s",
            addresses,
            _url_host_for_log(opened[0][0]),
            ", ".join(self._bind_specs),
        )
        self._runner = runner
        # Open the MPRIS session bus before the pump task wakes up,
        # so the first iteration's ``row_ids()`` sees live state
        # instead of an empty set. Failure is logged, not raised —
        # the daemon keeps running on a non-MPRIS layout.
        if isinstance(self.mpris, DbusMprisBackend):
            try:
                await self.mpris.start()
            except Exception as exc:
                log.warning("MPRIS backend start failed: %s", exc)
                self.mpris = None
        self.start_layouts_watcher()
        self.start_sensor_pump()
        self.start_media_pump()
        while True:
            await asyncio.sleep(3600)

    async def stop(self) -> None:
        for task in (self._focus_task, self._layouts_task, self._sensor_task, self._media_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        if self.focus_backend is not None:
            try:
                await self.focus_backend.stop()
            except Exception as exc:
                log.debug("focus backend stop failed: %s", exc)
        if self.sensors is not None:
            self.sensors.stop()
        if self.media is not None:
            self.media.stop()
        # Issue #52: tear down the bus connection so we don't keep
        # a session-bus name around after the daemon stops.
        if self.mpris is not None and isinstance(self.mpris, DbusMprisBackend):
            try:
                await self.mpris.stop()
            except Exception as exc:
                log.debug("MPRIS backend stop failed: %s", exc)
        runner = getattr(self, "_runner", None)
        if runner is not None:
            await runner.cleanup()
        await self.scroll.close()
        if self.key_sink is not None:
            self.key_sink.close()
