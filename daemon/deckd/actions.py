from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from .layouts import Action, Macro, MacroStep, Widget

if TYPE_CHECKING:
    from dbus_fast import BusType as BusTypeT
    from dbus_fast.aio import MessageBus

    from .input import KeySink
    from .layouts import Layout

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

    send_layout: "Callable[[], Awaitable[None]]"
    get_current_layout: "Callable[[], Layout]"
    current_app: str
    key_sink: "KeySink | None" = None
    dbus_bus_factory: "Callable[[BusTypeT], MessageBus] | None" = None
    focus_backend: Any = None


async def execute(
    widget: Widget,
    ctx: ActionContext,
) -> MacroOutcome | None:
    if widget.macro is not None:
        return await execute_macro(widget.macro, ctx)
    action = widget.action
    if action is None:
        log.debug("widget %s has no action; ignoring", widget.id)
        return None
    if action.shell is not None:
        await _run_shell(action.shell)
    elif action.terminal is not None:
        await run_terminal(action.terminal)
    elif action.key is not None:
        await _dispatch_key(action.key, ctx)
    elif action.dbus is not None:
        await _dispatch_dbus(action.dbus, ctx, widget_id=widget.id)
    elif action.raise_ is not None:
        await _dispatch_raise(action.raise_, ctx, widget_id=widget.id)
    elif action.url is not None:
        await _dispatch_url(action.url)
    elif action.text is not None:
        await _dispatch_text(action, ctx)
    else:
        log.warning("widget %s action has no recognised primitive: %s",
                    widget.id, action)
    return None


async def _dispatch_raise(identity: str, ctx: ActionContext, *, widget_id: str) -> None:
    backend = ctx.focus_backend
    if backend is None or "raise_app" not in backend.capabilities():
        log.info("[raise] unsupported backend (identity=%r, widget=%s)", identity, widget_id)
        return
    try:
        raised = await backend.raise_app(identity)
    except Exception as exc:
        log.warning("[raise] %r failed (widget=%s): %s", identity, widget_id, exc)
        return
    if not raised:
        log.info("[raise] no running window matched %r (widget=%s)", identity, widget_id)


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


# ---------------------------------------------------------------------------
# URL action dispatch
# ---------------------------------------------------------------------------

_URL_OPENERS_LINUX: list[tuple[str, ...]] = [
    ("xdg-open",),
    ("gio", "open"),
]
_URL_OPENERS_MACOS: list[tuple[str, ...]] = [
    ("open",),
]


def _resolve_url_opener() -> tuple[str, ...] | None:
    import sys

    candidates = _URL_OPENERS_MACOS if sys.platform == "darwin" else _URL_OPENERS_LINUX
    for cmd in candidates:
        if shutil.which(cmd[0]):
            return cmd
    return None


async def _dispatch_url(url: str) -> None:
    cmd = _resolve_url_opener()
    if cmd is None:
        log.warning("[url] no URL opener found; install xdg-utils or libglib2-bin")
        return
    log.info("[url] %s %s", cmd[0], url)
    try:
        await asyncio.create_subprocess_exec(
            *cmd, url,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        log.error("[url] failed to start %r %r: %s", cmd, url, exc)


# ---------------------------------------------------------------------------
# Text action dispatch
# ---------------------------------------------------------------------------


def _clipboard_read_args(tool: str) -> list[str]:
    import sys

    if sys.platform == "darwin":
        return [tool]
    if "xclip" in tool:
        return [tool, "-o", "-selection", "clipboard"]
    if "xsel" in tool:
        return [tool, "-b"]
    return [tool]


def _clipboard_write_args(tool: str) -> list[str]:
    import sys

    if sys.platform == "darwin":
        return [tool]
    if "xclip" in tool:
        return [tool, "-selection", "clipboard"]
    if "xsel" in tool:
        return [tool, "-b"]
    return [tool]


def _detect_clipboard_tools() -> tuple[str | None, str | None]:
    import sys

    if sys.platform == "darwin":
        return ("pbcopy", "pbpaste")
    copy_tool = shutil.which("wl-copy")
    paste_tool = None
    if copy_tool is not None:
        paste_tool = shutil.which("wl-paste")
    else:
        copy_tool = shutil.which("xclip")
        paste_tool = shutil.which("xclip")
        if copy_tool is None:
            copy_tool = shutil.which("xsel")
            paste_tool = shutil.which("xsel")
    return (copy_tool, paste_tool)


def _text_needs_paste_fallback(text: str, forced_mode: str | None) -> bool:
    if forced_mode == "simulate":
        return False
    if forced_mode == "paste":
        return True
    from .input import text_to_combos

    expected = len(text)
    combos = text_to_combos(text)
    if len(combos) < expected:
        return True
    return False


async def _dispatch_text(action: "Action", ctx: ActionContext) -> None:
    text = action.text
    if text is None or text == "":
        return

    mode = action.text_mode or "simulate"
    needs_fallback = _text_needs_paste_fallback(text, action.text_mode)
    if needs_fallback and mode == "simulate":
        log.warning("[text] string contains characters not mappable to keycodes; "
                     "falling back to paste mode")
        mode = "paste"

    if mode == "simulate":
        await _text_simulate(text, ctx)
    else:
        await _text_paste(text, ctx, action.restore_clipboard, action.restore_clipboard_delay_ms)


async def _text_simulate(text: str, ctx: ActionContext) -> None:
    from .input import text_to_combos

    combos = text_to_combos(text)
    sink = ctx.key_sink
    if sink is None:
        log.info("[text log] text=%r (no sink wired)", text)
        return
    for combo in combos:
        sink.emit_key(combo)
    log.info("[text simulate] %d chars", len(combos))


async def _text_paste(text: str, ctx: ActionContext, restore_clipboard: bool,
                       restore_delay_ms: int = 1000) -> None:
    copy_tool, paste_tool = _detect_clipboard_tools()
    if copy_tool is None:
        log.warning("[text paste] no clipboard tool found; falling back to simulate")
        await _text_simulate(text, ctx)
        return

    previous: str | None = None
    if restore_clipboard and paste_tool is not None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *_clipboard_read_args(paste_tool),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if proc.stdout is not None:
                stdout, _ = await proc.communicate()
                previous = stdout.decode("utf-8", errors="replace")
        except Exception as exc:
            log.warning("[text paste] failed to read clipboard: %s", exc)

    try:
        proc = await asyncio.create_subprocess_exec(
            *_clipboard_write_args(copy_tool),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if proc.stdin is not None:
            proc.stdin.write(text.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
            await proc.wait()
    except Exception as exc:
        log.warning("[text paste] failed to write clipboard: %s", exc)
        return

    sink = ctx.key_sink
    if sink is not None:
        from .input import parse_key_combo

        ctrlv = parse_key_combo("ctrl+v")
        sink.emit_key(ctrlv)
        log.info("[text paste] pasted %d chars via ctrl+v", len(text))
    else:
        log.info("[text paste log] text=%r (no sink wired)", text)

    if restore_clipboard and previous is not None and paste_tool is not None:
        await asyncio.sleep(restore_delay_ms / 1000.0)
        try:
            proc = await asyncio.create_subprocess_exec(
                *_clipboard_write_args(copy_tool),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            if proc.stdin is not None:
                proc.stdin.write(previous.encode("utf-8"))
                await proc.stdin.drain()
                proc.stdin.close()
                await proc.wait()
        except Exception as exc:
            log.warning("[text paste] failed to restore clipboard: %s", exc)


# ---------------------------------------------------------------------------
# Macro execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MacroOutcome:
    outcome: Literal["ok", "failed-at-step"]
    failed_step: int | None = None
    error: str | None = None


async def execute_macro(macro: Macro, ctx: ActionContext) -> MacroOutcome:
    steps = macro.steps
    for i, step in enumerate(steps):
        try:
            await _run_step(step, ctx)
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            log.warning("macro step %d failed: %s", i, err)
            if macro.continue_on_error:
                continue
            return MacroOutcome("failed-at-step", i, err)
    return MacroOutcome("ok")


_StepFunc = Callable[[MacroStep, ActionContext], Awaitable[None]]


_STEP_DISPATCH: dict[str, _StepFunc] = {}


def _register(kind: str) -> Callable[[_StepFunc], _StepFunc]:
    def decorator(func: _StepFunc) -> _StepFunc:
        _STEP_DISPATCH[kind] = func
        return func
    return decorator


async def _run_step(step: MacroStep, ctx: ActionContext) -> None:
    handler = _STEP_DISPATCH.get(step.type)
    if handler is None:
        raise ValueError(f"unknown macro step type: {step.type!r}")
    await handler(step, ctx)


@_register("delay")
async def _step_delay(step: MacroStep, _ctx: ActionContext) -> None:
    try:
        ms = int(step.value)
    except ValueError:
        raise ValueError(f"invalid delay value: {step.value!r}, expected milliseconds as integer") from None
    if ms < 0:
        raise ValueError(f"delay must be non-negative, got {ms}")
    await asyncio.sleep(ms / 1000)


@_register("shell")
async def _step_shell(step: MacroStep, _ctx: ActionContext) -> None:
    log.info("[macro shell] %s", step.value)
    await asyncio.create_subprocess_shell(
        step.value,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )


@_register("key")
async def _step_key(step: MacroStep, ctx: ActionContext) -> None:
    from .input import parse_key_combo

    keycodes = parse_key_combo(step.value)
    if not keycodes:
        raise ValueError(f"key value {step.value!r} parsed to empty keycode list")
    sink = ctx.key_sink
    if sink is not None:
        sink.emit_key(keycodes)
        log.info("[macro key] keycodes=%s", keycodes)
    else:
        log.info("[macro key log] keycodes=%s (no sink wired)", keycodes)


@_register("dbus")
async def _step_dbus(step: MacroStep, ctx: ActionContext) -> None:
    factory = ctx.dbus_bus_factory
    if factory is None:
        raise RuntimeError("no D-Bus bus factory wired")
    parsed = _parse_dbus_action(step.value)
    bus = factory(parsed.bus_type)
    try:
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
            raise RuntimeError(
                f"D-Bus {parsed.interface}.{parsed.method} on "
                f"{parsed.destination} returned error: {reply.body}"
            )
        log.info(
            "[macro dbus] %s.%s on %s@%s args=%s",
            parsed.interface,
            parsed.method,
            parsed.destination,
            parsed.path,
            parsed.args,
        )
    finally:
        try:
            bus.disconnect()
        except Exception as exc:
            log.debug("[macro dbus] disconnect error: %s", exc)


@_register("url")
async def _step_url(step: MacroStep, _ctx: ActionContext) -> None:
    await _dispatch_url(step.value)


@_register("text")
async def _step_text(step: MacroStep, ctx: ActionContext) -> None:
    from .layouts import Action
    a = Action(text=step.value, text_mode=None, restore_clipboard=True,
               restore_clipboard_delay_ms=1000)
    await _dispatch_text(a, ctx)
