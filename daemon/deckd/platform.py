from __future__ import annotations

import asyncio
import ast
import json
import logging
import os
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dbus_fast.aio import MessageBus

log = logging.getLogger("deckd.platform")


# Substrings that identify a web browser in an app_id / wm_class, across
# platforms and packaging (flatpak app-ids, X11 wm_class, macOS process
# names). Matched case-insensitively as substrings so ``org.mozilla.firefox``,
# ``firefox-esr`` and ``Navigator`` (Firefox's X11 wm_class) all count. Used
# only to decide whether a title-matched layout is a *web app* (browser) vs a
# desktop app that merely matched by title — see ``AppInfo.is_browser``.
_BROWSER_MARKERS = (
    "firefox",
    "navigator",  # Firefox's X11 wm_class
    "mozilla",
    "librewolf",
    "waterfox",
    "zen",
    "chrome",
    "chromium",
    "brave",
    "edge",
    "vivaldi",
    "opera",
    "safari",
    "epiphany",  # GNOME Web
)


@dataclass(frozen=True)
class AppInfo:
    app_id: str | None
    wm_class: str | None
    title: str | None = None
    pid: int | None = None

    @property
    def identity(self) -> str:
        return self.app_id or self.wm_class or "unknown"

    @property
    def is_browser(self) -> bool:
        """True if this app looks like a web browser.

        Best-effort substring match against a maintained marker list. It only
        gates the *web app* indicator (a browser-focused title match), never
        layout resolution, so a miss just means no globe badge — never a wrong
        layout.
        """
        hay = f"{self.app_id or ''} {self.wm_class or ''}".casefold()
        return any(marker in hay for marker in _BROWSER_MARKERS)


@dataclass(frozen=True)
class WindowInfo:
    """One open window, enumerated by a platform backend (issues #119 /
    #120 / #126).

    Two-layer shape: identity (the three keys the layout matcher
    compares against ``match`` tokens — ``wm_class`` /
    ``gtk_application_id`` / ``sandboxed_app_id`` per #117 / #118) plus
    state (``title`` for raw display fallback; ``workspace`` and
    ``minimized`` are on the wire from the extension per #119 but
    unrendered in v1's chrome list). ``window_id`` is the
    underlying platform window id (e.g. ``Meta.Window.get_id()`` on
    GNOME) stringified for transport — stable for the window's
    lifetime, opaque to the daemon, never parsed by the client. The
    matched label is *not* on this struct: it's a separate
    wire-payload field the daemon produces (backend interface is free
    of layout-pipeline concerns, per #121).
    """

    window_id: str
    wm_class: str | None
    gtk_application_id: str | None
    sandboxed_app_id: str | None
    title: str | None
    workspace: int | None
    minimized: bool


@dataclass(frozen=True)
class SensorReading:
    """One sample from a named sensor source.

    ``value`` is the live reading in the unit the source documents
    (``sensor.unit``). ``stale=True`` marks a reading the source could
    not refresh (sensor disappeared, permission denied) so the client
    can render an "unknown" treatment instead of an arbitrary number
    pinned to the last good value.
    """

    source: str
    value: float
    unit: str
    stale: bool = False


class SensorSource:
    """Named data source the daemon pushes to the client.

    Sources own their own polling cadence: a thermal-zone reader can
    re-read ``/sys`` cheaply on every tick, while a D-Bus signal
    listener just exposes the next event. ``SensorManager`` polls each
    registered source at its declared ``interval_s``; sources that need
    event-driven semantics override :meth:`wait_for_next` instead.

    Implementations must be cheap to construct and side-effect-free at
    construction time — file handles / bus connections open on the
    first call to :meth:`read`.
    """

    #: Short, stable identifier the client references (matches the
    #: ``source`` field on a meter widget in a layout YAML).
    name: str = ""

    #: Human-readable unit the value is in (e.g. ``"°C"``). Pushed
    #: alongside the value so the client can render a label without
    #: hard-coding units per source.
    unit: str = ""

    #: Default poll cadence the SensorManager uses when no per-widget
    #: override is in effect. Sources can override per-poll.
    interval_s: float = 1.0

    def is_available(self) -> bool:
        """True when the source can produce readings in this environment.

        Checked once at manager start; sources that return False are
        skipped and their meter widgets render ``stale=True`` forever.
        The check should be cheap (a stat, an env var read) — no I/O.
        """
        return True

    def read(self) -> SensorReading | None:
        """Return the next reading, or ``None`` to signal "no data".

        ``None`` keeps the manager's last-good value and flips the
        ``stale`` flag on subsequent pushes. Implementations should
        swallow their own exceptions and return ``None`` on failure;
        the manager will log and continue.
        """
        raise NotImplementedError


class SensorManager:
    """Owns a set of :class:`SensorSource` instances keyed by name.

    Built once at daemon startup with the platform-default sources.
    Layouts reference sources by name; the manager hands the same
    ``SensorReading`` to every subscriber so two meter widgets bound
    to the same source see one canonical value rather than two
    polls racing against each other.

    A single :class:`SensorManager` is shared across all sessions
    (the manager is process-scoped state, not session state). When
    no meter widget is interested in a source, the manager stops
    polling it: a phone that's never connected doesn't waste CPU
    re-reading ``/sys``. Polling resumes the moment any session
    binds a widget to the source.
    """

    def __init__(self, sources: list[SensorSource]) -> None:
        self._sources: dict[str, SensorSource] = {s.name: s for s in sources if s.name}
        self._last: dict[str, SensorReading] = {}
        self._subscribers: dict[str, int] = {}  # source -> refcount
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def sources(self) -> list[str]:
        return list(self._sources)

    def has(self, name: str) -> bool:
        return name in self._sources

    def is_available(self, name: str) -> bool:
        src = self._sources.get(name)
        return src is not None and src.is_available()

    def latest(self, name: str) -> SensorReading | None:
        return self._last.get(name)

    def subscribe(self, name: str) -> None:
        """Record one more consumer of ``name``.

        Bumps the refcount; starts the polling task on the 0 -> 1
        transition. Repeated calls are idempotent — only the first
        call per source kicks the task off.
        """
        if name not in self._sources:
            return
        self._subscribers[name] = self._subscribers.get(name, 0) + 1
        if name not in self._tasks:
            self._tasks[name] = asyncio.create_task(self._poll_loop(name))

    def unsubscribe(self, name: str) -> None:
        """Drop one consumer; stop polling when the count hits zero.

        Safe to call more times than :meth:`subscribe`; the count
        floors at zero. The polling task is cancelled on the 1 -> 0
        transition; the cached last reading stays so a re-subscribe
        within the same session doesn't flash ``stale=True``.
        """
        if name not in self._sources:
            return
        self._subscribers[name] = max(0, self._subscribers.get(name, 0) - 1)
        if self._subscribers[name] == 0 and name in self._tasks:
            task = self._tasks.pop(name)
            task.cancel()

    def start(self) -> None:
        """No-op retained for symmetry with :meth:`stop`.

        Sources are started lazily on :meth:`subscribe` so a process
        with no meter subscribers never opens a file handle.
        """
        return None

    def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    async def _poll_loop(self, name: str) -> None:
        src = self._sources[name]
        interval = max(0.05, src.interval_s)
        while True:
            try:
                reading = src.read()
            except Exception as exc:  # sources should swallow, but be defensive
                log.warning("sensor %s raised: %s", name, exc)
                reading = None
            if reading is None:
                last = self._last.get(name)
                if last is not None and not last.stale:
                    self._last[name] = SensorReading(
                        source=name, value=last.value, unit=last.unit, stale=True
                    )
            else:
                self._last[name] = reading
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return


# ---------------------------------------------------------------------------
# psutil-backed sensor sources
# ---------------------------------------------------------------------------
#
# We deliberately dropped the per-platform CPU-temperature readers
# (``/sys/class/thermal`` on Linux, ``osx-cpu-temp`` / ``istats`` shell-outs
# on macOS) in favour of metrics psutil exposes identically on every
# platform: CPU utilisation, memory usage, CPU frequency, battery.
# The trade-off is documented in ``README.md``; the short version is
# that Apple Silicon doesn't expose a stable, unprivileged CPU
# temperature API, and shelling out for one-off helper binaries is a
# support liability that buys us nothing the user can't see in
# Activity Monitor / ``top``.
#
# ``psutil.cpu_percent(interval=None)`` is the canonical non-blocking
# form: it returns the delta between this call and the previous one,
# so a 1s poll cadence gives a fresh per-second percentage. The
# first call returns 0.0 (no baseline yet) — that's correct, not a
# bug.


class PsutilCpuPercentSensorSource(SensorSource):
    """Whole-system CPU utilisation in percent, via ``psutil``.

    Returns a value in ``[0, 100]`` (well, sometimes briefly above
    on busy multi-core systems where psutil's normalisation hasn't
    settled — the meter cell clamps the bar to 100% anyway). The
    interval is ``1.0s`` to match psutil's standard semantics:
    ``cpu_percent(interval=None)`` is delta-since-last-call, so the
    delta window equals the poll cadence. Setting the source
    interval below ~0.5s makes the numbers jittery because the
    sampling window gets too short to be statistically meaningful.
    """

    name = "cpu_percent"
    unit = "%"
    interval_s = 1.0

    def is_available(self) -> bool:
        return True

    def read(self) -> SensorReading | None:
        try:
            import psutil  # type: ignore[import-untyped]

            value = psutil.cpu_percent(interval=None)
        except Exception:
            return None
        # First call after daemon start returns 0.0 (no baseline).
        # We surface that as a normal reading — the bar shows 0%
        # for one second, which is honest.
        return SensorReading(source=self.name, value=float(value), unit=self.unit)


class PsutilMemoryPercentSensorSource(SensorSource):
    """System memory usage in percent, via ``psutil.virtual_memory``.

    This is the ``used / total`` ratio on Linux and macOS. On Windows
    it follows the same definition. The value is a snapshot — no
    sampling window needed — so the interval can be as fast as we
    like; ``1.0s`` is the conservative default that keeps a meter's
    transition animation readable.
    """

    name = "mem_percent"
    unit = "%"
    interval_s = 1.0

    def is_available(self) -> bool:
        return True

    def read(self) -> SensorReading | None:
        try:
            import psutil  # type: ignore[import-untyped]

            value = psutil.virtual_memory().percent
        except Exception:
            return None
        return SensorReading(source=self.name, value=float(value), unit=self.unit)


class PlatformBackend:
    def capabilities(self) -> frozenset[str]:
        """Backend capability flags consumed by the server (issue #121).

        The default base implementation advertises the legacy focus-only
        surface so existing backends (X11, macOS, headless) keep working
        unchanged. Backends that implement the enumeration / raise
        surfaces (GNOME today, KWin follow-ups) override to add their
        flags. The server reads this once at startup; flag absences mean
        the matching wire frames are simply never produced — the chrome
        surfaces the corresponding empty state (issue #120, decision 8).
        """
        return frozenset({"watch_active_app"})

    async def start(self) -> None:
        """Acquire any long-lived resources (a D-Bus bus name, a session
        connection, etc.) the backend needs before the first
        ``get_active_app`` call. Default is a no-op so existing
        backends (GNOME, X11, macOS) keep working unchanged.
        """

    async def stop(self) -> None:
        """Release whatever ``start`` acquired. Default is a no-op for
        the same reason — implementations that own resources override
        this pair together."""

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

    async def watch_windows(
        self, *, interval_s: float = 0.1
    ) -> AsyncIterator[Sequence[WindowInfo]]:
        """Enumerate every open window, polling at ``interval_s``.

        Default implementation refuses: only backends that know how to
        enumerate (today the GNOME Shell extension) advertise the
        ``"watch_windows"`` capability and override this method. The
        server catches :class:`UnimplementedCapability` at startup so a
        legacy backend (X11, macOS, headless) doesn't crash; the chrome
        list simply stays in its "unsupported on this platform" empty
        state (issue #120, decision 8).

        The yielded snapshot is MRU-ordered (most-recently-focused
        first) by the backend's own comparator. The per-window
        ``window_id`` is the platform's stable underlying id (e.g.
        ``Meta.Window.get_id()`` on GNOME, stringified for transport)
        — stable for the window's lifetime, opaque to the daemon and
        the client (#119).
        """
        raise UnimplementedCapability(
            "this backend does not implement watch_windows",
            capability="watch_windows",
        )

    async def raise_window(self, window_id: str) -> None:
        """Raise (focus) the window carrying ``window_id`` (#122).

        The id is the opaque token the backend minted into a
        :meth:`watch_windows` snapshot (#119). Only backends that
        enumerate windows implement this; the default refuses with
        :class:`UnimplementedCapability` so a legacy backend (X11,
        macOS, headless) — which never produced a windows list, so the
        client never offers a tappable row — stays consistent.

        Backends that raise fire-and-forget: a stale/unknown id or a
        transient bus failure is surfaced to the server (which emits a
        diagnostic ``raise_failed`` event, #73), never propagated to
        the user as an error.
        """
        raise UnimplementedCapability(
            "this backend does not implement raise_window",
            capability="raise_window",
        )

    async def raise_app(self, identity: str) -> bool:
        raise UnimplementedCapability(
            "this backend does not implement raise_app",
            capability="raise_app",
        )


class GnomeShellFocusBackend(PlatformBackend):
    BUS_NAME = "org.deckd.Focus"
    OBJECT_PATH = "/org/deckd/Focus"
    INTERFACE = "org.deckd.Focus"

    def capabilities(self) -> frozenset[str]:
        # Stage 2 (#120): enumeration of every open window joins the
        # legacy focus-only surface. The KDE backend inherits this
        # unchanged for the poll path; it advertises the same flag set
        # (the KWin script can feed both ``UpdateActiveWindow`` and a
        # parallel window list, mirroring the GNOME extension's dual
        # ``GetActiveWindow`` / ``ListWindows``).
        return frozenset({"watch_active_app", "watch_windows", "raise_window", "raise_app"})

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
        return _app_info_from_payload(data)

    async def watch_windows(
        self, *, interval_s: float = 0.1
    ) -> AsyncIterator[Sequence[WindowInfo]]:
        """Poll ``org.deckd.Focus.ListWindows()`` at the focus cadence.

        Mirrors :meth:`watch_active_app` for the enumeration surface
        (#120 decision 2 — "polled, no signal"): the extension mints
        fresh ``window_id`` strings on every call so the daemon's
        id→Meta.Window table is the sole source of identity, and we
        evict on close via the daemon's own watcher. The cadence
        matches the focus poll so a newly-opened window appears in the
        chrome list with the same ~100ms envelope as a focus change.

        Errors from the gdbus shell-out (extension not installed,
        session bus unreachable) are logged once and the loop sleeps
        through them — mirrors the focus watcher's behaviour so a
        daemon started before the extension is enabled survives and
        the windows list catches up the moment the bus replies.
        """
        last: Sequence[WindowInfo] | None = None
        while True:
            try:
                snapshot = await self._list_windows_once()
            except Exception as exc:  # surface bus failures without killing the watcher
                log.debug("watch_windows: %s", exc)
                snapshot = []
            if snapshot != last:
                last = snapshot
                yield snapshot
            await asyncio.sleep(interval_s)

    async def _list_windows_once(self) -> list[WindowInfo]:
        out = await _run(
            "gdbus",
            "call",
            "--session",
            "--dest",
            self.BUS_NAME,
            "--object-path",
            self.OBJECT_PATH,
            "--method",
            f"{self.INTERFACE}.ListWindows",
        )
        payload = _parse_single_string_tuple(out)
        data = json.loads(payload)
        return [_window_info_from_payload(entry) for entry in data]

    async def raise_window(self, window_id: str) -> None:
        """Call ``org.deckd.Focus.RaiseWindow(window_id) -> b`` via gdbus.

        Fire-and-forget from the user's perspective: a ``false`` return
        (the id retired between enumeration and tap) is turned into a
        :class:`RaiseWindowFailed` so the server can emit a diagnostic
        ``raise_failed`` event (#73). Bus-level failures (extension
        gone) propagate as the underlying :class:`RuntimeError`; the
        server catches both.
        """
        out = await _run(
            "gdbus",
            "call",
            "--session",
            "--dest",
            self.BUS_NAME,
            "--object-path",
            self.OBJECT_PATH,
            "--method",
            f"{self.INTERFACE}.RaiseWindow",
            window_id,
        )
        if not _parse_single_bool_tuple(out):
            raise RaiseWindowFailed(window_id)

    async def raise_app(self, identity: str) -> bool:
        out = await _run(
            "gdbus", "call", "--session", "--dest", self.BUS_NAME,
            "--object-path", self.OBJECT_PATH, "--method",
            f"{self.INTERFACE}.RaiseApp", identity,
        )
        return _parse_single_bool_tuple(out)


class RaiseWindowFailed(RuntimeError):
    """The backend reached the window manager but it declined to raise
    the window — almost always because ``window_id`` retired between the
    enumeration snapshot and the user's tap (#122). Distinct from a
    bus-level failure so the server can attribute the diagnostic
    ``raise_failed`` event precisely; carries the offending id.
    """

    def __init__(self, window_id: str) -> None:
        super().__init__(f"window manager declined to raise window {window_id!r}")
        self.window_id = window_id


class FocusBackendUnavailable(RuntimeError):
    """Raised by a focus backend when its underlying mechanism (a shell-out
    binary, a D-Bus service, etc.) isn't usable.

    Subclasses ``RuntimeError`` so the daemon's broad
    ``except Exception`` in ``run_focus_watcher`` keeps catching it
    unchanged. Carries a ``hint`` string the CLI / scripts can print to
    point the user at the install / grant step.
    """

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class UnimplementedCapability(RuntimeError):
    """Raised by a backend that doesn't implement an opt-in capability
    (``watch_windows`` / ``raise_window``) — issue #121.

    Deliberately *distinct* from :class:`FocusBackendUnavailable`:
    ``FocusBackendUnavailable`` carries an install hint because the
    user can act on it (install the extension, enable the KWin
    script). ``UnimplementedCapability`` is silent — the backend has
    no path to that capability (X11's ``xdotool`` has no enumeration;
    macOS's osascript / Quartz surface can be extended but isn't in
    scope). The chrome-side treatment is the same either way (no
    ``RunningWindowsMessage`` frame ever lands; the view shows the
    "unsupported on this platform" empty state), so the daemon's
    startup hook swallows this exception and the wire surface stays
    consistent.

    Carries the missing capability name so a diagnostic can attribute
    the absence correctly when more than one capability is in scope.
    """

    def __init__(self, message: str, *, capability: str = "") -> None:
        super().__init__(message)
        self.capability = capability


# ---------------------------------------------------------------------------
# KDE Plasma Wayland backend (issue #31)
#
# Spike #30 picked a KWin-script-pushes-into-a-daemon-owned-cache
# architecture: KWin scripts can only ``callDBus`` OUT (they cannot own
# a D-Bus name or expose inbound methods), so the GNOME extension-side
# pull model inverts for KDE. The daemon owns ``org.deckd.Focus`` on the
# session bus, exposes ``UpdateActiveWindow(s)`` as the KWin script's
# push target, and exposes ``GetActiveWindow() -> s`` so the wire shape
# stays byte-identical to the GNOME extension.
#
# The KDE backend subclasses :class:`GnomeShellFocusBackend` unchanged
# for the poll path (``gdbus call org.deckd.Focus.GetActiveWindow``) so
# the published ``org.deckd.Focus`` interface is exercised on the
# production path, by both the daemon's focus watcher AND
# ``scripts/watch_focus.py`` on KDE. The KDE-specific overrides are
# only ``start`` / ``stop`` which own the bus name and export the
# cache-feeding service. Paying one ``gdbus`` fork per 100ms poll is
# the same precedent the X11 backend sets with its three-``xdotool``
# poll — acceptable on a desktop daemon.
#
# See docs/spike-kde-wayland-focus.md for the full architecture.
# ---------------------------------------------------------------------------


def _app_info_from_payload(data: dict) -> AppInfo:
    """Build an :class:`AppInfo` from the parsed JSON payload the
    ``org.deckd.Focus`` wire shape publishes. Two call sites share this
    (the GNOME backend's gdbus-poll path; the KDE cache's inspection
    hook) so the "ignore unknown keys via ``data.get(...)``" rule stays
    pinned in one place — the KWin script's diagnostic ``uuid`` field
    never desynchronizes from the consumer."""
    return AppInfo(
        app_id=data.get("app_id"),
        wm_class=data.get("wm_class"),
        title=data.get("title"),
        pid=data.get("pid"),
    )


def _window_info_from_payload(data: dict) -> WindowInfo:
    """Build a :class:`WindowInfo` from the parsed JSON payload the
    ``org.deckd.Focus.ListWindows()`` wire shape publishes (issues #119 /
    #120).

    All keys are read via ``data.get(...)`` with sensible defaults so a
    future extension revision that adds or removes a field doesn't crash
    an older daemon — the canonical "ignore unknown keys" rule the
    ``_app_info_from_payload`` helper also follows, so the wire-shape
    contract stays one-way extensible without a coordinated rollout.
    """
    workspace = data.get("workspace")
    return WindowInfo(
        window_id=str(data.get("window_id", "")),
        wm_class=data.get("wm_class"),
        gtk_application_id=data.get("gtk_application_id"),
        sandboxed_app_id=data.get("sandboxed_app_id"),
        title=data.get("title"),
        workspace=int(workspace) if isinstance(workspace, int) else None,
        minimized=bool(data.get("minimized", False)),
    )


class DeckdFocusCache:
    """In-memory snapshot of the KWin script's last pushed window.

    The cache lives in the daemon process and the
    :class:`DeckdFocusDBusService` (which receives KWin pushes via
    ``UpdateActiveWindow``) writes through to the same instance the
    ``GetActiveWindow`` D-Bus method reads from, so external ``gdbus``
    callers — including the :class:`KdeFocusBackend`'s inherited
    ``gdbus`` poll path — see every push.
    """

    EMPTY_PAYLOAD = json.dumps(
        {"app_id": None, "wm_class": None, "title": None, "pid": None}
    )

    def __init__(self, payload: str | None = None) -> None:
        self.payload: str = payload if payload is not None else self.EMPTY_PAYLOAD

    def update(self, payload: str) -> None:
        """Store a new JSON payload. Validates JSON so a malformed KWin
        push (e.g. truncated ``callDBus`` arg) cannot poison the
        last-good snapshot — on parse failure the previous payload is
        preserved and the error propagates to the D-Bus method
        handler, which ``dbus_fast`` turns into an error reply to the
        KWin script. The daemon keeps running; the script's
        ``try/catch`` around ``callDBus`` logs the rejected push and
        the cache holds its prior value until the next focus change.
        """
        json.loads(payload)  # raises json.JSONDecodeError on bad input
        self.payload = payload

    def to_app_info(self) -> AppInfo:
        """Inspection helper for tests / diagnostics. The production
        poll path goes through :class:`GnomeShellFocusBackend`'s
        ``gdbus`` call (inherited unchanged on KDE) which re-derives
        ``AppInfo`` from the wire reply, so this method is not on the
        hot path."""
        return _app_info_from_payload(json.loads(self.payload))


class DeckdFocusDBusService:
    """Session-bus service that owns ``org.deckd.Focus`` on KDE.

    Methods mirror the GNOME Shell extension's contract exactly so
    external consumers (``scripts/watch_focus.py``, ``gdbus`` probes,
    tests) call the same interface on either desktop. Two methods:

    * ``GetActiveWindow() -> s`` — returns the cached JSON payload
      (byte-identical wire shape to the GNOME extension).
    * ``UpdateActiveWindow(s) -> ()`` — the KWin script's push target;
      writes through to the shared :class:`DeckdFocusCache`.

    The class is wrapped lazily so import-time never depends on
    ``dbus_fast`` (a Linux-only dependency the macOS / X11 paths do not
    pull). ``_build_interface`` constructs the real
    :class:`dbus_fast.service.ServiceInterface` subclass the first time
    the service is exported, holding the cache via closure.
    """

    INTERFACE_NAME = "org.deckd.Focus"

    def __init__(self, cache: DeckdFocusCache | None = None) -> None:
        self.cache = cache or DeckdFocusCache()
        self._interface = self._build_interface()

    @property
    def name(self) -> str:
        """The exported interface name (``org.deckd.Focus``). Forwards
        to the ``dbus_fast`` ``ServiceInterface`` instance so the
        wrapper looks indistinguishable from a base-class subclass for
        introspection purposes."""
        return self._interface.name

    def _build_interface(self):
        from dbus_fast.service import ServiceInterface, dbus_method

        interface_name = self.INTERFACE_NAME
        cache = self.cache

        class _DeckdFocusInterface(ServiceInterface):  # type: ignore[misc]
            def __init__(self) -> None:
                super().__init__(interface_name)

            @dbus_method()
            def GetActiveWindow(self) -> "s":  # type: ignore[name-defined]
                return cache.payload

            @dbus_method()
            def UpdateActiveWindow(self, payload: "s") -> "":  # type: ignore[name-defined]
                cache.update(payload)

        return _DeckdFocusInterface()

    @property
    def interface(self):
        """The exported ``dbus_fast`` interface object (a
        ``ServiceInterface`` instance)."""
        return self._interface


class KdeFocusBackend(GnomeShellFocusBackend):
    """KDE Plasma Wayland focus backend.

    Subclasses :class:`GnomeShellFocusBackend` unchanged for the poll
    path so the daemon's focus watcher and ``scripts/watch_focus.py``
    both exercise the published ``org.deckd.Focus.GetActiveWindow``
    method (the wire-shape symmetry spike #30 explicitly mandated).
    The KDE-specific overrides are only the ``start`` / ``stop`` pair:

    * ``start`` connects to the session bus, requests the
      ``org.deckd.Focus`` name with ``NameFlag.REPLACE_EXISTING``, and
      exports the :class:`DeckdFocusDBusService` at ``/org/deckd/Focus``
      so the KWin script has a push target. Failures (no session bus,
      name already owned, ``dbus_fast`` errors) surface as
      :class:`FocusBackendUnavailable` carrying the install hint — the
      daemon keeps running on the default layout rather than crashing.
    * ``stop`` releases the name and disconnects. Safe to call after a
      failed start.

    ``get_active_app`` is inherited from :class:`GnomeShellFocusBackend`
    and shells out to ``gdbus`` on every poll, exactly as the GNOME
    backend does. The cost (one ``gdbus`` fork per 100ms) is comparable
    to the X11 backend's three ``xdotool`` forks per poll — accepted for
    wire-shape parity.
    """

    KDE_INSTALL_HINT = (
        "On KDE Plasma Wayland, the deckd daemon owns the org.deckd.Focus "
        "session-bus name and a KWin script pushes the focused window into "
        "it. Install and enable the KWin focus bridge:\n"
        "  just install-focus-kwin\n"
        "Without the script the cache stays on its empty default and the "
        "daemon holds the default layout until the next window activation."
    )

    def __init__(
        self,
        *,
        cache: DeckdFocusCache | None = None,
        bus_factory: "Callable[[], MessageBus] | None" = None,
    ) -> None:
        # GnomeShellFocusBackend has no __init__ of its own, so no
        # super().__init__() dispatch is needed here.
        self._cache = cache or DeckdFocusCache()
        self._bus_factory = bus_factory
        self._service: DeckdFocusDBusService | None = None
        self._bus: "MessageBus | None" = None
        self._started = False

    @property
    def cache(self) -> DeckdFocusCache:
        """The shared window cache. The KWin script's
        ``UpdateActiveWindow`` pushes write through here; the published
        ``GetActiveWindow`` method reads from it (and so does the KDE
        backend's inherited ``gdbus`` poll path, via the bus)."""
        return self._cache

    async def start(self) -> None:
        """Own ``org.deckd.Focus`` and export the push surface.

        Idempotent: a second call after a successful start is a no-op
        (avoids double-registration on retry paths). Wrapped in
        :class:`FocusBackendUnavailable` so the daemon's broad
        ``except Exception`` handler in ``run_focus_watcher`` surfaces
        the install hint instead of an opaque ``dbus_fast`` traceback.
        On success, logs a one-shot hint pointing at the
        ``install-focus-kwin`` recipe — analogous to the GNOME backend's
        failure-mode log (which fires when ``org.deckd.Focus`` isn't
        owned because the extension isn't installed): KDE doesn't have
        that failure mode (the daemon owns the name itself), so the
        hint is logged proactively the first time the bus is owned.
        """
        if self._started:
            return
        try:
            bus = await self._connect_bus()
            service = DeckdFocusDBusService(self._cache)
            bus.export(self.OBJECT_PATH, service.interface)
            from dbus_fast import NameFlag

            await bus.request_name(self.BUS_NAME, NameFlag.REPLACE_EXISTING)
        except Exception as exc:
            raise FocusBackendUnavailable(
                f"KDE focus backend could not own {self.BUS_NAME} on the "
                f"session bus: {exc}",
                hint=self.KDE_INSTALL_HINT,
            ) from exc
        self._bus = bus
        self._service = service
        self._started = True
        log.info(
            "KDE focus backend: owning %s at %s; "
            "waiting for KWin script pushes. "
            "hint: run `just install-focus-kwin` if no focus events arrive.",
            self.BUS_NAME,
            self.OBJECT_PATH,
        )

    async def _connect_bus(self) -> "MessageBus":
        if self._bus_factory is not None:
            bus = self._bus_factory()
        else:
            from dbus_fast import BusType
            from dbus_fast.aio import MessageBus

            bus = MessageBus(bus_type=BusType.SESSION)
        if not getattr(bus, "connected", False):
            await bus.connect()
        return bus

    async def stop(self) -> None:
        """Release the bus name and disconnect. Safe to call after a
        failed start, or never to have started."""
        if self._bus is not None:
            try:
                await self._bus.release_name(self.BUS_NAME)
            except Exception as exc:
                log.debug("release_name on stop failed: %s", exc)
            try:
                self._bus.disconnect()
            except Exception as exc:
                log.debug("bus disconnect on stop failed: %s", exc)
        self._bus = None
        self._service = None
        self._started = False


class X11FocusBackend(PlatformBackend):
    """Active-window via ``xdotool``. Supported on any X11 session — no
    platform extension, no D-Bus service, no permissions beyond
    ``xdotool`` on ``$PATH``. Surfaces ``FocusBackendUnavailable`` with
    an install hint when ``xdotool`` is missing or cannot reach the
    display, so the daemon and CLI log something actionable instead of
    a raw ``[Errno 2]``.
    """

    X11_INSTALL_HINT = (
        "xdotool is required for focus detection on X11 — "
        "install it with your distro's package manager "
        "(apt / dnf / pacman)."
    )
    X11_RUNTIME_HINT = (
        "check that an X session is active (DISPLAY set, X server "
        "reachable); on a headless box the focus watcher is unavailable."
    )

    async def get_active_app(self) -> AppInfo:
        try:
            window_id = (await _run("xdotool", "getactivewindow")).strip()
            wm_class = (await _run("xdotool", "getwindowclassname", window_id)).strip() or None
            title = (await _run("xdotool", "getwindowname", window_id)).strip() or None
        except FileNotFoundError as exc:
            raise FocusBackendUnavailable(
                f"xdotool not found: {exc}",
                hint=self.X11_INSTALL_HINT,
            ) from exc
        except RuntimeError as exc:
            raise FocusBackendUnavailable(
                f"xdotool focus query failed: {exc}",
                hint=self.X11_RUNTIME_HINT,
            ) from exc
        return AppInfo(app_id=None, wm_class=wm_class, title=title)


def default_backend() -> PlatformBackend:
    if sys.platform == "darwin":
        from .platform_macos import MacFocusBackend

        return MacFocusBackend()
    if os.environ.get("XDG_SESSION_TYPE") == "x11":
        return X11FocusBackend()
    if _is_kde_wayland_session():
        return KdeFocusBackend()
    return GnomeShellFocusBackend()


def default_sensor_manager() -> "SensorManager":
    """Build the platform-default :class:`SensorManager`.

    Every source here is psutil-backed, so the same set works on
    Linux, macOS Intel, and Apple Silicon without per-OS install
    steps or shell-outs. We register every source the manager knows
    about; per-widget subscriptions are gated by
    :meth:`SensorSource.is_available` so a sensor that can't read
    (e.g. ``battery`` on a desktop) just stays quiet rather than
    spamming None.

    Trade-off documented in README.md: dropping CPU temperature
    because Apple Silicon doesn't expose one without root + a
    privileged helper + a parser for Apple's undocumented format.
    CPU utilisation and memory percent cover the same "is the box
    healthy" use case and work everywhere.
    """
    return SensorManager(
        [
            PsutilCpuPercentSensorSource(),
            PsutilMemoryPercentSensorSource(),
        ]
    )


def _is_kde_wayland_session() -> bool:
    """Detect a KDE Plasma Wayland session.

    Spike #30's recommendation: the KWin-script push architecture only
    makes sense on Plasma Wayland (a KWin script runs inside the
    compositor). KDE-X11 falls back to the cross-DE xdotool path
    (#29). ``XDG_CURRENT_DESKTOP`` is colon-separated by spec, so we
    split and uppercase-compare — distro variants write ``KDE`` / ``kde``
    / ``GNOME:KDE`` interchangeably.
    """
    if os.environ.get("XDG_SESSION_TYPE") != "wayland":
        return False
    desktops = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return "KDE" in {part.upper() for part in desktops.split(":") if part}


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


def _parse_single_bool_tuple(value: str) -> bool:
    """Parse gdbus's ``(true,)`` / ``(false,)`` single-boolean reply.

    gdbus prints GVariant booleans lowercase (``true``/``false``), which
    ``ast.literal_eval`` can't parse, so normalise to Python's
    capitalised literals first — same one-arg-tuple discipline as
    :func:`_parse_single_string_tuple`.
    """
    normalised = value.replace("true", "True").replace("false", "False")
    parsed = ast.literal_eval(normalised)
    if not isinstance(parsed, tuple) or len(parsed) != 1 or not isinstance(parsed[0], bool):
        raise RuntimeError(f"unexpected gdbus response: {value}")
    return parsed[0]
