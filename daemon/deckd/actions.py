from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .layouts import Action, Widget

if TYPE_CHECKING:
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


async def run_terminal(target: bool | str = True) -> None:
    if isinstance(target, str):
        cmd = target
        if not shutil.which(cmd.split()[0]):
            log.warning("[terminal] %r not on $PATH", cmd)
            return
        await _run_shell(f"{cmd} &")
        return
    if target is True:
        cmd = _resolve_terminal()
        if cmd is None:
            log.warning("[terminal] no terminal emulator found; set $TERMINAL")
            return
        await _run_shell(f"{cmd} &")


@dataclass
class ActionContext:
    """Per-connection helpers the dispatcher needs."""

    send_layout: "callable"
    get_current_layout: "callable"
    current_app: str
    key_sink: "KeySink | None" = None


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
        log.warning("[dbus stub] widget=%s target=%s — dbus dispatch not wired up yet",
                    widget.id, action.dbus)
    else:
        log.warning("widget %s action has no recognised primitive: %s",
                    widget.id, action)


async def _run_shell(command: str) -> None:
    log.info("[shell] %s", command)
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        log.error("[shell] failed to start %r: %s", command, exc)
        return
    rc = await proc.wait()
    if rc != 0:
        log.warning("[shell] %s exited rc=%s", command, rc)


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
