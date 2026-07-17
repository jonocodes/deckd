from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import socket
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from aiohttp import WSMsgType, web

from . import protocol as p
from .actions import ActionContext, execute as run_action
from .input import ScrollController
from .layouts import Layout, LayoutStore, load_layouts, resolve_layout

if TYPE_CHECKING:
    from dbus_fast import BusType as BusTypeT
    from dbus_fast.aio import MessageBus

    from .input import KeySink
    from .platform import AppInfo, PlatformBackend

log = logging.getLogger("deckd.server")

DEFAULT_APP_ID = "default"


# ---------------------------------------------------------------------------
# Host-identity helpers used by /health. Cheap to compute per-request; no
# caching needed. Broken out so the tests can pin them via monkeypatch.
# ---------------------------------------------------------------------------


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


class Session:
    """Per-WebSocket-connection state."""

    def __init__(self, ws: web.WebSocketResponse, server: "Server") -> None:
        self.ws = ws
        self.server = server

    @property
    def app_id(self) -> str:
        return self.server.current_app_id

    async def send(self, message: p.ServerMessage) -> None:
        await self.ws.send_json(message.model_dump())

    async def push_current(self) -> None:
        layout = self.server.current_layout
        error = self.server.current_error
        if error is not None:
            # Bad on-disk config: send widgets=[] plus the error text so the
            # client swaps the grid for a diagnostic message.
            msg = p.LayoutMessage(
                type="layout",
                app=self.server.current_app_id,
                widgets=[],
                jogstrip_enabled=layout.jogstrip,
                error=error,
            )
        else:
            widgets = [w.model_dump() for w in layout.widgets]
            msg = p.LayoutMessage(
                type="layout",
                app=self.server.current_app_id,
                widgets=widgets,
                jogstrip_enabled=layout.jogstrip,
            )
        await self.send(msg)


class Server:
    def __init__(
        self,
        *,
        layouts_dir: Path,
        host: str,
        port: int,
        scroll: ScrollController | None = None,
        key_sink: "KeySink | None" = None,
        dbus_bus_factory: "Callable[[BusTypeT], MessageBus] | None" = None,
        focus_backend: "PlatformBackend | None" = None,
    ) -> None:
        self.layouts_dir = layouts_dir
        self.host = host
        self.port = port
        self.app = web.Application()
        self._setup_routes()
        self._sessions: set[Session] = set()
        self.layouts: LayoutStore = load_layouts(layouts_dir)
        self._current_app_id: str = DEFAULT_APP_ID
        self._current_layout: Layout = self.layouts.default()
        self.scroll = scroll if scroll is not None else ScrollController()
        self.key_sink = key_sink
        self.dbus_bus_factory = dbus_bus_factory
        self.focus_backend = focus_backend
        self._focus_task: asyncio.Task[None] | None = None
        self._layouts_task: asyncio.Task[None] | None = None
        self._current_error: str | None = None

    # -- layout state --------------------------------------------------------

    @property
    def current_layout(self) -> Layout:
        return self._current_layout

    @property
    def current_app_id(self) -> str:
        return self._current_app_id

    @property
    def current_error(self) -> str | None:
        return self._current_error

    def reload_layouts(self) -> None:
        """Re-read every layout YAML in ``layouts_dir``.

        On success: rebuild the store, keep the current app_id if it still
        resolves, else fall back to default, and clear any prior error.

        On failure (bad YAML, schema violation): keep the previous store and
        current layout intact, but record the error on ``current_error`` so
        the next push tells the client to render an error state instead of
        the grid. Callers should not have to catch anything.
        """
        try:
            new_store = load_layouts(self.layouts_dir)
        except SystemExit as exc:
            self._current_error = str(exc)
            log.error("layout reload failed (keeping last-good): %s", exc)
            return
        self.layouts = new_store
        try:
            new_layout = self.layouts[self._current_app_id]
        except KeyError:
            self._current_app_id = DEFAULT_APP_ID
            new_layout = self.layouts.default()
        self._current_layout = new_layout
        self._current_error = None
        log.info("reloaded layouts from %s", self.layouts_dir)

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
        page-title fallback ("deckd") covers browsers whose window title
        is only the page's ``<title>``.
        """
        title = app.title or ""
        port = self.port
        if port and port > 0 and str(port) in title:
            return True
        return "deckd" in title.lower()

    async def _on_focus(self, app: "AppInfo") -> None:
        if self._is_deckd_window(app):
            log.debug("holding layout; deckd client window focused (%s)", app)
            return
        # A genuine (non-deckd) focus change re-resolves the layout, so a
        # `deckctl layout` override never sticks past the next real switch.
        new_layout = resolve_layout(self.layouts, app)
        new_app_id = new_layout.id
        if new_app_id == self._current_app_id and new_layout is self._current_layout:
            return
        log.info("focus -> %s (layout=%s)", app, new_app_id)
        self._current_app_id = new_app_id
        self._current_layout = new_layout
        await self._push_to_all()

    async def run_focus_watcher(self) -> None:
        """Long-running task: react to focus changes from the backend.

        Reads the initial focus before entering the loop so the daemon
        starts with the correct layout instead of ``default``. Errors
        from the backend on any single iteration are logged but do not
        stop the watcher.
        """
        if self.focus_backend is None:
            return
        backend = self.focus_backend
        try:
            initial = await backend.get_active_app()
        except Exception as exc:
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
        directory is created, edited, or removed.

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
        yaml_suffixes = {".yaml", ".yml"}
        async for changes in awatch(self.layouts_dir):
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

    # -- routes / lifecycle --------------------------------------------------

    def _setup_routes(self) -> None:
        self.app.router.add_get("/ws", self._ws_handler)
        self.app.router.add_get("/health", self._health)
        self.app.router.add_post("/reload", self._reload)
        self.app.router.add_post("/layout/{layout_id}", self._set_layout)

    async def _health(self, _req: web.Request) -> web.Response:
        # The web client fetches /health from the Settings panel to read
        # host identity. On the Vite dev path (:5173 -> :8765) that fetch
        # is cross-origin, so the browser needs an explicit allow header
        # or it drops the response. A local dev tool with no auth has
        # nothing to protect by cornering the origin, so ``*`` is fine.
        return web.json_response(
            {
                "ok": True,
                "sessions": len(self._sessions),
                "app": self._current_app_id,
                "hostname": _hostname(),
                "os": _os_pretty(),
                "desktop": _desktop_env(),
            },
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def _reload(self, _req: web.Request) -> web.Response:
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

    async def _apply_layout_override(self, layout_id: str, layout: Layout) -> None:
        """Force every connected client to ``layout`` (addressed by ``layout_id``).

        Bypasses focus detection entirely. The override is not sticky: the
        next genuine (non-deckd-window) focus change re-resolves the layout
        and switches as normal.
        """
        self._current_app_id = layout_id
        self._current_layout = layout
        log.info("layout override -> %s", layout_id)
        await self._push_to_all()

    async def _ws_handler(self, req: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(req)
        session = Session(ws, self)
        self._sessions.add(session)
        log.info(
            "client connected (%d, app=%s)", len(self._sessions), self._current_app_id
        )
        try:
            await session.push_current()
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
            log.info("client disconnected (%d remaining)", len(self._sessions))
        return ws

    async def _dispatch(self, session: Session, data: dict) -> None:
        msg_type = data.get("type")
        if msg_type == "hello":
            log.info("client hello (token=%s)", bool(data.get("token")))
            return
        if msg_type == "jog":
            msg = p.JogMessage.model_validate(data)
            self.scroll.jog(msg.id, msg.delta)
            return
        if msg_type == "jog_end":
            msg = p.JogEndMessage.model_validate(data)
            self.scroll.jog_end(msg.id, msg.velocity)
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
        if msg_type != "press":
            log.debug("ignoring %s", msg_type)
            return
        msg = p.PressMessage.model_validate(data)
        widget = self._find_widget(msg.id)
        if widget is None:
            log.warning("press for unknown widget id=%s", msg.id)
            return
        ctx = ActionContext(
            send_layout=session.push_current,
            get_current_layout=lambda: self._current_layout,
            current_app=session.app_id,
            key_sink=self.key_sink,
            dbus_bus_factory=self.dbus_bus_factory,
        )
        await run_action(widget, ctx)

    def _find_widget(self, widget_id: str) -> Widget | None:
        for w in self._current_layout.widgets:
            if w.id == widget_id:
                return w
        return None

    async def start(self) -> None:
        runner = web.AppRunner(self.app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        log.info("listening on http://%s:%d (ws=%s/ws)", self.host, self.port, self.host)
        self._runner = runner
        self.start_layouts_watcher()
        while True:
            await asyncio.sleep(3600)

    async def stop(self) -> None:
        for task in (self._focus_task, self._layouts_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        runner = getattr(self, "_runner", None)
        if runner is not None:
            await runner.cleanup()
        await self.scroll.close()
        if self.key_sink is not None:
            self.key_sink.close()
