#!/usr/bin/env python3
"""Live-bus MPRIS smoke test (issue #52) — NOT run in CI.

Answers the question the hermetic e2e can't: does the *real*
``DbusMprisBackend`` pick up a *real* MPRIS player over a *real* session
bus? It publishes a minimal but conformant ``org.mpris.MediaPlayer2.*``
service (the same surface a media player like VLC or a browser exports),
then drives the production backend against the live bus and asserts the
player shows up as a playing row with the right metadata.

Why it lives here and not in ``tests/``: it needs a session bus
(``DBUS_SESSION_BUS_ADDRESS``), which GitHub's Linux runners don't
provide. The pytest suite mocks the bus (``tests/test_mpris_dbus.py``'s
``FakeDbusBus``) and the Playwright e2e seeds a ``FakeMprisBackend``
(``DECKD_FAKE_MPRIS``); this script is the third leg — real transport,
run by hand on a desktop:

    just smoke-mpris        # or: .venv/bin/python scripts/smoke_mpris_live.py

Exit codes: 0 = passed (or skipped, no session bus), 1 = the backend
failed to see / read the player. The skip path keeps the recipe green on
a headless box without a bus rather than failing spuriously.
"""
from __future__ import annotations

import asyncio

# The synthetic player advertises this bus-name suffix; the backend
# surfaces MPRIS players keyed by the suffix after the well-known prefix.
ROW_SUFFIX = "deckdsmoke"
TRACK_TITLE = "Live Smoke Track"
TRACK_ARTIST = "The Live Bus"


def _build_player_interfaces():
    """The two MPRIS interfaces the backend reads: the root's
    ``Identity`` and the Player's ``PlaybackStatus`` / ``Metadata`` /
    ``CanGoNext`` / ``CanGoPrevious``. dbus_fast serves the
    ``org.freedesktop.DBus.Properties.GetAll`` the backend calls for
    free once these are exported."""
    from dbus_fast import PropertyAccess, Variant
    from dbus_fast.service import ServiceInterface, dbus_property

    class Root(ServiceInterface):
        def __init__(self) -> None:
            super().__init__("org.mpris.MediaPlayer2")

        @dbus_property(access=PropertyAccess.READ)
        def Identity(self) -> "s":  # type: ignore[name-defined]
            return "deckd smoke player"

    class Player(ServiceInterface):
        def __init__(self) -> None:
            super().__init__("org.mpris.MediaPlayer2.Player")

        @dbus_property(access=PropertyAccess.READ)
        def PlaybackStatus(self) -> "s":  # type: ignore[name-defined]
            return "Playing"

        @dbus_property(access=PropertyAccess.READ)
        def Metadata(self) -> "a{sv}":  # type: ignore[name-defined]
            return {
                "xesam:title": Variant("s", TRACK_TITLE),
                "xesam:artist": Variant("as", [TRACK_ARTIST]),
            }

        @dbus_property(access=PropertyAccess.READ)
        def CanGoNext(self) -> "b":  # type: ignore[name-defined]
            return True

        @dbus_property(access=PropertyAccess.READ)
        def CanGoPrevious(self) -> "b":  # type: ignore[name-defined]
            return True

    return Root(), Player()


async def _run() -> int:
    from dbus_fast import BusType
    from dbus_fast.aio import MessageBus

    # 1. Publish the synthetic player on the real session bus.
    try:
        player_bus = await MessageBus(bus_type=BusType.SESSION).connect()
    except Exception as exc:  # no session bus (headless / CI) -> skip, not fail
        print(f"SKIP: no usable session bus ({exc}). Run on a desktop session.")
        return 0

    root_iface, player_iface = _build_player_interfaces()
    player_bus.export("/org/mpris/MediaPlayer2", root_iface)
    player_bus.export("/org/mpris/MediaPlayer2", player_iface)
    await player_bus.request_name(f"org.mpris.MediaPlayer2.{ROW_SUFFIX}")
    print(f"published synthetic player org.mpris.MediaPlayer2.{ROW_SUFFIX}")

    # 2. Drive the *production* backend against the live bus.
    from deckd.mpris import DbusMprisBackend

    backend = DbusMprisBackend(bus_factory=lambda bt: MessageBus(bus_type=bt))
    failures: list[str] = []
    try:
        await backend.start()
        rows = backend.row_ids()
        print(f"backend enumerated rows: {rows}")
        if ROW_SUFFIX not in rows:
            failures.append(
                f"backend did not enumerate {ROW_SUFFIX!r} (saw {rows})"
            )
        else:
            state = await backend.read_state(ROW_SUFFIX)
            print(f"read_state({ROW_SUFFIX!r}) -> {state}")
            if state is None:
                failures.append("read_state returned None for a live player")
            else:
                if state.playing is not True:
                    failures.append(f"expected playing=True, got {state.playing!r}")
                if state.title != TRACK_TITLE:
                    failures.append(
                        f"expected title {TRACK_TITLE!r}, got {state.title!r}"
                    )
                if state.artist != TRACK_ARTIST:
                    failures.append(
                        f"expected artist {TRACK_ARTIST!r}, got {state.artist!r}"
                    )
    finally:
        await backend.stop()
        player_bus.disconnect()

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("PASS: live DbusMprisBackend picked up the player with correct metadata")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
