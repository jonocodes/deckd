from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .layouts import Action, Widget

if TYPE_CHECKING:
    from dbus_fast import BusType as BusTypeT
    from dbus_fast.aio import MessageBus

    from .input import KeySink

log = logging.getLogger("deckd.actions")


TERMINAL_CANDIDATES = ("foot", "kitty", "gnome-terminal", "konsole", "alacritty")


def _resolve_terminal() -> str | None:
    env = os.environ.get("TERMINAL")
    if env and shutil.which(env):
        return env
    for cand in TERMINAL_CANDIDATES:
        if shutil.which(cand):
            return cand
    return None


async def run_terminal(target: bool = True) -> None:
    """Open the auto-detected terminal emulator.

    Only ``terminal: true`` is meaningful; a specific program should be
    launched with a ``shell:`` action instead (the layout schema rejects a
    string ``terminal`` value at load time). ``target`` is anything other
    than ``True`` is a no-op.
    """
    if target is not True:
        return
    cmd = _resolve_terminal()
    if cmd is None:
        log.warning("[terminal] no terminal emulator found; set $TERMINAL")
        return
    await _run_shell(cmd)


@dataclass
class ActionContext:
    """Per-connection helpers the dispatcher needs."""

    send_layout: "callable"
    get_current_layout: "callable"
    current_app: str
    key_sink: "KeySink | None" = None
    dbus_bus_factory: "Callable[[BusTypeT], MessageBus] | None" = None


async def execute(
    widget: Widget,
    ctx: ActionContext,
) -> None:
    action = widget.action
    if action is None:
        log.debug("widget %s has no action; ignoring", widget.id)
        return
    if action.shell is not None:
        await _run_shell(action.shell)
    elif action.terminal is not None:
        await run_terminal(action.terminal)
    elif action.key is not None:
        await _dispatch_key(action.key, ctx)
    elif action.dbus is not None:
        await _dispatch_dbus(action.dbus, ctx, widget_id=widget.id)
    else:
        log.warning("widget %s action has no recognised primitive: %s",
                    widget.id, action)


async def _run_shell(command: str) -> None:
    """Launch ``command`` via the shell, detached and fire-and-forget.

    A button press must return immediately whether it launched a GUI app or
    a one-shot command, so we do NOT wait for the child to exit. stdin/stdout/
    stderr are discarded and the child runs in its own session (``setsid``) so
    it outlives the daemon and isn't tied to the daemon's process group. The
    trade-off is that a non-zero exit is not observable — that's inherent to
    fire-and-forget; use it to launch things, not to run commands you need the
    result of.
    """
    log.info("[shell] %s", command)
    try:
        await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        log.error("[shell] failed to start %r: %s", command, exc)


async def _dispatch_key(key_string: str, ctx: ActionContext) -> None:
    from .input import parse_key_combo

    keycodes = parse_key_combo(key_string)
    if not keycodes:
        log.warning("[key] widget key=%r parsed to empty keycode list", key_string)
        return

    sink = ctx.key_sink
    if sink is not None:
        sink.emit_key(keycodes)
        log.info("[key] keycodes=%s", keycodes)
    else:
        log.info("[key log] keycodes=%s (no sink wired)", keycodes)


# ---------------------------------------------------------------------------
# D-Bus action dispatch
# ---------------------------------------------------------------------------


SYSTEM_BUS_INTERFACE_PREFIXES = (
    "org.freedesktop.login1.",
    "org.freedesktop.systemd1.",
    "org.freedesktop.timedate1.",
    "org.freedesktop.locale1.",
    "org.freedesktop.machine1.",
    "org.freedesktop.hostname1.",
    "org.freedesktop.import1.",
    "org.freedesktop.portable1.",
    "org.freedesktop.resolve1.",
)


@dataclass(frozen=True)
class ParsedDbusCall:
    destination: str
    path: str
    interface: str
    method: str
    args: list[str]
    bus_type: "BusTypeT"


def _infer_bus_type(interface: str) -> "BusTypeT":
    from dbus_fast import BusType

    if any(interface.startswith(p) for p in SYSTEM_BUS_INTERFACE_PREFIXES):
        return BusType.SYSTEM
    return BusType.SESSION


def _default_destination_and_path(interface: str) -> tuple[str, str]:
    """Infer destination + path from a dotted interface name.

    For ``org.freedesktop.login1.Manager`` the destination is
    ``org.freedesktop.login1`` and the path is ``/org/freedesktop/login1``.
    Falls back to the full interface for both if the name has fewer than three
    segments.
    """
    parts = interface.split(".")
    if len(parts) >= 3:
        destination = ".".join(parts[:2])
        path = "/" + "/".join(parts[:2])
    else:
        destination = interface
        path = "/" + interface.replace(".", "/")
    return destination, path


def _parse_dbus_action(value: str) -> ParsedDbusCall:
    """Parse a ``dbus:`` action string into a structured call.

    Accepted forms::

        "service:path org.Interface.Method arg1 arg2"
        "org.Interface.Method arg1 arg2"

    When ``service:path`` is omitted, the destination and path are inferred
    from the first segments of the interface name (first two segments form
    the destination; the same two joined with ``/`` form the path). The bus
    is inferred from the interface name (systemd-style interfaces map to the
    system bus; everything else defaults to the session bus).
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("dbus action value is empty")

    head, _, tail = stripped.partition(" ")
    tokens = tail.split()
    if not tokens:
        raise ValueError(f"dbus action {value!r} has no method tokens")

    method_token = tokens[0]
    args = tokens[1:]

    if "." not in method_token:
        raise ValueError(
            f"dbus action {value!r}: method token {method_token!r} is not a "
            f"fully-qualified 'org.Interface.Method'"
        )

    if ":" in head:
        destination, _, path = head.partition(":")
    else:
        destination = ""
        path = ""

    interface, _, method = method_token.rpartition(".")
    if not interface:
        raise ValueError(
            f"dbus action {value!r}: cannot derive interface from {method_token!r}"
        )

    if not destination or not path:
        destination, path = _default_destination_and_path(interface)

    bus_type = _infer_bus_type(interface)
    return ParsedDbusCall(
        destination=destination,
        path=path,
        interface=interface,
        method=method,
        args=args,
        bus_type=bus_type,
    )


async def _dispatch_dbus(
    value: str,
    ctx: ActionContext,
    *,
    widget_id: str | None = None,
) -> None:
    """Parse and dispatch a ``dbus:`` action.

    All errors (parse failure, connection failure, reply error) are caught
    and logged. They never propagate back to the client.
    """
    factory = ctx.dbus_bus_factory
    if factory is None:
        log.warning("[dbus] no bus factory wired (widget=%s); skipping", widget_id)
        return

    try:
        parsed = _parse_dbus_action(value)
    except ValueError as exc:
        log.warning("[dbus] %s (widget=%s)", exc, widget_id)
        return

    bus = None
    try:
        bus = factory(parsed.bus_type)
        await bus.connect()
        from dbus_fast.message import Message

        reply = await bus.call(
            Message(
                destination=parsed.destination,
                path=parsed.path,
                interface=parsed.interface,
                member=parsed.method,
                body=parsed.args or [],
            )
        )
        from dbus_fast import MessageType

        if reply is not None and reply.message_type == MessageType.ERROR:
            log.warning(
                "[dbus] %s.%s on %s returned error: %s",
                parsed.interface,
                parsed.method,
                parsed.destination,
                reply.body,
            )
        else:
            log.info(
                "[dbus] %s.%s on %s@%s args=%s",
                parsed.interface,
                parsed.method,
                parsed.destination,
                parsed.path,
                parsed.args,
            )
    except Exception as exc:
        log.warning(
            "[dbus] %s.%s on %s failed: %s (widget=%s)",
            parsed.interface,
            parsed.method,
            parsed.destination,
            exc,
            widget_id,
        )
    finally:
        if bus is not None:
            try:
                bus.disconnect()
            except Exception as exc:
                log.debug("[dbus] disconnect error: %s", exc)

