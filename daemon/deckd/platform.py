from __future__ import annotations

import asyncio
import ast
import json
import logging
import os
import sys
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dbus_fast.aio import MessageBus

log = logging.getLogger("deckd.platform")


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
        return _app_info_from_payload(data)


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

        class _DeckdFocusInterface(ServiceInterface):
            def __init__(self) -> None:
                super().__init__(interface_name)

            @dbus_method()
            def GetActiveWindow(self) -> "s":  # noqa: F722 — dbus signature
                return cache.payload

            @dbus_method()
            def UpdateActiveWindow(self, payload: "s") -> "":  # noqa: F722
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
