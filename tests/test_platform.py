"""Tests for ``deckd.platform`` — focus-backend selection + X11 path.

The macOS backend's pure functions live in ``test_platform_macos.py``;
this file pins the cross-platform dispatch and the X11 path that
``default_backend()`` picks when ``XDG_SESSION_TYPE=x11``.

The X11 backend shells out to ``xdotool`` three times per query, so
tests patch ``deckd.platform._run`` to canned stdout strings (the same
seam the GNOME backend uses) rather than touching ``subprocess``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from deckd import platform as plat
from deckd.platform import (
    AppInfo,
    FocusBackendUnavailable,
    GnomeShellFocusBackend,
    RaiseWindowFailed,
    UnimplementedCapability,
    WindowInfo,
    X11FocusBackend,
)


def _reset_module_env(monkeypatch) -> None:
    """Strip the X11 / desktop env vars ``default_backend()`` reads so each
    test starts from a known dispatcher state."""
    for var in ("XDG_SESSION_TYPE",):
        monkeypatch.delenv(var, raising=False)


def test_default_backend_picks_x11_on_x11_session(monkeypatch) -> None:
    """On an X11 session the X11 backend wins over the GNOME default so
    the daemon doesn't try to poll a non-existent GNOME extension — any
    X11 DE (XFCE, MATE, KDE-X11, i3, …) lands here regardless of
    ``XDG_CURRENT_DESKTOP``."""
    _reset_module_env(monkeypatch)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    backend = plat.default_backend()
    assert isinstance(backend, X11FocusBackend)


def test_default_backend_ignores_xdg_current_desktop_when_x11(monkeypatch) -> None:
    """Audit criterion: a non-GNOME X11 session (e.g. XFCE) with no GNOME
    extension installed must not collapse to the GNOME backend.
    ``default_backend()`` only reads ``XDG_SESSION_TYPE``, never
    ``XDG_CURRENT_DESKTOP``, so any X11 DE picks the xdotool path."""
    _reset_module_env(monkeypatch)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "XFCE")
    backend = plat.default_backend()
    assert isinstance(backend, X11FocusBackend)


def test_default_backend_picks_gnome_when_no_session_type(monkeypatch) -> None:
    """No ``XDG_SESSION_TYPE`` (or anything other than ``x11``) falls
    through to the GNOME path — the historical default before the X11
    promotion."""
    _reset_module_env(monkeypatch)
    backend = plat.default_backend()
    assert isinstance(backend, GnomeShellFocusBackend)


def test_default_backend_picks_gnome_on_wayland(monkeypatch) -> None:
    _reset_module_env(monkeypatch)
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    backend = plat.default_backend()
    assert isinstance(backend, GnomeShellFocusBackend)


@pytest.mark.asyncio
async def test_x11_backend_happy_path(monkeypatch) -> None:
    """Three ``xdotool`` calls return window id, class, title. The backend
    populates ``wm_class`` + ``title`` and leaves ``app_id`` ``None``
    (X11 has no app_id analogue; ``wm_class`` is the natural identity)."""
    calls: list[tuple] = []

    async def fake_run(*args: str) -> str:
        calls.append(args)
        if args[0] != "xdotool":
            raise RuntimeError(f"unexpected call: {args!r}")
        sub = args[1]
        if sub == "getactivewindow":
            return "12345678\n"
        if sub == "getwindowclassname":
            return "firefox\n"
        if sub == "getwindowname":
            return "YouTube — Mozilla Firefox\n"
        raise RuntimeError(f"unexpected xdotool subcommand: {sub}")

    monkeypatch.setattr(plat, "_run", fake_run)

    app = await X11FocusBackend().get_active_app()
    assert app == AppInfo(
        app_id=None,
        wm_class="firefox",
        title="YouTube — Mozilla Firefox",
        pid=None,
    )
    assert calls == [
        ("xdotool", "getactivewindow"),
        ("xdotool", "getwindowclassname", "12345678"),
        ("xdotool", "getwindowname", "12345678"),
    ]


@pytest.mark.asyncio
async def test_x11_backend_strips_whitespace_and_empties(monkeypatch) -> None:
    """Trailing newlines get stripped, and a blank class / title collapses
    to ``None`` rather than a stray empty string — same shape as the
    GNOME backend's ``data.get(...)`` lookups."""
    async def fake_run(*args: str) -> str:
        sub = args[1]
        if sub == "getactivewindow":
            return "  42  \n"
        if sub == "getwindowclassname":
            return "   \n"
        if sub == "getwindowname":
            return "  Terminal — bash  \n"
        raise AssertionError(sub)

    monkeypatch.setattr(plat, "_run", fake_run)

    app = await X11FocusBackend().get_active_app()
    assert app.wm_class is None
    assert app.title == "Terminal — bash"


@pytest.mark.asyncio
async def test_x11_backend_missing_xdotool_raises_focus_unavailable(monkeypatch) -> None:
    """When ``xdotool`` is not installed, ``create_subprocess_exec``
    raises ``FileNotFoundError``. The backend must convert that into a
    ``FocusBackendUnavailable`` carrying an install hint, not propagate
    the raw ``FileNotFoundError`` (which the daemon's
    ``run_focus_watcher`` would only log as an opaque ``[Errno 2]``)."""
    async def fake_run(*args: str) -> str:
        raise FileNotFoundError(2, "No such file or directory", "xdotool")

    monkeypatch.setattr(plat, "_run", fake_run)

    with pytest.raises(FocusBackendUnavailable) as excinfo:
        await X11FocusBackend().get_active_app()
    assert "xdotool" in str(excinfo.value)
    assert excinfo.value.hint
    assert "install" in excinfo.value.hint.lower() or "apt" in excinfo.value.hint.lower()


@pytest.mark.asyncio
async def test_x11_backend_xdotool_failure_raises_focus_unavailable(monkeypatch) -> None:
    """``xdotool`` exists but fails (no display, no focused window). The
    raw ``RuntimeError`` from ``_run`` should be wrapped so the watcher
    can surface a focus-backend-specific message rather than the cryptic
    xdotool stderr."""
    async def fake_run(*args: str) -> str:
        raise RuntimeError("xdotool getactivewindow failed: Can't open display")

    monkeypatch.setattr(plat, "_run", fake_run)

    with pytest.raises(FocusBackendUnavailable) as excinfo:
        await X11FocusBackend().get_active_app()
    assert "xdotool" in str(excinfo.value)
    assert excinfo.value.hint


@pytest.mark.asyncio
async def test_focus_backend_unavailable_is_runtime_error() -> None:
    """The daemon's ``run_focus_watcher`` catches ``Exception`` broadly;
    ``FocusBackendUnavailable`` subclasses ``RuntimeError`` so existing
    handlers keep catching it without code changes."""
    err = FocusBackendUnavailable("boom", hint="do something")
    assert isinstance(err, RuntimeError)
    assert err.hint == "do something"
    assert "boom" in str(err)

# ---------------------------------------------------------------------------
# Browser identity (gates the web-app badge)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "app_id, wm_class",
    [
        ("firefox", "firefox"),
        ("org.mozilla.firefox", None),
        ("firefox-esr", None),
        (None, "Navigator"),  # Firefox's X11 wm_class
        ("google-chrome", "Google-chrome"),
        ("chromium", "Chromium-browser"),
        ("brave-browser", None),
        ("microsoft-edge", None),
        ("org.gnome.Epiphany", None),
    ],
)
def test_appinfo_is_browser_true(app_id, wm_class) -> None:
    assert AppInfo(app_id=app_id, wm_class=wm_class, title="x - YouTube").is_browser


@pytest.mark.parametrize(
    "app_id, wm_class",
    [
        ("org.gnome.Console", "org.gnome.Console"),
        ("com.gexperts.Tilix", "Tilix"),
        ("code", "Code"),
        (None, None),
    ],
)
def test_appinfo_is_browser_false(app_id, wm_class) -> None:
    assert not AppInfo(app_id=app_id, wm_class=wm_class, title="x - YouTube").is_browser


# ---------------------------------------------------------------------------
# Stage 2 capability surface (issues #120 / #121 / #126)
# ---------------------------------------------------------------------------


def test_default_capabilities_advertise_focus_only() -> None:
    """The base ``PlatformBackend`` advertises the legacy focus-only
    surface. Backends that implement the enumeration / raise surfaces
    (GNOME today, KWin follow-ups) override to add their flags — the
    server reads this once at startup so a legacy backend keeps
    working unchanged."""
    from deckd.platform import PlatformBackend

    assert PlatformBackend().capabilities() == frozenset({"watch_active_app"})


def test_x11_backend_does_not_advertise_watch_windows() -> None:
    """X11's xdotool surface has no enumeration capability — the
    windows list stays in its "unsupported on this platform" empty
    state (issue #120, decision 8)."""
    assert X11FocusBackend().capabilities() == frozenset({"watch_active_app"})


def test_gnome_backend_advertises_watch_windows() -> None:
    """GNOME today implements both surfaces; the windows watcher is
    started at daemon boot and the chrome list gets a real snapshot."""
    assert GnomeShellFocusBackend().capabilities() == frozenset(
        {"watch_active_app", "watch_windows", "raise_window", "raise_app"}
    )


@pytest.mark.asyncio
async def test_gnome_raise_app_calls_gdbus(monkeypatch) -> None:
    calls: list[tuple] = []

    async def fake_run(*args: str) -> str:
        calls.append(args)
        return "(true,)\n"

    monkeypatch.setattr(plat, "_run", fake_run)
    assert await GnomeShellFocusBackend().raise_app("org.mozilla.firefox")
    assert calls[0][-1] == "org.mozilla.firefox"
    assert any("RaiseApp" in part for part in calls[0])


@pytest.mark.asyncio
async def test_gnome_raise_window_calls_gdbus_and_succeeds_on_true(monkeypatch) -> None:
    """The GNOME backend shells out to ``RaiseWindow`` and treats a
    ``(true,)`` reply as success (no exception) — the id resolved to a
    live window (#122)."""
    calls: list[tuple] = []

    async def fake_run(*args: str) -> str:
        calls.append(args)
        assert args[0] == "gdbus"
        return "(true,)\n"

    monkeypatch.setattr(plat, "_run", fake_run)
    await GnomeShellFocusBackend().raise_window("42")
    # The window id rides as the last positional arg of the gdbus call.
    assert calls[0][-1] == "42"
    assert any("RaiseWindow" in part for part in calls[0])


@pytest.mark.asyncio
async def test_gnome_raise_window_raises_on_false(monkeypatch) -> None:
    """A ``(false,)`` reply means the id retired between enumeration and
    tap; the backend raises :class:`RaiseWindowFailed` carrying the id so
    the server can emit a ``raise_failed`` diagnostic (#73)."""
    async def fake_run(*args: str) -> str:
        return "(false,)\n"

    monkeypatch.setattr(plat, "_run", fake_run)
    with pytest.raises(RaiseWindowFailed) as excinfo:
        await GnomeShellFocusBackend().raise_window("gone")
    assert excinfo.value.window_id == "gone"


@pytest.mark.asyncio
async def test_base_raise_window_raises_unimplemented_capability() -> None:
    """The base backend refuses to raise — only enumerating backends
    implement it. The exception names the missing capability."""
    from deckd.platform import PlatformBackend

    with pytest.raises(UnimplementedCapability) as excinfo:
        await PlatformBackend().raise_window("1")
    assert excinfo.value.capability == "raise_window"


@pytest.mark.asyncio
async def test_base_watch_windows_raises_unimplemented_capability() -> None:
    """The base ``PlatformBackend.watch_windows`` refuses: only backends
    that know how to enumerate (today the GNOME Shell extension)
    override this method. The exception carries the missing capability
    name so a diagnostic can attribute the absence correctly."""
    from deckd.platform import PlatformBackend

    backend = PlatformBackend()
    # The base implementation raises synchronously inside the
    # generator body. Calling the method returns a coroutine which the
    # runtime sees as a plain coroutine (no ``yield`` reached), so
    # ``await`` raises directly — no need for ``async for`` here.
    with pytest.raises(UnimplementedCapability) as excinfo:
        await backend.watch_windows()
    assert excinfo.value.capability == "watch_windows"


def test_unimplemented_capability_is_runtime_error() -> None:
    """Same broad-catch rule as ``FocusBackendUnavailable``: the
    daemon's startup wiring handles the absence via ``capabilities()``
    rather than via ``try/except`` around backend methods, but the
    exception still subclasses ``RuntimeError`` so a defensive
    ``except Exception`` keeps catching it unchanged."""
    err = UnimplementedCapability("boom", capability="watch_windows")
    assert isinstance(err, RuntimeError)
    assert err.capability == "watch_windows"


def test_unimplemented_capability_carries_capability_name() -> None:
    """The capability name rides on the exception so a log line / diag
    entry attributes the absence to the right surface (a backend that
    lacks ``watch_windows`` today may implement ``raise_window``
    tomorrow — distinct diagnostics matter)."""
    err = UnimplementedCapability("nope", capability="raise_window")
    assert err.capability == "raise_window"


def test_window_info_is_frozen_and_carries_seven_keys() -> None:
    """The window identity struct is frozen (hashable for dedupe) and
    carries the seven fields the wire shape publishes (#119 / #120):
    ``window_id`` + three identity keys + ``title`` + ``workspace`` +
    ``minimized``. Missing any of them would break the round-trip
    against the GNOME extension's JSON snapshot."""
    info = WindowInfo(
        window_id="1",
        wm_class="firefox",
        gtk_application_id="org.mozilla.firefox",
        sandboxed_app_id="org.flathub.Firefox",
        title="YouTube",
        workspace=2,
        minimized=False,
    )
    assert info.window_id == "1"
    assert info.wm_class == "firefox"
    assert info.gtk_application_id == "org.mozilla.firefox"
    assert info.sandboxed_app_id == "org.flathub.Firefox"
    assert info.title == "YouTube"
    assert info.workspace == 2
    assert info.minimized is False
    # Frozen: any field reassignment raises.
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        info.window_id = "2"  # type: ignore[misc]


def test_window_info_from_payload_full_shape() -> None:
    """The parser matches the GNOME extension's JSON snapshot
    byte-for-byte: every key the extension publishes lands on the
    right field, including the ``workspace`` int (an index, not a
    MetaWorkspace object on the wire) and the ``minimized`` bool."""
    info = plat._window_info_from_payload(
        {
            "window_id": "42",
            "wm_class": "firefox",
            "app_name": "Firefox",
            "gtk_application_id": "org.mozilla.firefox",
            "sandboxed_app_id": "org.flathub.Firefox",
            "title": "YouTube",
            "workspace": 1,
            "minimized": False,
        }
    )
    assert info == WindowInfo(
        window_id="42",
        wm_class="firefox",
        app_name="Firefox",
        gtk_application_id="org.mozilla.firefox",
        sandboxed_app_id="org.flathub.Firefox",
        title="YouTube",
        workspace=1,
        minimized=False,
    )


def test_focus_wire_fixture_parses_into_both_domain_models() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "focus-wire.json").read_text()
    )
    schema = json.loads(
        (Path(__file__).parent / "fixtures" / "focus-wire.schema.json").read_text()
    )
    _assert_focus_wire_schema(fixture, schema)
    assert plat._app_info_from_payload(fixture["active_window"]) == AppInfo(
        app_id="org.mozilla.firefox",
        wm_class="firefox",
        title="YouTube - Mozilla Firefox",
        pid=4242,
    )
    assert plat._window_info_from_payload(fixture["window"]) == WindowInfo(
        window_id="42",
        wm_class="firefox",
        app_name="Firefox",
        gtk_application_id="org.mozilla.firefox",
        sandboxed_app_id="org.mozilla.Firefox",
        title="YouTube - Mozilla Firefox",
        workspace=1,
        minimized=False,
    )


def _assert_focus_wire_schema(value: dict, schema: dict) -> None:
    assert set(value) == set(schema["required"])
    for name, definition in schema["properties"].items():
        payload = value[name]
        shape = schema["$defs"][definition["$ref"].rsplit("/", 1)[-1]]
        assert set(payload) == set(shape["required"])
        for key, property_schema in shape["properties"].items():
            item = payload[key]
            allowed = property_schema["type"]
            if not isinstance(allowed, list):
                allowed = [allowed]
            assert any(
                item is None
                if kind == "null"
                else isinstance(item, str)
                if kind == "string"
                else isinstance(item, bool)
                if kind == "boolean"
                else isinstance(item, int) and not isinstance(item, bool)
                for kind in allowed
            )


def test_window_info_from_payload_handles_missing_keys() -> None:
    """A future extension revision that drops a field doesn't crash an
    older daemon — every key is read with ``data.get`` so a missing
    field lands as ``None`` / ``False`` and the snapshot still parses.
    Same forward-compat rule as ``_app_info_from_payload``."""
    info = plat._window_info_from_payload({})
    assert info.window_id == ""
    assert info.wm_class is None
    assert info.app_name is None
    assert info.gtk_application_id is None
    assert info.sandboxed_app_id is None
    assert info.title is None
    assert info.workspace is None
    assert info.minimized is False


def test_window_info_from_payload_coerces_window_id_to_str() -> None:
    """``Meta.Window.get_id()`` returns a number on the JS side; the
    extension already stringifies it before publishing the JSON, but
    a future backend that forgets to would still round-trip rather
    than crash — the parser coerces to ``str`` defensively."""
    info = plat._window_info_from_payload({"window_id": 42})
    assert info.window_id == "42"


def test_window_info_from_payload_non_int_workspace_is_none() -> None:
    """A workspace index that doesn't serialise as an int (a string
    from a future backend revision, or a missing field that lands as
    ``None``) yields ``workspace=None`` rather than crashing the
    daemon. Mirrors the same defensive normalisation the rest of the
    parser does for missing keys."""
    info = plat._window_info_from_payload({"workspace": "primary"})
    assert info.workspace is None
