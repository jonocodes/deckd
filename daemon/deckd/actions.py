from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass

from .layouts import Action, Widget

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


async def execute(
    widget: Widget,
    ctx: ActionContext,
    *,
    on_page_change: "callable | None" = None,
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
        log.info("[key stub] widget=%s keysym=%s — uinput not wired up yet",
                 widget.id, action.key)
    elif action.dbus is not None:
        log.warning("[dbus stub] widget=%s target=%s — dbus dispatch not wired up yet",
                    widget.id, action.dbus)
    elif action.page is not None:
        if on_page_change is not None:
            await on_page_change(action.page)
        else:
            log.warning("[page] widget=%s page=%s — no on_page_change wired",
                        widget.id, action.page)
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
