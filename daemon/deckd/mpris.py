from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .layouts import MediaBrowserEmptyState
from .media import MediaState, _art_token
from .mpris_art import is_supported_art_url

if TYPE_CHECKING:
    from dbus_fast import BusType
    from dbus_fast.aio import MessageBus

    from .layouts import LayoutStore

log = logging.getLogger("deckd.mpris")


# Browser-facing command -> MPRIS D-Bus method name. The set is the
# three controls the v1 browser ships (issue #52 acceptance criterion
# for the dispatch mapping); any other command is a no-op so a future
# browser-side button can't accidentally invoke a destructive MPRIS
# method.
_COMMANDS: dict[str, str] = {
    "play-pause": "PlayPause",
    "next": "Next",
    "previous": "Previous",
}


# MPRIS protocol constants. Documented in the upstream MPRIS spec
# (https://specifications.freedesktop.org/mpris-spec/latest/) and
# stated explicitly here so the layout / protocol / client surface
# and the backend can't drift apart on a typo.
MPRIS_BUS_PREFIX = "org.mpris.MediaPlayer2"
MPRIS_OBJECT_PATH = "/org/mpris/MediaPlayer2"
ROOT_INTERFACE = "org.mpris.MediaPlayer2"
PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
DBUS_INTERFACE = "org.freedesktop.DBus"
NAME_OWNER_CHANGED = "NameOwnerChanged"
PROPERTIES_CHANGED = "PropertiesChanged"

# The MPRIS multiplexer (`playerctld`) accepts every other player's
# commands and re-dispatches them. Listing it next to the real players
# creates a duplicate row the user has no way to remove; we skip it.
# The filter is a constant set so layouts / docs / tests can reference
# the same list rather than hard-coding the strings.
EXCLUDED_PLAYER_SUFFIXES = frozenset({"playerctld"})


def _is_mpris_bus_name(name: str) -> bool:
    """True for ``org.mpris.MediaPlayer2.<suffix>`` where ``suffix`` is a
    non-empty, ASCII-safe segment."""
    return _mpris_suffix(name) is not None


def _mpris_suffix(name: str) -> str | None:
    """Extract the row suffix (``"vlc"``, ``"spotify"``) from a bus
    name like ``org.mpris.MediaPlayer2.vlc``, or ``None`` if the
    name isn't a well-formed MPRIS row.

    A well-formed suffix is non-empty, only ASCII alphanumerics or
    ``-`` / ``_`` / ``.`` (legal in a D-Bus name), and not in
    :data:`EXCLUDED_PLAYER_SUFFIXES`. Centralising the rule here
    means :func:`_is_mpris_bus_name`, :meth:`refresh_names`, and
    the ``NameOwnerChanged`` handler agree on the same filter."""
    if not isinstance(name, str) or not name.startswith(MPRIS_BUS_PREFIX + "."):
        return None
    suffix = name[len(MPRIS_BUS_PREFIX) + 1 :]
    if not suffix:
        return None
    if not all(c.isalnum() or c in "_-." for c in suffix):
        return None
    if suffix in EXCLUDED_PLAYER_SUFFIXES:
        return None
    return suffix


def _first_body_value(message: Any) -> Any:
    """Return ``message.body[0]`` when the body is a non-empty list,
    else ``None``. Centralises the defensive shape check that the
    GetAll / ListNames / GetNameOwner replies need — dbus_fast may
    surface a None body or a missing first slot on some failure
    paths, and four call sites all need the same handling.
    """
    body = getattr(message, "body", None)
    if not body:
        return None
    return body[0]


def _unwrap(value: Any) -> Any:
    """Recursively strip ``dbus_fast`` ``Variant`` wrappers.

    ``a{sv}`` bodies (``GetAll`` replies and ``PropertiesChanged``
    ``changed`` dicts) arrive with every value boxed in a ``Variant``,
    and ``Metadata`` is a ``Variant`` wrapping a nested ``a{sv}``. The
    property mappers want plain ``str`` / ``bool`` / ``list``, so unwrap
    before they run — otherwise ``isinstance`` checks silently drop
    every field and ``status in {...}`` blows up on the unhashable
    ``Variant``. Detected by duck-typing (``.value`` + ``.signature``)
    to avoid a hard ``dbus_fast`` import on the test path.
    """
    if hasattr(value, "value") and hasattr(value, "signature"):
        return _unwrap(value.value)
    if isinstance(value, dict):
        return {k: _unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unwrap(v) for v in value]
    return value


def _is_awaitable(value: Any) -> bool:
    """True when ``value`` can be awaited (a coroutine, task, or Future).

    Used to bridge a sync callable (the test seam) and an async one
    (the real bus path) inside ``DbusMprisBackend.refresh_names`` —
    the test passes a plain list; production rebinds the same slot to
    a coroutine that fetches via ``org.freedesktop.DBus.ListNames``."""
    return hasattr(value, "__await__")


# The set of artUrl shapes the ``/mpris/<row>/art`` proxy knows how to
# fetch (issue #57). The allowed-scheme predicate lives in
# :mod:`deckd.mpris_art` so the backend's gate and the resolver's
# dispatch can never drift apart: any URL the backend writes to its
# cache is one the resolver will fetch.
def _parse_mpris_art_url(metadata: Any) -> str | None:
    """Pull the row's ``mpris:artUrl`` out of a Metadata dict, validating
    the URL shape the proxy can serve.

    Returns the raw URL string for known shapes (``file://``,
    ``http://``, ``https://``, ``data:``) so the proxy can stream it,
    or ``None`` for missing / unknown / non-string values. The token
    is derived by :func:`deckd.media._art_token` from whatever this
    returns — ``None`` there means "no art, fall back".
    """
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("mpris:artUrl")
    if not is_supported_art_url(value):
        return None
    return value


class MediaBrowser(BaseModel):
    """The ``mediabrowser`` widget kind (issue #50).

    Lists the MPRIS rows the daemon's :class:`MprisBackend` reports, with
    each row showing its player identity and prev / play-pause / next
    controls. Lives here (not in :mod:`layouts`) because it's the MPRIS
    feature's own schema, not a VLC-media cousin — keeping the new model
    next to its backend seam avoids re-coupling the layout module to a
    second media source.

    Fields:

    - ``id``: the widget id (used as the layout-internal id and surfaced
      to the client so it can correlate per-row updates).
    - ``size``: the standard reflow extent, identical to every other widget
      kind (ADR-0010) — a ``[w, h]`` span or ``"full"``. Optional; a
      mediabrowser is typically a full-surface view rendered outside the flow.
    - ``empty_state``: whether the cell still renders a placeholder row
      when no MPRIS player is discovered. ``show`` (default) keeps the
      chrome's icon reachable; ``hide`` collapses the cell so a layout
      that relies on the browser can drop the cell entirely.

    Row order is whatever :meth:`MprisBackend.row_ids` returns — by
    convention the order the session bus's ``ListNames`` reply reports
    them, matching GNOME Shell's quick-settings media widget. No
    per-layout knob (issue #58).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    size: list[int] | Literal["full"] | None = None
    empty_state: MediaBrowserEmptyState = "show"


class MprisBackend(Protocol):
    """Backend seam for enumerating MPRIS rows and controlling them."""

    def row_ids(self) -> list[str]:
        ...

    async def read_state(self, row_id: str) -> MediaState | None:
        ...

    async def send_command(self, row_id: str, command: str) -> None:
        ...

    def art_url(self, row_id: str) -> str | None:
        """The row's current ``mpris:artUrl`` (one of the proxy-servable
        shapes — ``file://`` / ``http(s)://`` / ``data:``), or ``None``
        when there is no art or the row is unknown (issue #57)."""
        ...

    def set_chrome_media_listener(
        self, listener: "Callable[[ChromeMediaState], None] | None"
    ) -> None:
        """Register a callback fired on the chrome-media indicator's
        boundary events (issue #47).

        The listener receives the new :class:`ChromeMediaState` snapshot
        after every ``NameOwnerChanged`` registration transition and
        after every ``PlaybackStatus`` change that crosses the
        Playing ↔ non-Playing boundary. Position / Metadata updates
        that don't flip ``playing`` do not fire the listener (debounce
        by event-type, no time window).

        ``None`` unregisters the listener. The default is no listener —
        a backend constructed without one stays quiet, so a test that
        doesn't care about chrome-media can ignore the path entirely.
        """
        ...

    def chrome_media_snapshot(self) -> ChromeMediaState:
        """Compute the current chrome-media state from the backend's
        owned-rows set and per-row cached ``playing`` flag (issue #47).

        Used for the just-connected session snapshot path: the
        broadcast loop only fires on event-type transitions, so a
        session that joins mid-lifetime would otherwise never see the
        current ``playing`` / ``available`` until the next event. The
        snapshot fills that gap with a one-shot frame based on the
        backend's current view of the bus.
        """
        ...

    def set_diagnostic_listener(
        self, listener: "Callable[[str, str | None, dict[str, Any]], None] | None"
    ) -> None:
        """Register a callback fired on every backend-internal event
        (issue #72).

        ``listener`` is invoked synchronously from the same task that
        processes the originating signal (a NameOwnerChanged /
        PropertiesChanged handler, or a method called from the
        ``send_command`` path). The arguments are
        ``(kind, row_id, data)``; ``kind`` is one of ``"player_added"``,
        ``"player_removed"``, ``"playback_changed"``,
        ``"metadata_changed"``, ``"command"``, ``"dbus_error"``,
        ``"art_error"``. ``data`` is event-specific, redacted, and
        must not contain the shared password or arbitrary URLs.

        ``None`` unregisters the listener. Default is no listener so a
        backend that doesn't care about diagnostics stays quiet.
        """
        ...


@dataclass(frozen=True)
class ChromeMediaState:
    """Chrome-icon passive-playback snapshot (issue #47).

    Wire shape: ``{available, playing, playing_count}``. ``available``
    means at least one ``org.mpris.MediaPlayer2.*`` player is
    registered on the session bus; ``playing`` is true when at least
    one is in ``PlaybackStatus == Playing``; ``playing_count`` is the
    number of players in Playing (so a future 'now playing' indicator
    has the raw count to work with — today the icon only tints on the
    boolean ``playing``).

    Frozen so two values computed from the same inputs compare equal
    by value — the server's broadcast loop debounces against equality,
    so a frozen dataclass gives that for free.
    """

    available: bool
    playing: bool
    playing_count: int


def compute_chrome_media(
    owned_names: list[str], states: dict[str, MediaState]
) -> ChromeMediaState:
    """Pure mapping from the backend's row set + cached states to a
    :class:`ChromeMediaState` snapshot (issue #47).

    Available reflects the owned-names set (the session bus's
    ``ListNames`` reply). Playing tally reads each owned row's cached
    ``playing`` flag — ``True`` only on a confirmed Playing. ``None``
    or missing cached states count as not-playing: the chrome icon
    must not tint on unconfirmed state.

    Centralising the rule here keeps the
    ``_emit_chrome_media`` callback on :class:`DbusMprisBackend`
    trivially testable (this function is its only logic) and gives the
    server's media pump a single function to call when it wants a
    snapshot for any reason (e.g. a late session catching up).
    """
    playing_count = 0
    for suffix in owned_names:
        state = states.get(suffix)
        if state is not None and state.playing is True:
            playing_count += 1
    return ChromeMediaState(
        available=bool(owned_names),
        playing=playing_count > 0,
        playing_count=playing_count,
    )


@dataclass
class FakeMprisBackend(MprisBackend):
    states: dict[str, MediaState]

    def __init__(self, states: dict[str, MediaState] | None = None) -> None:
        self.states = dict(states or {})
        self.commands: list[tuple[str, str]] = []
        # Synthetic artUrl table; tests that exercise the proxy inject
        # entries here. Keys are row suffixes, values are the raw URL
        # the proxy would serve (``file://…``, ``https://…``, ``data:…``).
        self.art_urls: dict[str, str] = {}
        # Diagnostic listener (issue #72). The default no-op keeps
        # tests that don't care about the diagnostic ring buffer out
        # of the wiring.
        self._diagnostic_listener: Callable[[str, str | None, dict[str, Any]], None] | None = None

    def row_ids(self) -> list[str]:
        return list(self.states)

    async def read_state(self, row_id: str) -> MediaState | None:
        state = self.states.get(row_id)
        if state is None:
            return None
        # Mirror the real backend: art_url rides on the same
        # MediaState so the snapshot helper sees the art flag
        # without a second lookup. ``dataclasses.replace`` keeps the
        # state frozen while letting tests inject art URLs without
        # rebuilding the whole state.
        art_url = self.art_urls.get(row_id)
        if art_url is not None and state.art_url != art_url:
            return replace(state, art_url=art_url)
        return state

    async def send_command(self, row_id: str, command: str) -> None:
        self.commands.append((row_id, command))

    def art_url(self, row_id: str) -> str | None:
        """The row's current ``mpris:artUrl`` (one of the proxy-servable
        shapes — ``file://`` / ``http(s)://`` / ``data:``), or ``None``
        when there is no art or the row is unknown.

        Tests inject entries into :attr:`art_urls`; production uses
        :class:`DbusMprisBackend`'s implementation, which reads the
        URL the bus's most recent ``Metadata`` carried.
        """
        return self.art_urls.get(row_id)

    def chrome_media_snapshot(self) -> ChromeMediaState:
        """Snapshot the current chrome-media state (issue #47).

        Mirrors the production implementation: read every cached
        row's ``playing`` flag from the states map. ``row_ids()`` is
        the source of truth for which rows are currently on the bus,
        so a state entry for a row no longer in ``row_ids`` is
        correctly ignored by the reducer.
        """
        return compute_chrome_media(self.row_ids(), self.states)

    def set_diagnostic_listener(
        self, listener: Callable[[str, str | None, dict[str, Any]], None] | None
    ) -> None:
        self._diagnostic_listener = listener

    def _emit_diagnostic(
        self, kind: str, row_id: str | None, data: dict[str, Any]
    ) -> None:
        listener = self._diagnostic_listener
        if listener is not None:
            listener(kind, row_id, data)


class DbusMprisBackend(MprisBackend):
    """Real-session-bus MPRIS backend (issue #52).

    Connects to the session bus via ``dbus_fast.aio.MessageBus``,
    enumerates ``org.mpris.MediaPlayer2.*`` players, subscribes to
    ``NameOwnerChanged`` / ``PropertiesChanged`` so rows appear /
    disappear as players start and stop, and translates browser
    commands (``play-pause`` / ``next`` / ``previous``) into D-Bus
    method calls on the right player.

    The class is constructed empty; :meth:`start` does the connect /
    enumerate / subscribe work, and :meth:`stop` tears it down. A
    no-layouts-use-it factory :func:`connect_mpris_backend` returns
    ``None`` so a daemon whose layouts don't include ``mediabrowser``
    doesn't even open the bus.

    The bus surface is plugged through ``bus_factory`` so tests can
    swap in a fake without standing up a real session bus. The fake
    used in :mod:`tests.test_mpris_dbus` records every method call
    and lets the test push synthetic NameOwnerChanged /
    PropertiesChanged signals into the backend's handlers.
    """

    def __init__(self, bus_factory: "Callable[[BusType], MessageBus] | None" = None) -> None:
        self._bus_factory = bus_factory
        self._bus: MessageBus | None = None
        # Owned MPRIS row suffixes in bus-discovery order — i.e. the
        # order :meth:`refresh_names` last saw on the session bus's
        # ``ListNames`` reply (matching GNOME Shell, issue #58). The
        # set is bounded by the number of MPRIS players on the bus
        # (a handful), so list ops are fine; ``list`` is the right
        # shape because we need stable iteration order, not O(1)
        # membership.
        self._owned_names: list[str] = []
        # Maps a row suffix (``vlc``) to the unique-name
        # (``":1.42"``) it last saw on the bus. Used to translate
        # ``PropertiesChanged.sender`` (a unique name) back into a
        # row id; updated on every ``NameOwnerChanged`` so a handoff
        # routes future signals to the right row.
        self._owners: dict[str, str] = {}
        self._states: dict[str, MediaState] = {}
        # Row suffix -> the player's root-interface ``Identity`` string
        # (or ``None`` when it has none / the read failed). Identity is
        # stable for a bus name, so it's fetched once on first read and
        # reused — a key absent from the dict means "not fetched yet".
        self._identities: dict[str, str | None] = {}
        # ``list_names`` rebinds once ``start()`` has a live bus to a
        # coroutine that fetches via ``org.freedesktop.DBus.ListNames``;
        # tests override it to return a synchronous fixture list so
        # they don't need an event loop or a real daemon bus. Both
        # shapes (awaitable or plain list) are awaited by
        # :meth:`refresh_names` via ``_is_awaitable``.
        self.list_names: Callable[[], Any] = lambda: []
        # Chrome-media passive indicator listener (issue #47). The
        # server wires its broadcast loop in here so the chrome icon
        # tints on ``NameOwnerChanged`` registration transitions and
        # on ``PlaybackStatus`` boundary crossings. ``None`` keeps the
        # backend quiet — a backend constructed without a listener
        # still works, so tests that don't exercise chrome-media can
        # leave the slot empty.
        self._chrome_media_listener: Callable[[ChromeMediaState], None] | None = None

    def set_chrome_media_listener(
        self, listener: Callable[[ChromeMediaState], None] | None
    ) -> None:
        self._chrome_media_listener = listener

    def set_diagnostic_listener(
        self, listener: Callable[[str, str | None, dict[str, Any]], None] | None
    ) -> None:
        # Issue #72: the daemon's diagnostics module listens for
        # player-add/remove/playback/metadata transitions and writes
        # them to a bounded ring buffer the ``/mpris/events/recent``
        # endpoint exposes. ``None`` unregisters (tests that don't
        # exercise the path stay quiet).
        self._diagnostic_listener = listener

    def _emit_diagnostic(
        self, kind: str, row_id: str | None, data: dict[str, Any]
    ) -> None:
        listener = getattr(self, "_diagnostic_listener", None)
        if listener is not None:
            listener(kind, row_id, data)

    def _emit_chrome_media(self) -> None:
        """Snapshot the chrome-media state and fire the listener.

        Called from the two event sites the issue names:
        ``NameOwnerChanged`` registration transitions (every one —
        registration and unregistration both count, since ``available``
        changes either way) and ``PlaybackStatus`` boundary crossings.
        Position / Metadata updates that don't flip ``playing`` skip
        this path entirely; the listener isn't called, so no frame is
        produced.
        """
        listener = self._chrome_media_listener
        if listener is None:
            return
        listener(compute_chrome_media(self._owned_names, self._states))

    def row_ids(self) -> list[str]:
        # The single source of truth for the row order the browser
        # surfaces. Reflects whatever ``refresh_names`` last observed
        # on the session bus (typically == ``ListNames`` reply order,
        # matching GNOME Shell — issue #58). Returns a copy so callers
        # can iterate without worrying about concurrent mutation from
        # ``NameOwnerChanged`` handlers.
        return list(self._owned_names)

    async def start(self) -> None:
        """Connect to the session bus, enumerate, and subscribe.

        Idempotent: a second call without an intervening :meth:`stop`
        is a no-op so the server's :meth:`start_media_pump` path can
        call it freely without tracking first-start state.
        """
        if self._bus is not None:
            return
        factory = self._bus_factory
        if factory is None:  # pragma: no cover -- guarded by factory caller
            raise RuntimeError("DbusMprisBackend requires a bus_factory")
        from dbus_fast import BusType

        self._bus = factory(BusType.SESSION)
        await self._bus.connect()
        # Install match rules BEFORE we subscribe so the bus daemon
        # actually delivers the signals we care about. ``AddMatch``
        # is the standard D-Bus mechanism; without it, the registry
        # never pushes ``NameOwnerChanged`` or
        # ``PropertiesChanged`` to this connection, and the add_message_handler
        # we register below would never see them in production.
        await self._add_match(
            "type='signal',sender='org.freedesktop.DBus',"
            "interface='org.freedesktop.DBus',member='NameOwnerChanged'"
        )
        await self._add_match(
            "type='signal',interface='org.freedesktop.DBus.Properties',"
            "member='PropertiesChanged',arg0namespace='org.mpris'"
        )
        self._override_list_names_from_bus()
        await self.refresh_names()
        self._bus.add_message_handler(self._on_message)
        # Discover the unique-name owner of every row so subsequent
        # ``PropertiesChanged`` signals can be routed to the right
        # row. ``GetNameOwner`` is cheap (it's a registry lookup); a
        # second pass on the same list would be redundant.
        await self._populate_owners()

    async def stop(self) -> None:
        """Disconnect from the session bus.

        Safe to call without a prior :meth:`start` (test cleanup
        paths fire this unconditionally).
        """
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None
        self._owned_names = []
        self._owners = {}
        self._states = {}
        self._identities = {}

    def _override_list_names_from_bus(self) -> None:
        """Bind ``list_names`` to the bus-backed ``ListNames`` caller.

        The real path uses ``org.freedesktop.DBus.ListNames`` to fetch
        every owned bus name on every refresh. Tests leave the
        default ``list_names`` in place and inject values directly;
        both shapes (sync list-returning and async coroutine-returning) are
        awaited by :meth:`refresh_names`.
        """

        async def _impl() -> list[str]:
            assert self._bus is not None
            from dbus_fast.message import Message

            reply = await self._bus.call(
                Message(
                    destination=DBUS_INTERFACE,
                    path="/org/freedesktop/DBus",
                    interface=DBUS_INTERFACE,
                    member="ListNames",
                )
            )
            inner = _first_body_value(reply)
            if not isinstance(inner, list):
                return []
            return [n for n in inner if isinstance(n, str)]

        self.list_names = _impl  # type: ignore[assignment]  # bridge sync/async at runtime; see _is_awaitable in refresh_names

    async def refresh_names(self) -> None:
        """Re-read the bus-name registry and reconcile ``_owned_names``.

        Called on startup and after every ``NameOwnerChanged`` signal —
        the bus's list of owned ``org.mpris.MediaPlayer2.*`` names
        changes whenever a player comes or goes. Filtering happens
        here; the fake and the real bus both go through this single
        path so the row set is identical in both shapes.

        The list preserves the ``ListNames`` reply order: ``row_ids``
        then returns the same order GNOME Shell's quick-settings
        media widget surfaces, so the two read identically end-to-end
        on the same session bus. Duplicates the bus might publish are
        collapsed to first occurrence — issue #58.
        """
        result = self.list_names()
        if _is_awaitable(result):
            result = await result  # type: ignore[misc]
        new_names: list[str] = []
        seen: set[str] = set()
        for n in result:
            suffix = _mpris_suffix(n)
            if suffix is None or suffix in seen:
                continue
            seen.add(suffix)
            new_names.append(suffix)
        self._owned_names = new_names
        # Drop cached state and stale owner mappings for players
        # that disappeared so the next ``read_state`` repopulates
        # them cleanly.
        self._states = {k: v for k, v in self._states.items() if k in self._owned_names}
        self._owners = {k: v for k, v in self._owners.items() if k in self._owned_names}
        self._identities = {
            k: v for k, v in self._identities.items() if k in self._owned_names
        }

    async def _populate_owners(self) -> None:
        """Populate ``_owners`` for every owned row via ``GetNameOwner``.

        ``PropertiesChanged`` signals arrive from the player's unique
        name (``:1.N``), not the bus name, so we have to learn the
        mapping once on startup.
        """
        if not self._bus:
            return
        from dbus_fast.message import Message

        suffixes = list(self._owned_names)
        for suffix in suffixes:
            try:
                reply = await self._bus.call(
                    Message(
                        destination=DBUS_INTERFACE,
                        path="/org/freedesktop/DBus",
                        interface=DBUS_INTERFACE,
                        member="GetNameOwner",
                        signature="s",
                        body=[f"{MPRIS_BUS_PREFIX}.{suffix}"],
                    )
                )
            except Exception as exc:
                log.debug("GetNameOwner for %s failed: %s", suffix, exc)
                continue
            if reply is None or reply.body is None:
                continue
            owner = _first_body_value(reply)
            if isinstance(owner, str) and owner:
                self._owners[suffix] = owner

    async def _add_match(self, rule: str) -> None:
        """Install a D-Bus ``AddMatch`` rule on the bus connection.

        ``dbus_fast`` registers ``NameOwnerChanged`` automatically
        when its high-level proxy is constructed (the
        ``_name_owner_match_rule`` member), but it does not by default
        install our ``PropertiesChanged`` rule, and the bus daemon
        only delivers signals to clients whose match rules match the
        signal — so without these calls, the production backend
        receives nothing.
        """
        if not self._bus:
            return
        from dbus_fast import MessageType
        from dbus_fast.message import Message

        try:
            reply = await self._bus.call(
                Message(
                    destination=DBUS_INTERFACE,
                    path="/org/freedesktop/DBus",
                    interface=DBUS_INTERFACE,
                    member="AddMatch",
                    signature="s",
                    body=[rule],
                )
            )
        except Exception as exc:
            log.warning("AddMatch %r failed: %s", rule, exc)
            self._emit_diagnostic(
                "dbus_error", None, {"op": "AddMatch", "error": repr(exc)}
            )
            return
        if reply is not None and reply.message_type == MessageType.ERROR:
            log.warning(
                "AddMatch %r returned error: %s", rule, getattr(reply, "body", None)
            )
            self._emit_diagnostic(
                "dbus_error",
                None,
                {"op": "AddMatch", "error": getattr(reply, "body", None)},
            )

    def _on_message(self, message: Any) -> None:
        """Bus-side message handler.

        dbus_fast delivers every inbound D-Bus message to every
        registered handler — including ``METHOD_RETURN`` replies we
        made (which are routed back to the originating ``call`` via
        serial matching and are best ignored here). For signals
        (``message_type == SIGNAL``), we react to the two subscriptions
        the issue's acceptance criteria require: ``NameOwnerChanged``
        and ``PropertiesChanged``.
        """
        from dbus_fast import MessageType

        if getattr(message, "message_type", None) != MessageType.SIGNAL:
            return
        if (
            message.member == NAME_OWNER_CHANGED
            and message.interface == DBUS_INTERFACE
        ):
            self._handle_name_owner_changed(message)
        elif (
            message.member == PROPERTIES_CHANGED
            and message.interface == PROPERTIES_INTERFACE
        ):
            self._handle_properties_changed(message)

    def _handle_name_owner_changed(self, message: Any) -> None:
        # ``NameOwnerChanged`` body is ``(name, old_owner, new_owner)``.
        # ``old_owner`` empty + ``new_owner`` non-empty -> a name
        # appeared; the reverse -> disappeared; both set -> a name was
        # handed off (old owner left, new owner took it). Issue #52
        # spec calls for treat-rename-as-remove-then-add: clear the
        # row's owner and cache, then re-add it for the new owner. A
        # brief row-blip between the two is the spec's intent — the
        # the browser reflects what the bus is publishing, and the
        # next ``read_state`` poll fills the new owner's cache.
        body = message.body or []
        if len(body) < 3:
            return
        name = body[0]
        old_owner = body[1]
        new_owner = body[2]
        suffix = _mpris_suffix(name)
        if suffix is None:
            return
        log.debug(
            "NameOwnerChanged %s: %s -> %s",
            name,
            old_owner or "<none>",
            new_owner or "<none>",
        )
        # Phase 1: drop the old owner (always — issue #52 says even a
        # pure-add goes through a remove-and-add so the row's metadata
        # is rebuilt cleanly under the new owner).
        if old_owner:
            if suffix in self._owned_names:
                self._owned_names.remove(suffix)
            self._owners.pop(suffix, None)
            self._states.pop(suffix, None)
            self._identities.pop(suffix, None)
        # Phase 2: re-add the new owner (no-op on a pure removal
        # where ``new_owner`` is the empty string). Append to the tail
        # so the row's position in ``row_ids`` reflects when it last
        # appeared on the bus — matching GNOME Shell's quick-settings
        # widget (issue #58).
        if new_owner and suffix not in self._owned_names:
            self._owned_names.append(suffix)
            self._owners[suffix] = new_owner
            self._emit_diagnostic("player_added", suffix, {"owner": new_owner})
        elif old_owner and suffix in self._owned_names:
            # Pure remove (no re-add); the else branch above only
            # covers the re-add case, so a true removal still needs
            # its event.
            self._emit_diagnostic(
                "player_removed", suffix, {"old_owner": old_owner}
            )
        elif new_owner and suffix in self._owned_names:
            # Handoff: same suffix, new owner. Counts as a player
            # change for the diagnostic timeline even though the
            # chrome-media debounce is intentionally quiet on it.
            self._emit_diagnostic(
                "player_added",
                suffix,
                {"owner": new_owner, "handoff": True},
            )
        # Issue #47: every ``NameOwnerChanged`` registration transition
        # (registration, unregistration, handoff) flips the chrome icon's
        # ``available`` bit, so emit regardless of direction.
        self._emit_chrome_media()

    def _handle_properties_changed(self, message: Any) -> None:
        # ``PropertiesChanged`` body is ``(interface, changed,
        # invalidated)``. Only the Player interface matters — the
        # root ``org.mpris.MediaPlayer2`` interface doesn't carry
        # playback state.
        body = message.body or []
        if len(body) < 2 or body[0] != PLAYER_INTERFACE:
            return
        changed = _unwrap(body[1] or {})
        sender = getattr(message, "sender", None)
        if not isinstance(sender, str):
            return
        # Reverse the owner map once per signal rather than maintain
        # a per-row reverse index — the size is bounded by the number
        # of MPRIS players (a handful on a typical desktop).
        for row_id, owner in self._owners.items():
            if owner == sender:
                previous = self._states.get(row_id) or MediaState(
                    available=True, stale=False
                )
                # Capture the prior ``playing`` flag before merging
                # the new ``changed`` dict — the chrome-media
                # debounce rule fires only on the boundary crossing,
                # so a Position-only or Metadata-only update (which
                # never touches ``playing``) must not emit (issue #47).
                previous_playing = previous.playing is True
                # ``_apply_properties_changed`` updates ``art_token`` and
                # ``art_url`` together from the signal's ``Metadata`` (or
                # preserves the previous values if Metadata is absent) —
                # so the proxy's URL always tracks the state cache, no
                # second cache to keep in sync (issue #57).
                self._states[row_id] = _apply_properties_changed(previous, changed)
                next_playing = self._states[row_id].playing is True
                # Issue #47 chrome-media debounce: emit on every flip of
                # the boolean ``playing`` flag the icon's tint depends
                # on. The spec's literal wording covers Paused → Stopped
                # transitions too, but a Stopped state still maps to
                # ``playing=False`` — the icon's tint doesn't change,
                # so firing a frame for the indicator would be a no-op
                # on the client. We emit only on the Playing ↔
                # non-Playing boundary, which matches the icon's
                # observable behaviour and keeps the wire quiet.
                if previous_playing != next_playing:
                    self._emit_chrome_media()
                    self._emit_diagnostic(
                        "playback_changed",
                        row_id,
                        {"playing": self._states[row_id].playing},
                    )
                elif "Metadata" in changed:
                    # Track metadata transitions separately so the
                    # diagnostic timeline reflects track skips without
                    # duplicating chrome-media frames.
                    self._emit_diagnostic(
                        "metadata_changed",
                        row_id,
                        {
                            "title": self._states[row_id].title,
                            "artist": self._states[row_id].artist,
                        },
                    )
                return

    async def read_state(self, row_id: str) -> MediaState | None:
        """Pull the row's :class:`MediaState`.

        A fresh :class:`MediaState` is fetched via ``Properties.GetAll``
        on every call; the v1 browser polls at 1Hz and the Properties
        round-trip is cheap. The cache fills in opportunistically from
        :class:`PropertiesChanged` signals and is consulted first so the
        cache-hit path is observable in tests (issue #52's signaling
        layer requires that ``read_state`` return the cached state
        without re-issuing GetAll when a signal arrived after the
        cache was populated).

        Unknown rows return ``None`` so the pump loop can skip them
        without surfacing a malformed destination on the wire.
        """
        if row_id not in self._owned_names or self._bus is None:
            return None
        app_name = await self._read_identity(row_id)
        cached = self._states.get(row_id)
        if cached is not None:
            # A signal-populated cache entry carries no app_name (the
            # Player interface doesn't expose Identity); stamp the cached
            # root-interface value on so the row header stays populated.
            if cached.app_name != app_name:
                cached = dataclasses.replace(cached, app_name=app_name)
                self._states[row_id] = cached
            return cached
        from dbus_fast.message import Message

        reply = await self._bus.call(
            Message(
                destination=f"{MPRIS_BUS_PREFIX}.{row_id}",
                path=MPRIS_OBJECT_PATH,
                interface=PROPERTIES_INTERFACE,
                member="GetAll",
                signature="s",
                body=[PLAYER_INTERFACE],
            )
        )
        if reply is None or reply.body is None:
            return None
        inner = _unwrap(_first_body_value(reply))
        state, art_url = _properties_to_state(
            inner if isinstance(inner, dict) else {}
        )
        state = dataclasses.replace(state, app_name=app_name)
        # ``art_url`` is already on the state from
        # ``_properties_to_state``; cache the state itself so the
        # proxy can read the URL from the same source the client
        # reads its token (no second cache to drift out of sync —
        # issue #57).
        self._states[row_id] = state
        return state

    def art_url(self, row_id: str) -> str | None:
        """The row's current ``mpris:artUrl`` (one of ``file://`` /
        ``http(s)://`` / ``data:``), or ``None`` when there is no art
        or the row is unknown.

        Reads from the cached ``MediaState`` so the URL is always in
        lockstep with the state — the proxy can never see a token
        without a URL, or vice versa (issue #57).
        """
        if row_id not in self._owned_names:
            return None
        state = self._states.get(row_id)
        if state is None:
            return None
        return state.art_url

    def chrome_media_snapshot(self) -> ChromeMediaState:
        """Compute the current chrome-media snapshot (issue #47).

        Reads ``_owned_names`` (the live row set) and the per-row
        cached ``MediaState.playing`` flag directly — the same
        inputs the listener-driven path uses, just synchronously from
        the snapshot caller. A row whose state hasn't been fetched
        yet counts as not-playing (matching the reducer's rule); the
        caller renders ``available=True, playing=False`` for an
        early-connection session, which is the correct
        conservative state until a real ``Playing`` transition arrives.
        """
        return compute_chrome_media(self._owned_names, self._states)

    async def _read_identity(self, row_id: str) -> str | None:
        """Fetch (and cache) the player's root-interface ``Identity``.

        The human-readable app name GNOME shows above each row lives on
        the ``org.mpris.MediaPlayer2`` root interface, a separate object
        from the Player interface ``read_state`` polls. It's stable for a
        bus name, so it's fetched once and cached; a failed read caches
        ``None`` so a broken player doesn't get re-probed every second.
        """
        if row_id in self._identities:
            return self._identities[row_id]
        identity: str | None = None
        if self._bus is not None:
            from dbus_fast.message import Message

            try:
                reply = await self._bus.call(
                    Message(
                        destination=f"{MPRIS_BUS_PREFIX}.{row_id}",
                        path=MPRIS_OBJECT_PATH,
                        interface=PROPERTIES_INTERFACE,
                        member="GetAll",
                        signature="s",
                        body=[ROOT_INTERFACE],
                    )
                )
                inner = _unwrap(_first_body_value(reply))
                if isinstance(inner, dict):
                    value = inner.get("Identity")
                    if isinstance(value, str) and value:
                        identity = value
            except Exception as exc:
                log.warning("MPRIS Identity read on %s failed: %s", row_id, exc)
        self._identities[row_id] = identity
        return identity

    async def send_command(self, row_id: str, command: str) -> None:
        """Dispatch a browser command to the corresponding MPRIS method.

        Unknown rows, unknown commands, and bus errors are all no-ops
        the server's pump catches and logs — the wire side never sees
        a failure, only a log line.
        """
        if self._bus is None or row_id not in self._owned_names:
            return
        method = _COMMANDS.get(command)
        if method is None:
            return
        from dbus_fast.message import Message

        try:
            await self._bus.call(
                Message(
                    destination=f"{MPRIS_BUS_PREFIX}.{row_id}",
                    path=MPRIS_OBJECT_PATH,
                    interface=PLAYER_INTERFACE,
                    member=method,
                )
            )
            self._emit_diagnostic("command", row_id, {"command": command})
        except Exception as exc:
            log.warning(
                "MPRIS %s.%s on %s failed: %s",
                PLAYER_INTERFACE,
                method,
                row_id,
                exc,
            )
            self._emit_diagnostic(
                "dbus_error",
                row_id,
                {"command": command, "error": repr(exc)},
            )


def _playback_to_playing(
    status: Any, fallback: bool | None = None
) -> bool | None:
    """Map a ``PlaybackStatus`` string to a playing-bool.

    ``"Playing"`` -> ``True``; ``"Paused"`` / ``"Stopped"`` ->
    ``False``; anything else falls back to ``fallback`` (default
    ``None``) so the caller controls whether unknown transitions
    preserve the previous value.
    """
    if status == "Playing":
        return True
    if status in {"Paused", "Stopped"}:
        return False
    return fallback


def _properties_to_state(
    properties: dict[str, Any],
) -> tuple[MediaState, str | None]:
    """Map a Player-interface property dict to ``(state, art_url)``.

    Populates the documented subset (issue #52 acceptance criterion 4
    + issue #57's art handoff): ``PlaybackStatus``, ``Metadata.title``,
    ``Metadata.artist``, ``Metadata.artUrl`` (as a stable ``art_token``
    the client cache-busts an ``<img>`` on), ``DesktopEntry``,
    ``CanGoNext``, ``CanGoPrevious``. Everything else on
    ``MediaState`` is ``None`` so the relay contract stays explicit.
    ``available=True`` whenever the row exists in the owned-names set
    (that's the gate the caller already passed).

    The tuple returns the parsed ``mpris:artUrl`` alongside the
    state so the caller can cache it without re-parsing — the
    proxy's ``/mpris/<row>/art`` route reads the URL itself, and
    recomputing the parse is wasted work (issue #57).
    """
    metadata = properties.get("Metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    title = metadata.get("xesam:title")
    artist_raw = metadata.get("xesam:artist")
    if isinstance(artist_raw, list):
        artist = ", ".join(a for a in artist_raw if isinstance(a, str))
    elif isinstance(artist_raw, str):
        artist = artist_raw
    else:
        artist = None
    desktop_entry = properties.get("DesktopEntry")
    art_url = _parse_mpris_art_url(metadata)
    return MediaState(
        available=True,
        stale=False,
        playing=_playback_to_playing(properties.get("PlaybackStatus")),
        title=title if isinstance(title, str) else None,
        artist=artist,
        desktop_entry=desktop_entry if isinstance(desktop_entry, str) else None,
        can_go_next=properties.get("CanGoNext")
        if isinstance(properties.get("CanGoNext"), bool)
        else None,
        can_go_previous=properties.get("CanGoPrevious")
        if isinstance(properties.get("CanGoPrevious"), bool)
        else None,
        # ``art_token`` is the cache-busting id the client stamps on
        # ``/mpris/<row>/art?token=<token>``; ``art_url`` is the URL
        # the proxy resolves server-side. Both live on the state so a
        # PropertiesChanged that updates the cover is a single
        # ``dataclasses.replace`` — no second cache to keep in sync.
        # ``art_url`` is stripped from the wire in
        # ``Server._media_message`` (issue #57).
        art_token=_art_token(art_url),
        art_url=art_url,
    ), art_url


def _apply_properties_changed(
    previous: MediaState, changed: dict[str, Any]
) -> MediaState:
    """Merge a ``PropertiesChanged.changed`` dict into a previous state.

    Used as the cache-write path so a Player signal updates the
    backend's cached ``MediaState`` without a fresh GetAll. Issue
    #52's acceptance criterion 3 calls for ``MediaState`` updates on
    relevant transitions — track changes (title / artist), playback
    transitions, capability flips. Fields the v1 browser doesn't
    render (rate / volume / position / duration / album / art) are
    ignored.

    The ``Metadata`` dict carries ``xesam:title`` /
    ``xesam:artist`` and the spec's documented field subset, so we
    pick them out of ``changed["Metadata"]`` rather than waiting for
    the next 1-second poll — the row's UI wants to reflect a track
    skip immediately.
    """
    if not changed:
        return previous
    updates: dict[str, Any] = {"stale": False}
    if "PlaybackStatus" in changed:
        updates["playing"] = _playback_to_playing(
            changed["PlaybackStatus"], previous.playing
        )
    metadata = changed.get("Metadata")
    if isinstance(metadata, dict):
        title = metadata.get("xesam:title")
        if isinstance(title, str):
            updates["title"] = title
        artist_raw = metadata.get("xesam:artist")
        if isinstance(artist_raw, list):
            updates["artist"] = ", ".join(a for a in artist_raw if isinstance(a, str))
        elif isinstance(artist_raw, str):
            updates["artist"] = artist_raw
        # ``Metadata.mpris:artUrl`` tracks the cover; re-hash it so a
        # track skip invalidates the client's cached ``<img>`` and
        # refresh the URL itself so the proxy stays in lockstep.
        # ``_parse_mpris_art_url`` returns ``None`` for missing /
        # unknown shapes, so the new token + URL are the right
        # values whatever the new track carries (issue #57).
        art_url = _parse_mpris_art_url(metadata)
        updates["art_token"] = _art_token(art_url)
        updates["art_url"] = art_url
    if "CanGoNext" in changed and isinstance(changed["CanGoNext"], bool):
        updates["can_go_next"] = changed["CanGoNext"]
    if "CanGoPrevious" in changed and isinstance(changed["CanGoPrevious"], bool):
        updates["can_go_previous"] = changed["CanGoPrevious"]
    if "DesktopEntry" in changed and isinstance(changed["DesktopEntry"], str):
        updates["desktop_entry"] = changed["DesktopEntry"]
    if len(updates) == 1:
        # Only the staleness flip; nothing the browser cares about.
        return previous
    return dataclasses.replace(previous, **updates)


def connect_mpris_backend(
    layouts: "LayoutStore",
    bus_factory: "Callable[[BusType], MessageBus]",
) -> DbusMprisBackend | None:
    """Connect a real :class:`DbusMprisBackend` if any layout uses it.

    Users who don't enable the ``mediabrowser`` widget shouldn't pay
    the cost of opening the session bus; this factory checks every
    loaded layout for the widget kind and returns ``None`` when none
    are present. Callers wire the result into the same
    ``Server(mpris_backend=...)`` slot as ``FakeMprisBackend``.

    The check is layout-only (not focus-driven): a user with the
    mediabrowser layout in their config pays the cost once on startup
    and re-uses the same backend on every focus change. The backend's
    idle-while-no-active-mediabrowser-layout behaviour is owned by
    the server's pump gating (``_has_mediabrowser``), not this factory.
    """
    for layout in layouts.layouts:
        if any(getattr(w, "kind", None) == "mediabrowser" for w in layout.widgets):
            return DbusMprisBackend(bus_factory=bus_factory)
    return None
