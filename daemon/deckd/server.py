from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from aiohttp import WSMsgType, web

from . import protocol as p
from .actions import ActionContext, execute as run_action
from .input import ScrollController
from .layouts import Layout, Widget, load_layout

if TYPE_CHECKING:
    from dbus_fast import BusType as BusTypeT
    from dbus_fast.aio import MessageBus

    from .input import KeySink

log = logging.getLogger("deckd.server")


class Session:
    """Per-WebSocket-connection state."""

    def __init__(self, ws: web.WebSocketResponse, server: "Server") -> None:
        self.ws = ws
        self.server = server
        self.app_id = "default"

    async def send(self, message: p.ServerMessage) -> None:
        await self.ws.send_json(message.model_dump())

    async def push_current(self) -> None:
        layout = self.server.layout_for(self.app_id)
        widgets = [w.model_dump() for w in layout.widgets]
        msg = p.LayoutMessage(type="layout", app=self.app_id, widgets=widgets)
        await self.send(msg)


class Server:
    def __init__(
        self,
        *,
        layouts_path: Path,
        host: str,
        port: int,
        scroll: ScrollController | None = None,
        key_sink: "KeySink | None" = None,
        dbus_bus_factory: "Callable[[BusTypeT], MessageBus] | None" = None,
    ) -> None:
        self.layouts_path = layouts_path
        self.host = host
        self.port = port
        self.app = web.Application()
        self._setup_routes()
        self._sessions: set[Session] = set()
        self.layout: Layout = load_layout(layouts_path)
        self.scroll = scroll if scroll is not None else ScrollController()
        self.key_sink = key_sink
        self.dbus_bus_factory = dbus_bus_factory

    def reload_layout(self) -> None:
        self.layout = load_layout(self.layouts_path)
        log.info("reloaded layout from %s", self.layouts_path)

    async def reload_and_push(self) -> None:
        self.reload_layout()
        for session in list(self._sessions):
            try:
                await session.push_current()
            except ConnectionResetError:
                pass

    def layout_for(self, app_id: str) -> Layout:
        return self.layout

    def _setup_routes(self) -> None:
        self.app.router.add_get("/ws", self._ws_handler)
        self.app.router.add_get("/health", self._health)
        self.app.router.add_post("/reload", self._reload)

    async def _health(self, _req: web.Request) -> web.Response:
        return web.json_response({"ok": True, "sessions": len(self._sessions)})

    async def _reload(self, _req: web.Request) -> web.Response:
        try:
            await self.reload_and_push()
        except SystemExit as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "sessions": len(self._sessions)})

    async def _ws_handler(self, req: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(req)
        session = Session(ws, self)
        self._sessions.add(session)
        log.info("client connected (%d)", len(self._sessions))
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
        if msg_type != "press":
            log.debug("ignoring %s in spike", msg_type)
            return
        msg = p.PressMessage.model_validate(data)
        widget = self._find_widget(msg.id)
        if widget is None:
            log.warning("press for unknown widget id=%s", msg.id)
            return
        ctx = ActionContext(
            send_layout=session.push_current,
            get_current_layout=lambda: self.layout,
            current_app=session.app_id,
            key_sink=self.key_sink,
            dbus_bus_factory=self.dbus_bus_factory,
        )
        await run_action(widget, ctx)

    def _find_widget(self, widget_id: str) -> Widget | None:
        for w in self.layout.widgets:
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
        while True:
            await asyncio.sleep(3600)

    async def stop(self) -> None:
        runner = getattr(self, "_runner", None)
        if runner is not None:
            await runner.cleanup()
        await self.scroll.close()
        if self.key_sink is not None:
            self.key_sink.close()
