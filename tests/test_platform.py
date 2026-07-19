"""Tests for ``deckd.platform`` — focus-backend selection + X11 path.

The macOS backend's pure functions live in ``test_platform_macos.py``;
this file pins the cross-platform dispatch and the X11 path that
``default_backend()`` picks when ``XDG_SESSION_TYPE=x11``.

The X11 backend shells out to ``xdotool`` three times per query, so
tests patch ``deckd.platform._run`` to canned stdout strings (the same
seam the GNOME backend uses) rather than touching ``subprocess``.
"""
from __future__ import annotations

import pytest

from deckd import platform as plat
from deckd.platform import (
    AppInfo,
    FocusBackendUnavailable,
    GnomeShellFocusBackend,
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