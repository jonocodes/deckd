"""Tests for the KDE-Wayland focus backend (:issue:`31`).

Mirrors the shape of :mod:`tests.test_platform` (which pins GNOME + X11
dispatch + the X11 backend's happy / failure paths) for the KDE side:

* the cache that holds the latest push from the KWin script,
* the D-Bus service that exposes ``org.deckd.Focus`` to the session bus,
* the :class:`KdeFocusBackend` that owns the bus name and feeds the
  cache to the focus watcher, and
* ``default_backend()`` dispatch on ``XDG_CURRENT_DESKTOP=KDE`` +
  ``XDG_SESSION_TYPE=wayland``.

D-Bus is faked (no real session bus is touched). The backend sees a
``FakeKdeBus`` that records ``export`` / ``request_name`` calls; the
service is exercised through the cache seam, not through a live
``dbus_fast`` socket.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from deckd import platform as plat
from deckd.platform import (
    AppInfo,
    DeckdFocusCache,
    DeckdFocusDBusService,
    FocusBackendUnavailable,
    GnomeShellFocusBackend,
    KdeFocusBackend,
    PlatformBackend,
    X11FocusBackend,
)


# ---------------------------------------------------------------------------
# DeckdFocusCache — the in-memory window snapshot fed by the KWin script
# ---------------------------------------------------------------------------


def test_cache_default_payload_is_all_nulls() -> None:
    cache = DeckdFocusCache()
    data = json.loads(cache.payload)
    assert data == {
        "app_id": None,
        "wm_class": None,
        "title": None,
        "pid": None,
    }


def test_cache_default_playback_to_app_info_keeps_all_none() -> None:
    app = DeckdFocusCache().to_app_info()
    assert app == AppInfo(app_id=None, wm_class=None, title=None, pid=None)


def test_cache_update_stores_payload_and_renders_app_info() -> None:
    cache = DeckdFocusCache()
    cache.update(
        json.dumps(
            {
                "app_id": "org.kde.dolphin",
                "wm_class": "dolphin",
                "title": "Dolphin — Home",
                "pid": 4242,
            }
        )
    )
    app = cache.to_app_info()
    assert app == AppInfo(
        app_id="org.kde.dolphin",
        wm_class="dolphin",
        title="Dolphin — Home",
        pid=4242,
    )


def test_cache_update_rejects_invalid_json_without_overwriting_existing() -> None:
    """A malformed / hostile push from the KWin script must not corrupt
    the previous good payload — the daemon keeps the last-good cache
    until a parseable push arrives."""
    cache = DeckdFocusCache()
    cache.update(json.dumps({"app_id": "kcalc", "wm_class": "kcalc", "title": None, "pid": None}))
    with pytest.raises(json.JSONDecodeError):
        cache.update("not-json")
    # The cache still holds the previous good payload, not "not-json".
    assert json.loads(cache.payload)["app_id"] == "kcalc"


def test_cache_update_missing_keys_render_as_none() -> None:
    """The KWin script may omit keys on focus-loss (a null push). The
    cache tolerates partial JSON via ``data.get(...)`` mirroring the
    GNOME backend's lookups."""
    cache = DeckdFocusCache()
    cache.update(json.dumps({"app_id": "firefox", "wm_class": "firefox"}))
    app = cache.to_app_info()
    assert app.app_id == "firefox"
    assert app.wm_class == "firefox"
    assert app.title is None
    assert app.pid is None


def test_cache_identity_falls_back_to_wm_class() -> None:
    """An XWayland window without a desktop-file hint lands with
    ``app_id=None``; the existing ``AppInfo.identity`` fallback covers
    it (matches the GNOME backend's behaviour)."""
    cache = DeckdFocusCache()
    cache.update(json.dumps({"app_id": None, "wm_class": "firefox", "title": "YT", "pid": 99}))
    assert cache.to_app_info().identity == "firefox"


# ---------------------------------------------------------------------------
# DeckdFocusDBusService — the org.deckd.Focus service interface
# ---------------------------------------------------------------------------


def test_dbus_service_interface_name_matches_gnome_wire() -> None:
    svc = DeckdFocusDBusService()
    assert svc.name == "org.deckd.Focus"


def test_dbus_service_exposes_get_and_update_methods() -> None:
    from dbus_fast.service import ServiceInterface

    svc = DeckdFocusDBusService()
    methods = {m.name: m for m in ServiceInterface._get_methods(svc.interface)}
    assert "GetActiveWindow" in methods
    assert "UpdateActiveWindow" in methods
    # Wire-shape contract with the KWin script + the GNOME extension:
    # GetActiveWindow returns one string (the JSON tuple's payload),
    # UpdateActiveWindow accepts one string (the JSON push).
    assert methods["GetActiveWindow"].in_signature == ""
    assert methods["GetActiveWindow"].out_signature == "s"
    assert methods["UpdateActiveWindow"].in_signature == "s"
    assert methods["UpdateActiveWindow"].out_signature == ""


def test_dbus_service_get_returns_cache_payload() -> None:
    cache = DeckdFocusCache()
    cache.update(json.dumps({"app_id": "x", "wm_class": "y", "title": None, "pid": 7}))
    svc = DeckdFocusDBusService(cache=cache)
    # dbus_fast's @dbus_method wraps the fn so a direct call discards
    # the result; the original fn lives on the introspected method's
    # `fn` slot and is exactly what dbus_fast invokes when a client
    # calls the method over the bus.
    from dbus_fast.service import ServiceInterface

    method = next(
        m
        for m in ServiceInterface._get_methods(svc.interface)
        if m.name == "GetActiveWindow"
    )
    assert method.fn(svc.interface) == cache.payload


def test_dbus_service_update_writes_through_to_shared_cache() -> None:
    cache = DeckdFocusCache()
    svc = DeckdFocusDBusService(cache=cache)
    from dbus_fast.service import ServiceInterface

    method = next(
        m
        for m in ServiceInterface._get_methods(svc.interface)
        if m.name == "UpdateActiveWindow"
    )
    method.fn(
        svc.interface,
        json.dumps({"app_id": "k", "wm_class": "k", "title": None, "pid": 1}),
    )
    assert json.loads(cache.payload)["app_id"] == "k"


# ---------------------------------------------------------------------------
# KdeFocusBackend — the gdbus poll path is inherited from
# GnomeShellFocusBackend; we pin it against a fake `_run` the same way
# ``test_x11_backend_happy_path`` pins the X11 backend. This is the
# "mirrors the GNOME backend's test shape" the issue's acceptance
# criterion asks for — the KDE-specific surface the backend ADDS over
# GNOME (owning the bus name + exporting the cache service) is pinned
# by the start / stop tests below.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kde_backend_get_active_app_polls_org_deckd_focus_via_gdbus(
    monkeypatch,
) -> None:
    """The KDE backend inherits ``get_active_app`` verbatim from
    ``GnomeShellFocusBackend``: ``gdbus call --session --dest
    org.deckd.Focus --object-path /org/deckd/Focus --method
    org.deckd.Focus.GetActiveWindow`` returns a single-string tuple
    wrapping the cache's JSON. Pin the wire-shape contract by faking
    ``_run`` (the same seam the X11 happy-path test uses)."""
    calls: list[str] = [""]

    async def fake_run(*args: str) -> str:
        calls[0] = " ".join(args)
        # gdbus returns a single-string tuple; _parse_single_string_tuple
        # unwraps the outer parens with ast.literal_eval, then json.loads
        # the inner string. Build the payload as a real Python tuple
        # repr (ast parses it back) — keeps the test free of nested
        # quote-escape puzzles.
        payload = json.dumps(
            {
                "app_id": "org.kde.dolphin",
                "wm_class": "dolphin",
                "title": "Dolphin\u2014Home",
                "pid": 4242,
            }
        )
        return repr((payload,))

    monkeypatch.setattr(plat, "_run", fake_run)
    app = await KdeFocusBackend().get_active_app()
    assert app == AppInfo(
        app_id="org.kde.dolphin",
        wm_class="dolphin",
        title="Dolphin\u2014Home",
        pid=4242,
    )
    assert "gdbus" in calls[0]
    assert "org.deckd.Focus" in calls[0]
    assert "/org/deckd/Focus" in calls[0]
    assert "GetActiveWindow" in calls[0]


@pytest.mark.asyncio
async def test_kde_backend_get_active_app_default_cache_round_trips_all_none(
    monkeypatch,
) -> None:
    """Before any KWin push lands, ``GetActiveWindow`` returns the
    cache's empty default (all-nulls JSON); the inherited gdbus-poll
    parse maps that back to a fully-null ``AppInfo`` so the daemon
    starts on the default layout without surprises."""

    async def fake_run(*args: str) -> str:
        return repr((DeckdFocusCache.EMPTY_PAYLOAD,))

    monkeypatch.setattr(plat, "_run", fake_run)
    app = await KdeFocusBackend().get_active_app()
    assert app == AppInfo(None, None, None, None)


@pytest.mark.asyncio
async def test_kde_backend_is_a_platform_backend_for_dispatch_compat() -> None:
    assert isinstance(KdeFocusBackend(), PlatformBackend)
    # Subclasses GnomeShellFocusBackend unchanged for the poll path —
    # the wire-shape symmetry spike #30 mandated.
    assert issubclass(KdeFocusBackend, GnomeShellFocusBackend)
    # start / stop are the new KDE-specific overrides; the base no-ops
    # are still the GNOME backend's defaults.
    assert KdeFocusBackend.start is not PlatformBackend.start
    assert KdeFocusBackend.stop is not PlatformBackend.stop
    # get_active_app is inherited from GNOME verbatim — no override.
    assert KdeFocusBackend.get_active_app is GnomeShellFocusBackend.get_active_app


# ---------------------------------------------------------------------------
# KdeFocusBackend.start — owning org.deckd.Focus on the session bus
# ---------------------------------------------------------------------------


class FakeKdeBus:
    """Stand-in for ``dbus_fast.aio.MessageBus`` exercising the export /
    name-ownership path without touching a real session bus. Exposes
    just the surface the backend touches."""

    def __init__(
        self,
        *,
        fail_connect: bool = False,
        fail_request_name: bool = False,
    ) -> None:
        self.connected = False
        self.disconnected = False
        self.exported: list[tuple[str, object]] = []
        self.requested_names: list[tuple[str, int]] = []
        self.released_names: list[str] = []
        self._fail_connect = fail_connect
        self._fail_request = fail_request_name

    async def connect(self) -> "FakeKdeBus":
        if self._fail_connect:
            raise OSError("no session bus available")
        self.connected = True
        return self

    def export(self, path: str, interface: object) -> None:
        self.exported.append((path, interface))

    async def request_name(self, name: str, flags: int = 0) -> int:
        self.requested_names.append((name, flags))
        if self._fail_request:
            raise RuntimeError("name already owned by another process")
        return 1  # DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER

    async def release_name(self, name: str) -> int:
        self.released_names.append(name)
        return 1

    def disconnect(self) -> None:
        self.disconnected = True


@pytest.mark.asyncio
async def test_kde_backend_start_owns_bus_name_and_exports_service() -> None:
    bus = FakeKdeBus()
    backend = KdeFocusBackend(bus_factory=lambda: bus)
    await backend.start()

    assert backend._started is True
    assert bus.connected is True
    assert len(bus.exported) == 1
    path, exported = bus.exported[0]
    assert path == "/org/deckd/Focus"
    # The exported object is the dbus_fast ServiceInterface instance, not
    # the wrapper itself — the wrapper keeps the cache visible at the
    # Python level and the interface.__dict__ tells the session bus
    # what methods to serve.
    assert exported is backend._service.interface
    from dbus_fast import NameFlag

    assert bus.requested_names == [("org.deckd.Focus", NameFlag.REPLACE_EXISTING)]


@pytest.mark.asyncio
async def test_kde_backend_start_is_idempotent() -> None:
    bus = FakeKdeBus()
    backend = KdeFocusBackend(bus_factory=lambda: bus)
    await backend.start()
    await backend.start()  # second call is a no-op
    assert len(bus.exported) == 1
    assert len(bus.requested_names) == 1


@pytest.mark.asyncio
async def test_kde_backend_start_failure_raises_focus_unavailable_with_install_hint() -> None:
    backend = KdeFocusBackend(bus_factory=lambda: FakeKdeBus(fail_connect=True))
    with pytest.raises(FocusBackendUnavailable) as excinfo:
        await backend.start()
    assert "org.deckd.Focus" in str(excinfo.value)
    assert excinfo.value.hint
    assert "install-focus-kwin" in excinfo.value.hint


@pytest.mark.asyncio
async def test_kde_backend_start_failure_on_request_name_raises_focus_unavailable() -> None:
    backend = KdeFocusBackend(bus_factory=lambda: FakeKdeBus(fail_request_name=True))
    with pytest.raises(FocusBackendUnavailable):
        await backend.start()


@pytest.mark.asyncio
async def test_kde_backend_stop_releases_name_and_disconnects() -> None:
    bus = FakeKdeBus()
    backend = KdeFocusBackend(bus_factory=lambda: bus)
    await backend.start()
    await backend.stop()
    assert bus.disconnected is True
    assert bus.released_names == ["org.deckd.Focus"]


@pytest.mark.asyncio
async def test_kde_backend_stop_is_safe_when_never_started() -> None:
    backend = KdeFocusBackend(bus_factory=lambda: FakeKdeBus())
    await backend.stop()  # nothing to release; should not raise


@pytest.mark.asyncio
async def test_kde_backend_start_logs_install_hint_on_success(caplog) -> None:
    """Acceptance criterion 3 of issue #31: when the KWin focus source is
    missing the backend must log a clear install hint and not crash the
    daemon. KDE doesn't have the GNOME failure mode (the daemon owns
    the org.deckd.Focus name itself, so ``gdbus call`` doesn't fail
    with "service unknown" when the script is absent). Instead the
    backend logs the install hint proactively on successful start so a
    user who forgot to run ``install-focus-kwin`` sees the remedy
    even though the bus ownership itself succeeded."""
    import logging

    bus = FakeKdeBus()
    backend = KdeFocusBackend(bus_factory=lambda: bus)
    with caplog.at_level(logging.INFO, logger="deckd.platform"):
        await backend.start()
    hint_records = [r for r in caplog.records if "install-focus-kwin" in r.getMessage()]
    assert hint_records, "expected the install-focus-kwin hint to be logged on start"
    assert hint_records[0].levelno == logging.INFO


# ---------------------------------------------------------------------------
# default_backend() dispatch — KDE-Wayland picks Kde, KDE-X11 still picks X11
# ---------------------------------------------------------------------------


def _reset_module_env(monkeypatch) -> None:
    for var in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP"):
        monkeypatch.delenv(var, raising=False)


def test_default_backend_picks_kde_on_kde_wayland(monkeypatch) -> None:
    _reset_module_env(monkeypatch)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    backend = plat.default_backend()
    assert isinstance(backend, KdeFocusBackend)


def test_default_backend_picks_x11_on_kde_x11(monkeypatch) -> None:
    """KDE-X11 still falls into the xdotool path (the X11 promotion
    from #29), not the KWin-script path — KWin scripts are only needed
    on Wayland where clients can't see each other."""
    _reset_module_env(monkeypatch)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    backend = plat.default_backend()
    assert isinstance(backend, X11FocusBackend)


def test_default_backend_falls_through_to_gnome_when_kde_but_not_wayland(
    monkeypatch,
) -> None:
    """A KDE session whose session type is unset (rare headless dev
    box) does not become the KWin backend; the historical GNOME default
    keeps the daemon usable. The KDE backend needs Wayland to be a
    sensible KWin-script host."""
    _reset_module_env(monkeypatch)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    backend = plat.default_backend()
    assert isinstance(backend, GnomeShellFocusBackend)


def test_default_backend_picks_kde_when_xdg_current_desktop_has_multiple_entries(
    monkeypatch,
) -> None:
    """``XDG_CURRENT_DESKTOP`` is colon-separated by spec; some distros
    set e.g. ``KDE:GNOME``. The dispatch splits on ``:`` so KDE anywhere
    in the list picks the KWin backend on Wayland."""
    _reset_module_env(monkeypatch)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME:KDE")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    backend = plat.default_backend()
    assert isinstance(backend, KdeFocusBackend)


def test_default_backend_kde_dispatch_is_case_insensitive(monkeypatch) -> None:
    """Plasma variants may write ``kde`` lowercase in some setups; the
    check compares uppercased so ``KDE`` / ``kde`` / ``Kde`` all match."""
    _reset_module_env(monkeypatch)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "kde")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    backend = plat.default_backend()
    assert isinstance(backend, KdeFocusBackend)