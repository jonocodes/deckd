from __future__ import annotations

import asyncio
import ast
import json
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True)
class AppInfo:
    app_id: str | None
    wm_class: str | None
    title: str | None = None
    pid: int | None = None

    @property
    def identity(self) -> str:
        return self.app_id or self.wm_class or "unknown"


class PlatformBackend:
    async def get_active_app(self) -> AppInfo:
        raise NotImplementedError

    async def watch_active_app(self, *, interval_s: float = 0.1) -> AsyncIterator[AppInfo]:
        last: AppInfo | None = None
        while True:
            current = await self.get_active_app()
            if current != last:
                last = current
                yield current
            await asyncio.sleep(interval_s)


class GnomeShellFocusBackend(PlatformBackend):
    BUS_NAME = "org.deckd.Focus"
    OBJECT_PATH = "/org/deckd/Focus"
    INTERFACE = "org.deckd.Focus"

    async def get_active_app(self) -> AppInfo:
        out = await _run(
            "gdbus",
            "call",
            "--session",
            "--dest",
            self.BUS_NAME,
            "--object-path",
            self.OBJECT_PATH,
            "--method",
            f"{self.INTERFACE}.GetActiveWindow",
        )
        payload = _parse_single_string_tuple(out)
        data = json.loads(payload)
        return AppInfo(
            app_id=data.get("app_id"),
            wm_class=data.get("wm_class"),
            title=data.get("title"),
            pid=data.get("pid"),
        )


class X11FocusBackend(PlatformBackend):
    async def get_active_app(self) -> AppInfo:
        window_id = (await _run("xdotool", "getactivewindow")).strip()
        wm_class = (await _run("xdotool", "getwindowclassname", window_id)).strip() or None
        title = (await _run("xdotool", "getwindowname", window_id)).strip() or None
        return AppInfo(app_id=None, wm_class=wm_class, title=title)


def default_backend() -> PlatformBackend:
    if sys.platform == "darwin":
        from .platform_macos import MacFocusBackend

        return MacFocusBackend()
    if os.environ.get("XDG_SESSION_TYPE") == "x11":
        return X11FocusBackend()
    return GnomeShellFocusBackend()


async def _run(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        message = stderr.decode().strip() or stdout.decode().strip()
        raise RuntimeError(f"{' '.join(args)} failed: {message}")
    return stdout.decode().strip()


def _parse_single_string_tuple(value: str) -> str:
    parsed = ast.literal_eval(value)
    if not isinstance(parsed, tuple) or len(parsed) != 1 or not isinstance(parsed[0], str):
        raise RuntimeError(f"unexpected gdbus response: {value}")
    return parsed[0]
