"""Standalone fixture for ``org.deckd.Focus.ListWindows()`` (issues #120 / #126).

Prints a JSON snapshot of every open window the GNOME Shell extension
would emit if it were running. Lives outside GNOME Shell — exercises
the wire shape and round-trip against the daemon's
:func:`deckd.platform._window_info_from_payload` without the JS hooks.

Two modes:

* ``--once`` (default): one enumeration, exit. Useful for ad-hoc
  spot-checks against a live session.
* The no-arg mode (poll): enumerate at the same ~100ms cadence the
  daemon uses; prints a fresh snapshot whenever the id set changes.

The fixture uses ``xdotool`` / ``wmctrl`` to enumerate windows so it
runs without GNOME Shell installed. The data is intentionally
synthetic-shaped — same envelope as the extension's wire shape, but
without the GTK application id / sandboxed id depth (xdotool can't
see those).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

from deckd.platform import _window_info_from_payload  # noqa: E402  (path mutation above)


async def _xdotool_windows() -> list[dict]:
    """Best-effort xdotool enumeration.

    Returns one entry per top-level window the user owns; uses
    ``xdotool`` because it's the cross-DE escape hatch this fixture
    needs to run in CI without GNOME. A session without ``xdotool``
    produces an empty list — the daemon's watcher treats that as a
    legitimate snapshot (the chrome list simply renders empty until a
    window appears), so a missing tool is a successful no-op rather
    than a fixture failure.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "xdotool",
            "search",
            "--onlyvisible",
            "--screen",
            "root",
            "",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
    except FileNotFoundError:
        return []
    if proc.returncode != 0:
        return []
    ids = [line.strip() for line in stdout.decode().splitlines() if line.strip()]
    entries: list[dict] = []
    for wid in ids:
        wm_class = await _run_xdotool("getwindowclassname", wid) or None
        title = await _run_xdotool("getwindowname", wid) or None
        entries.append(
            {
                "window_id": wid,
                "wm_class": wm_class,
                "gtk_application_id": None,
                "sandboxed_app_id": None,
                "title": title,
                "workspace": 0,
                "minimized": False,
            }
        )
    return entries


async def _run_xdotool(*args: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "xdotool",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
    except FileNotFoundError:
        return ""
    if proc.returncode != 0:
        return ""
    return stdout.decode().strip()


async def emit(*, once: bool, interval_s: float) -> None:
    last: list[str] | None = None
    while True:
        entries = await _xdotool_windows()
        # Round-trip through the daemon's parser so the fixture
        # exercises the same code path a real wire frame lands on;
        # unexpected fields surface here rather than as silent drift
        # in the daemon.
        validated = [_window_info_from_payload(e).__dict__ for e in entries]
        rendered = json.dumps(validated)
        if rendered != last:
            print(rendered, flush=True)
            last = rendered
        if once:
            return
        await asyncio.sleep(interval_s)


def main() -> None:
    parser = argparse.ArgumentParser(prog="list_windows_fixture.py")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=0.1)
    args = parser.parse_args()
    try:
        asyncio.run(emit(once=args.once, interval_s=args.interval))
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()