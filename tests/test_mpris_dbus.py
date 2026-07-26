"""Tests for the real D-Bus MprisBackend (issue #52).

Seam under test: ``DbusMprisBackend`` in :mod:`deckd.mpris`. The
backend implements the same :class:`MprisBackend` Protocol as
``FakeMprisBackend`` (row_ids / read_state / send_command) but talks to
the real session bus via ``dbus_fast``. A fake bus — shaped just like
the methods ``DbusMprisBackend`` actually calls (``connect``,
``call``, ``add_message_handler``, ``disconnect``) — stands in for a
real bus here; the production path uses ``dbus_fast.aio.MessageBus``
plus ``org.freedesktop.DBus.ListNames`` plus
``org.freedesktop.DBus.Properties.PropertiesChanged``.

Coverage mirrors the issue's acceptance criteria:
  * enumeration (``row_ids``) skips ``playerctld`` and malformed names
  * ``read_state`` pulls documented fields via the Player interface
  * ``send_command`` translates browser commands to MPRIS methods
  * ``NameOwnerChanged`` adds/removes rows (rename = remove then add)
  * ``PropertiesChanged`` updates a row's state live
  * the connect-only-if-needed factory yields ``None`` when no layout
    uses ``mediabrowser``
  * the idle-while-no-layout gate is exercised at the pump layer
"""
from __future__ import annotations

from typing import Any, Callable

import pytest

from deckd.mpris import (
    DbusMprisBackend,
    EXCLUDED_PLAYER_SUFFIXES,
    MPRIS_BUS_PREFIX,
    MPRIS_OBJECT_PATH,
    PLAYER_INTERFACE,
    PROPERTIES_INTERFACE,
    ROOT_INTERFACE,
    connect_mpris_backend,
)


# ---------------------------------------------------------------------------
# Fake bus — enough of ``dbus_fast.aio.MessageBus`` for ``DbusMprisBackend``
# ---------------------------------------------------------------------------


class FakeDbusBus:
    """Stand-in for ``dbus_fast.aio.MessageBus`` for MPRIS tests.

    Records every method the backend invokes into ``calls`` so a test
    can assert on the destination / path / interface / method / body.
    For ``call(msg)`` it returns a synthetic reply built from a small
    router — the test controls what each Player interface property
    GetAll returns and what each Player method does. Outbound signals
    (PropertiesChanged, NameOwnerChanged) are pushed into the
    backend's registered handlers via ``emit_*``.
    """

    def __init__(self) -> None:
        self.bus_type: Any = None
        self.connected = False
        self.disconnected = False
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []
        self.message_handlers: list[Callable[[Any], Any]] = []
        # Synthetic state: each row's bus name maps to the properties
        # the backend pulls via Properties.GetAll.
        self._properties: dict[str, dict[str, Any]] = {}
        # Root-interface (``org.mpris.MediaPlayer2``) properties per bus
        # name — where ``Identity`` (the human-readable app name) lives.
        self._root_properties: dict[str, dict[str, Any]] = {}
        # Maps bus name to its current unique-name owner (":1.42").
        # ``GetNameOwner`` replies with this value; defaulted to
        # ":1.<n>" derived from insertion order so signals can be
        # routed without an explicit call.
        self._owners: dict[str, str] = {}
        self._owner_counter = 1
        # Optional failure hook for dispatched Player methods. Tests
        # leave it ``None`` unless they want to simulate a method
        # failure; returning ``False`` makes the reply an ERROR.
        self.player_methods: Callable[[str, str], bool] | None = None

    # -- MessageBus surface the backend touches ----------------------------

    async def connect(self) -> "FakeDbusBus":
        self.connected = True
        return self

    def disconnect(self) -> None:
        self.disconnected = True

    def add_message_handler(self, handler: Callable[[Any], Any]) -> None:
        self.message_handlers.append(handler)

    async def call(self, message: Any) -> Any:
        from dbus_fast import MessageType
        from dbus_fast.message import Message

        self.call_count += 1
        record = {
            "destination": message.destination,
            "path": message.path,
            "interface": message.interface,
            "member": message.member,
            "body": list(message.body or []),
        }
        self.calls.append(record)

        def _ok(signature: str = "", body: list[Any] | None = None) -> Any:
            # ``Message.new_method_return`` requires a non-zero
            # ``reply_serial``; production bus assigns real serials at
            # send time. The fake skips that path (no wire), so we
            # build the reply directly with the inbound serial.
            return Message(
                message_type=MessageType.METHOD_RETURN,
                reply_serial=message.serial or 1,
                signature=signature,
                body=body or [],
            )

        if (
            record["destination"] == "org.freedesktop.DBus"
            and record["interface"] == "org.freedesktop.DBus"
            and record["member"] == "ListNames"
        ):
            names = sorted(self._properties.keys())
            return _ok(signature="as", body=[names])

        if (
            record["destination"] == "org.freedesktop.DBus"
            and record["interface"] == "org.freedesktop.DBus"
            and record["member"] == "GetNameOwner"
        ):
            bus_name = record["body"][0] if record["body"] else ""
            owner = self._owners.get(bus_name, ":1.0")
            return _ok(signature="s", body=[owner])

        if (
            record["interface"] == PROPERTIES_INTERFACE
            and record["member"] == "GetAll"
        ):
            destination = record["destination"]
            interface = record["body"][0] if record["body"] else ""
            row_props = self._properties.get(destination, {})
            if interface != PLAYER_INTERFACE:
                root_props = self._root_properties.get(destination, {})
                return _ok(signature="a{sv}", body=[dict(root_props)])
            return _ok(signature="a{sv}", body=[dict(row_props)])

        if (
            record["interface"] == PLAYER_INTERFACE
            and record["member"] in {"Play", "Pause", "PlayPause", "Next", "Previous"}
        ):
            if self.player_methods is not None:
                if not self.player_methods(record["destination"], record["member"]):
                    return Message(
                        message_type=MessageType.ERROR,
                        reply_serial=message.serial or 1,
                        error_name="org.mpris.MediaPlayer2.Player.Error",
                        body=["synthetic failure"],
                    )
            return _ok()

        return _ok()

    # -- test helpers -------------------------------------------------------

    def set_player_properties(self, bus_name: str, properties: dict[str, Any]) -> None:
        self._properties[bus_name] = dict(properties)
        if bus_name not in self._owners:
            self._owners[bus_name] = f":1.{self._owner_counter}"
            self._owner_counter += 1

    def set_root_properties(self, bus_name: str, properties: dict[str, Any]) -> None:
        self._root_properties[bus_name] = dict(properties)

    def set_owner(self, bus_name: str, unique_name: str) -> None:
        self._owners[bus_name] = unique_name

    def emit_name_owner_changed(
        self, name: str, old_owner: str | None, new_owner: str | None
    ) -> None:
        """Push a ``NameOwnerChanged`` signal to every registered handler."""
        from dbus_fast.message import Message

        for handler in list(self.message_handlers):
            reply = Message.new_signal(
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="NameOwnerChanged",
                signature="sss",
                body=[name, old_owner or "", new_owner or ""],
            )
            handler(reply)

    def emit_properties_changed(
        self,
        bus_name: str,
        interface: str,
        changed: dict[str, Any],
    ) -> None:
        """Push a ``org.freedesktop.DBus.Properties.PropertiesChanged``
        signal to every registered handler. ``sender`` is set to the
        row's current unique-name owner (matches dbus_fast's wire
        behaviour); the backend uses that to map back to a row_id."""
        from dbus_fast.message import Message

        sender = self._owners.get(bus_name, ":1.0")
        for handler in list(self.message_handlers):
            reply = Message.new_signal(
                path=MPRIS_OBJECT_PATH,
                interface=PROPERTIES_INTERFACE,
                member="PropertiesChanged",
                signature="sa{sv}as",
                body=[interface, dict(changed), []],
            )
            reply.sender = sender
            handler(reply)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _static_list_names(names: list[str]) -> Callable[[], list[str]]:
    """A drop-in :class:`DbusMprisBackend.list_names` returning ``names``."""

    def _impl() -> list[str]:
        return list(names)

    return _impl


# ---------------------------------------------------------------------------
# Slice 1 — enumeration: row_ids filters the bus registry correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_row_ids_lists_filtered_mpris_bus_names() -> None:
    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend.list_names = _static_list_names(  # type: ignore[attr-defined]
        [
            "org.mpris.MediaPlayer2.vlc",
            "org.mpris.MediaPlayer2.spotify",
            "org.mpris.MediaPlayer2.playerctld",
            "org.mpris.MediaPlayer2.",            # empty suffix -> malformed
            "org.mpris.MediaPlayer2.weird\nname",  # newline -> malformed
            ":1.42",                              # unique name
            "org.freedesktop.DBus",               # unrelated bus name
        ]
    )
    backend._bus = bus
    await backend.refresh_names()

    ids = sorted(backend.row_ids())
    assert ids == ["spotify", "vlc"]


def test_playerctld_is_excluded_constant() -> None:
    assert "playerctld" in EXCLUDED_PLAYER_SUFFIXES


def test_row_ids_constant_set() -> None:
    assert MPRIS_BUS_PREFIX == "org.mpris.MediaPlayer2"
    assert MPRIS_OBJECT_PATH == "/org/mpris/MediaPlayer2"
    assert PLAYER_INTERFACE == "org.mpris.MediaPlayer2.Player"


# ---------------------------------------------------------------------------
# Slice 2 — read_state maps a Player interface GetAll reply to MediaState
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_state_calls_properties_getall_on_player_interface() -> None:
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc",
        {
            "PlaybackStatus": "Playing",
            "Metadata": {
                "xesam:title": "Walk Like an Egyptian",
                "xesam:artist": ["The Bangles"],
                "mpris:artUrl": "file:///tmp/art.png",
            },
            "CanGoNext": True,
            "CanGoPrevious": True,
        },
    )
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"vlc"}

    state = await backend.read_state("vlc")

    assert state is not None
    assert state.available is True
    assert state.playing is True
    assert state.title == "Walk Like an Egyptian"
    # ``Metadata:artist`` is a list per MPRIS — the daemon joins it so
    # one string travels to the client.
    assert state.artist == "The Bangles"
    # Other MediaState fields the browser doesn't show stay None —
    # the daemon populates only the documented subset.
    assert state.position is None
    assert state.duration is None
    assert state.volume is None
    assert state.rate is None
    # ``art_token`` is always ``None`` for the v1 browser (out-of-scope
    # for issues #52 and #53).
    assert state.art_token is None

    # ``read_state`` issues two GetAll calls: the root interface for the
    # ``Identity`` app name and the Player interface for playback state.
    getalls = [c for c in bus.calls if c["member"] == "GetAll"]
    assert len(getalls) == 2
    call = next(c for c in getalls if c["body"] == [PLAYER_INTERFACE])
    assert call["destination"] == "org.mpris.MediaPlayer2.vlc"
    assert call["path"] == MPRIS_OBJECT_PATH
    assert call["interface"] == PROPERTIES_INTERFACE
    assert call["member"] == "GetAll"


@pytest.mark.asyncio
async def test_read_state_paused_player_reports_playing_false() -> None:
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.spotify", {"PlaybackStatus": "Paused"}
    )
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"spotify"}

    state = await backend.read_state("spotify")
    assert state is not None
    assert state.playing is False


@pytest.mark.asyncio
async def test_read_state_unknown_row_returns_none() -> None:
    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"vlc"}

    assert await backend.read_state("nonexistent") is None
    assert bus.calls == []


# ---------------------------------------------------------------------------
# Slice 3 — send_command translates browser commands to MPRIS methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_command_play_pause_calls_playpause() -> None:
    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"vlc"}

    await backend.send_command("vlc", "play-pause")
    assert len(bus.calls) == 1
    call = bus.calls[0]
    assert call["destination"] == "org.mpris.MediaPlayer2.vlc"
    assert call["path"] == MPRIS_OBJECT_PATH
    assert call["interface"] == PLAYER_INTERFACE
    assert call["member"] == "PlayPause"


@pytest.mark.asyncio
async def test_send_command_next_calls_next() -> None:
    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"vlc"}

    await backend.send_command("vlc", "next")
    assert bus.calls[0]["member"] == "Next"


@pytest.mark.asyncio
async def test_send_command_previous_calls_previous() -> None:
    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"vlc"}

    await backend.send_command("vlc", "previous")
    assert bus.calls[0]["member"] == "Previous"


@pytest.mark.asyncio
async def test_send_command_unknown_command_is_a_noop() -> None:
    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"vlc"}

    await backend.send_command("vlc", "volume")
    assert bus.calls == []


@pytest.mark.asyncio
async def test_send_command_unknown_row_is_a_noop() -> None:
    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"vlc"}

    await backend.send_command("nonexistent", "next")
    assert bus.calls == []


# ---------------------------------------------------------------------------
# Slice 4 — NameOwnerChanged subscribes and reconciles row_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_subscribes_to_name_owner_changed() -> None:
    """``start()`` registers a message handler that reconciles the row set
    on every ``org.freedesktop.DBus.NameOwnerChanged`` signal (issue #52
    acceptance criterion 3). The bus factory is called once with the
    session bus type."""

    captured: dict[str, Any] = {}

    def factory(bus_type: Any) -> FakeDbusBus:
        bus = FakeDbusBus()
        bus.bus_type = bus_type
        captured["bus"] = bus
        return bus

    backend = DbusMprisBackend(bus_factory=factory)
    await backend.start()

    from dbus_fast import BusType

    assert captured["bus"].connected is True
    assert captured["bus"].bus_type is BusType.SESSION
    assert captured["bus"].message_handlers, "expected one message handler"


@pytest.mark.asyncio
async def test_name_owner_changed_adds_a_new_row() -> None:
    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend.list_names = _static_list_names(["org.mpris.MediaPlayer2.vlc"])
    backend._bus = bus
    bus.add_message_handler(backend._on_message)
    await backend.refresh_names()
    assert backend.row_ids() == ["vlc"]

    # A new player appears: org.mpris.MediaPlayer2.spotify registered
    # with owner ":1.99". The handler must extend the row set.
    bus.emit_name_owner_changed("org.mpris.MediaPlayer2.spotify", None, ":1.99")
    assert sorted(backend.row_ids()) == ["spotify", "vlc"]


@pytest.mark.asyncio
async def test_name_owner_changed_removes_a_row() -> None:
    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend.list_names = _static_list_names(
        ["org.mpris.MediaPlayer2.vlc", "org.mpris.MediaPlayer2.spotify"]
    )
    backend._bus = bus
    bus.add_message_handler(backend._on_message)
    await backend.refresh_names()
    assert sorted(backend.row_ids()) == ["spotify", "vlc"]

    # VLC shuts down; its name is released. The handler must drop
    # ``vlc`` from the row set.
    bus.emit_name_owner_changed("org.mpris.MediaPlayer2.vlc", ":1.42", None)
    assert backend.row_ids() == ["spotify"]


@pytest.mark.asyncio
async def test_name_owner_changed_rename_is_remove_then_add() -> None:
    """A bus name handoff (same suffix, new owner) is treated as
    remove-then-add: the row's owner and cached state are cleared,
    then re-registered under the new owner. The end state is
    ``vlc`` again with the new unique name (issue #52 acceptance
    criterion 6)."""
    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend._bus = bus
    bus.add_message_handler(backend._on_message)

    # Step 1: only one player, owned by ":1.1".
    backend.list_names = _static_list_names(["org.mpris.MediaPlayer2.vlc"])  # type: ignore[attr-defined]
    await backend.refresh_names()
    backend._owners["vlc"] = ":1.1"
    assert backend.row_ids() == ["vlc"]

    # Step 2: vlc hands its name off to ":1.2". The handler should
    # drop the cached entry, then re-add for the new owner.
    bus.emit_name_owner_changed("org.mpris.MediaPlayer2.vlc", ":1.1", ":1.2")
    assert backend.row_ids() == ["vlc"]
    assert backend._owners["vlc"] == ":1.2"


# ---------------------------------------------------------------------------
# Slice 5 — PropertiesChanged updates the cached state live
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_properties_changed_updates_cached_state() -> None:
    """A ``PropertiesChanged`` signal for the Player interface refreshes
    the daemon's cached ``MediaState`` so the next ``read_state`` read
    returns the new state without another GetAll round-trip.

    Caching is the implementation detail; the observable seam is that
    a single ``read_state`` after the signal returns the new state
    without any D-Bus call.
    """
    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"vlc"}
    # The owner map is normally populated by the start() path via
    # GetNameOwner; tests bypass start() and inject it directly so the
    # PropertiesChanged sender has somewhere to land.
    backend._owners = {"vlc": ":1.42"}
    bus.set_owner("org.mpris.MediaPlayer2.vlc", ":1.42")
    bus.add_message_handler(backend._on_message)

    # Initial state reads from the bus.
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc", {"PlaybackStatus": "Paused"}
    )
    state = await backend.read_state("vlc")
    assert state is not None
    assert state.playing is False
    # Two GetAll calls on the first read: root (Identity) + Player state.
    assert len(bus.calls) == 2

    # PropertiesChanged: player transitioned to Playing.
    bus.emit_properties_changed(
        "org.mpris.MediaPlayer2.vlc",
        PLAYER_INTERFACE,
        {"PlaybackStatus": "Playing"},
    )

    # Re-read: must reflect the new state without re-issuing GetAll.
    state = await backend.read_state("vlc")
    assert state is not None
    assert state.playing is True
    # No new D-Bus calls: the signal refreshed the Player cache and the
    # Identity is cached from the first read.
    assert len(bus.calls) == 2


# ---------------------------------------------------------------------------
# Slice 6a — read_state extracts the documented field subset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_state_extracts_documented_field_subset() -> None:
    """``read_state`` populates only the documented Player fields
    (issue #52 acceptance criterion 4): ``PlaybackStatus``,
    ``Metadata.title`` and ``Metadata.artist``, ``DesktopEntry``,
    ``CanGoNext``, ``CanGoPrevious``. Other ``MediaState`` slots
    stay ``None`` so a future contributor adding new ones knows the
    subset is intentional."""
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc",
        {
            "PlaybackStatus": "Playing",
            "Metadata": {"xesam:title": "Now Playing", "xesam:artist": ["Bangles"]},
            "DesktopEntry": "vlc.desktop",
            "CanGoNext": True,
            "CanGoPrevious": False,
            # The spec says populate only the documented subset; other
            # Player properties the backend sees must be ignored.
            "Rate": 1.5,
            "Volume": 0.42,
        },
    )
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"vlc"}

    state = await backend.read_state("vlc")
    assert state is not None
    assert state.desktop_entry == "vlc.desktop"
    assert state.can_go_next is True
    assert state.can_go_previous is False
    # ``Rate`` and ``Volume`` are *not* part of the v1 browser subset;
    # they must stay ``None`` rather than leaking through.
    assert state.rate is None
    assert state.volume is None


@pytest.mark.asyncio
async def test_read_state_populates_app_name_from_root_identity() -> None:
    """``read_state`` reads the root-interface ``Identity`` and exposes
    it as ``app_name`` — the human-readable player name (e.g. "VLC media
    player") the browser renders as a per-row header."""
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.vlc", {"PlaybackStatus": "Playing"}
    )
    bus.set_root_properties(
        "org.mpris.MediaPlayer2.vlc", {"Identity": "VLC media player"}
    )
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"vlc"}

    state = await backend.read_state("vlc")
    assert state is not None
    assert state.app_name == "VLC media player"

    # Identity is stable, so it's fetched once and cached: a second read
    # issues no further root-interface GetAll.
    root_getalls = [
        c for c in bus.calls if c["member"] == "GetAll" and c["body"] == [ROOT_INTERFACE]
    ]
    assert len(root_getalls) == 1
    await backend.read_state("vlc")
    root_getalls = [
        c for c in bus.calls if c["member"] == "GetAll" and c["body"] == [ROOT_INTERFACE]
    ]
    assert len(root_getalls) == 1


@pytest.mark.asyncio
async def test_read_state_app_name_none_when_no_identity() -> None:
    """A player that publishes no ``Identity`` leaves ``app_name`` None
    (the browser then renders no header) rather than raising."""
    bus = FakeDbusBus()
    bus.set_player_properties(
        "org.mpris.MediaPlayer2.mpv", {"PlaybackStatus": "Playing"}
    )
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"mpv"}

    state = await backend.read_state("mpv")
    assert state is not None
    assert state.app_name is None


@pytest.mark.asyncio
async def test_properties_changed_unwraps_variant_values() -> None:
    """``PropertiesChanged`` delivers ``a{sv}`` values boxed in
    ``dbus_fast`` ``Variant`` objects (``Metadata`` is itself a Variant
    wrapping a nested ``a{sv}``). The signal handler must unwrap them —
    a raw ``Variant`` is unhashable and blows up the ``PlaybackStatus``
    membership check (regression: the browser showed nothing for a real
    playing VLC)."""
    from dbus_fast.signature import Variant

    bus = FakeDbusBus()
    backend = DbusMprisBackend()
    backend._bus = bus
    backend._owned_names = {"vlc"}
    backend._owners = {"vlc": ":1.42"}
    bus.set_owner("org.mpris.MediaPlayer2.vlc", ":1.42")
    bus.add_message_handler(backend._on_message)

    # Signal body shaped like the real bus: every value is a Variant.
    bus.emit_properties_changed(
        "org.mpris.MediaPlayer2.vlc",
        PLAYER_INTERFACE,
        {
            "PlaybackStatus": Variant("s", "Playing"),
            "Metadata": Variant(
                "a{sv}",
                {
                    "xesam:title": Variant("s", "Two In The Bush"),
                    "xesam:artist": Variant("as", ["Outback"]),
                },
            ),
            "CanGoNext": Variant("b", True),
        },
    )

    state = await backend.read_state("vlc")
    assert state is not None
    assert state.playing is True
    assert state.title == "Two In The Bush"
    assert state.artist == "Outback"
    assert state.can_go_next is True


# ---------------------------------------------------------------------------
# Slice 6b — start() installs AddMatch rules so signals arrive in production
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_installs_match_rules() -> None:
    """``start()`` registers D-Bus ``AddMatch`` rules so the bus daemon
    pushes ``NameOwnerChanged`` and ``PropertiesChanged`` to this
    connection. Without them, ``add_message_handler`` doesn't see
    production signals — every test that exercises the handlers
    relies on this."""
    bus = FakeDbusBus()

    def factory(_bt: Any) -> FakeDbusBus:
        return bus

    backend = DbusMprisBackend(bus_factory=factory)
    await backend.start()

    try:
        # Two AddMatch calls: NameOwnerChanged + PropertiesChanged.
        add_match = [
            c for c in bus.calls if c["interface"] == "org.freedesktop.DBus"
            and c["member"] == "AddMatch"
        ]
        rules = [c["body"][0] for c in add_match]
        assert any("NameOwnerChanged" in rule for rule in rules)
        assert any(
            "PropertiesChanged" in rule and "org.mpris" in rule for rule in rules
        )
    finally:
        await backend.stop()


# ---------------------------------------------------------------------------
# Slice 6 — connect_mpris_backend factory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_mpris_backend_returns_none_when_no_layout_has_mediabrowser() -> None:
    """The factory only opens the bus when at least one loaded layout
    declares a ``mediabrowser`` widget (issue #52 acceptance criterion 1)."""

    captured: dict[str, Any] = {}

    def factory(_bt: Any) -> FakeDbusBus:
        bus = FakeDbusBus()
        captured["bus"] = bus
        return bus

    store = _store_with_layouts(
        [
            ("default", [{"id": "btn", "kind": "button", "grid": [0, 0, 1, 1]}]),
            ("firefox", [{"id": "btn", "kind": "button", "grid": [0, 0, 1, 1]}]),
        ]
    )

    backend = connect_mpris_backend(store, factory)
    assert backend is None
    assert captured == {}


@pytest.mark.asyncio
async def test_connect_mpris_backend_returns_backend_when_a_layout_has_mediabrowser() -> None:
    def factory(_bt: Any) -> FakeDbusBus:
        return FakeDbusBus()

    store = _store_with_layouts(
        [
            (
                "mpris",
                [{"id": "browser", "kind": "mediabrowser", "grid": [0, 0, 4, 2]}],
            ),
        ]
    )
    backend = connect_mpris_backend(store, factory)
    assert backend is not None
    await backend.stop()


# ---------------------------------------------------------------------------
# Layout-store test helper (lightweight stand-in for LayoutStore.values)
# ---------------------------------------------------------------------------


def _store_with_layouts(spec: list[tuple[str, list[dict[str, Any]]]]) -> Any:
    """A duck-typed :class:`LayoutStore` exposing ``.layouts``.

    The factory only reads ``layout.widgets[*].kind``, so a namedtuple
    per fake layout is enough — no need for a three-class ladder.
    """

    def _layout(spec_id: str, widget_specs: list[dict[str, Any]]) -> Any:
        layout = type("L", (), {})()
        layout.id = spec_id
        widgets: list[Any] = []
        for w in widget_specs:
            widget = type("W", (), {})()
            widget.id = w.get("id")
            widget.kind = w.get("kind")
            widgets.append(widget)
        layout.widgets = widgets
        return layout

    class _Store:
        def __init__(self) -> None:
            self._layouts: list[Any] = [_layout(_id, ws) for _id, ws in spec]

        @property
        def layouts(self) -> list[Any]:
            return list(self._layouts)

    return _Store()
