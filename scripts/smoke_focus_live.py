#!/usr/bin/env python3
"""Live-bus GNOME focus smoke test (issue #129) — NOT run in CI.

The stage-2 running-windows list silently returned ``[]`` on every real
GNOME session because the extension called ``get_window_actors()`` on the
wrong object (fixed in e166242). No test caught it: every stage-2 test
mocks ``gdbus`` daemon-side (``tests/test_platform.py``,
``tests/test_running_windows_websocket.py``), so the actual extension ↔
session-bus contract is never exercised. This is the missing third leg —
it drives the *production* ``GnomeShellFocusBackend`` over the *live*
session bus and asserts well-formed responses, catching interface /
receiver drift (method on the wrong object, renamed signature, a
silently-empty enumeration) that daemon-side mocks structurally cannot.

Sibling of ``scripts/smoke_mpris_live.py``. Same skip contract: it needs
a GNOME session with the ``deckd-focus@local`` extension installed and
enabled (``org.deckd.Focus`` owned on the session bus). When that name
isn't on the bus — headless, CI, extension not installed — it prints
SKIP and exits 0 rather than failing, so it never gates a PR.

    just smoke-focus     # or: .venv/bin/python scripts/smoke_focus_live.py

Prereq beyond the extension: at least one normal window open (the
terminal running this counts). An empty ``ListWindows`` on a session that
plainly has windows is exactly the e166242 bug, so it's a FAIL, not a
skip.

Exit codes: 0 = passed (or skipped, name not on bus), 1 = the extension
answered but a response was malformed / empty / the wrong shape.
"""
from __future__ import annotations

import asyncio

from deckd.platform import (
    AppInfo,
    GnomeShellFocusBackend,
    RaiseWindowFailed,
    WindowInfo,
    _run,
)

BOGUS_WINDOW_ID = "deckd-smoke-bogus-window-id"


async def _focus_name_owned() -> bool:
    """True iff ``org.deckd.Focus`` is currently owned on the session bus.

    Uses the bus daemon's own ``NameHasOwner`` so a missing ``gdbus``,
    an unreachable bus, or an uninstalled extension all collapse to the
    same "skip" answer rather than a spurious failure."""
    try:
        out = await _run(
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.freedesktop.DBus",
            "--object-path",
            "/org/freedesktop/DBus",
            "--method",
            "org.freedesktop.DBus.NameHasOwner",
            GnomeShellFocusBackend.BUS_NAME,
        )
    except Exception:
        return False
    return "true" in out


async def _run_checks(backend: GnomeShellFocusBackend) -> list[str]:
    failures: list[str] = []

    # GetActiveWindow -> a parseable AppInfo. The parse itself is the
    # contract check: a renamed key or a non-JSON reply raises here.
    active = await backend.get_active_app()
    print(f"GetActiveWindow -> {active}")
    if not isinstance(active, AppInfo):
        failures.append(f"GetActiveWindow returned {type(active).__name__}, not AppInfo")

    # ListWindows -> a non-empty list of well-formed WindowInfo. Non-empty
    # is the e166242 guard: a session with windows open must enumerate at
    # least one. Each entry needs a non-empty window_id (the id the raise
    # path keys on) — that's the shape the chrome list depends on.
    windows = await backend._list_windows_once()
    print(f"ListWindows -> {len(windows)} window(s)")
    if not windows:
        failures.append(
            "ListWindows returned []; on a session with windows open this is "
            "the e166242 receiver bug (open at least one normal window and retry)"
        )
    for i, win in enumerate(windows):
        if not isinstance(win, WindowInfo):
            failures.append(f"ListWindows[{i}] is {type(win).__name__}, not WindowInfo")
        elif not win.window_id:
            failures.append(f"ListWindows[{i}] has an empty window_id ({win!r})")

    # RaiseWindow(bogus) -> false, surfaced as RaiseWindowFailed. This is
    # the #127 verification bullet that went unmet: a bogus id must be
    # declined, not silently accepted.
    try:
        await backend.raise_window(BOGUS_WINDOW_ID)
    except RaiseWindowFailed as exc:
        print(f"RaiseWindow({BOGUS_WINDOW_ID!r}) -> declined (RaiseWindowFailed: {exc.window_id!r}) ✓")
    else:
        failures.append(
            f"RaiseWindow({BOGUS_WINDOW_ID!r}) returned true for a bogus id "
            "(expected false / RaiseWindowFailed)"
        )

    return failures


async def _main() -> int:
    if not await _focus_name_owned():
        print(
            f"SKIP: {GnomeShellFocusBackend.BUS_NAME} is not owned on the session "
            "bus. Run on a GNOME session with the deckd-focus@local extension "
            "enabled (`just install-focus-extension`)."
        )
        return 0

    backend = GnomeShellFocusBackend()
    failures = await _run_checks(backend)
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: live org.deckd.Focus answered GetActiveWindow / ListWindows / "
          "RaiseWindow with well-formed responses")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
