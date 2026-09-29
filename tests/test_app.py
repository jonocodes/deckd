"""Tests for the macOS app-bundle helpers (issue #165).

The AppKit wrapper itself (``packaging/macos/menubar.py``) is macOS-only and
not exercised here; everything platform-independent lives in
``deckd.macos_app`` so it runs on the Linux dev/CI hosts.
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from deckd import macos_app


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_resource_root_dev_fallback(monkeypatch) -> None:
    monkeypatch.delattr(macos_app.sys, "_MEIPASS", raising=False)
    root = macos_app.resource_root()
    assert (root / "daemon" / "deckd").is_dir()
    assert (root / "pyproject.toml").is_file()


def test_resource_root_frozen(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(macos_app.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert macos_app.resource_root() == tmp_path


def test_menubar_icon_paths_frozen_layout(tmp_path: Path) -> None:
    # Frozen: the spec drops the template PNGs at the bundle root.
    _write(tmp_path / "deckd-menubar.png", "")
    assert macos_app.menubar_icon_paths(tmp_path) == (
        tmp_path / "deckd-menubar.png",
        tmp_path / "deckd-menubar@2x.png",
    )


def test_menubar_icon_paths_source_layout(tmp_path: Path) -> None:
    # Source checkout: the PNGs sit beside the spec in packaging/macos.
    _write(tmp_path / "packaging" / "macos" / "deckd-menubar.png", "")
    assert macos_app.menubar_icon_paths(tmp_path) == (
        tmp_path / "packaging" / "macos" / "deckd-menubar.png",
        tmp_path / "packaging" / "macos" / "deckd-menubar@2x.png",
    )


def test_menubar_icon_paths_absent(tmp_path: Path) -> None:
    assert macos_app.menubar_icon_paths(tmp_path) is None


def test_seed_layouts_first_run_then_noop(tmp_path: Path) -> None:
    src = tmp_path / "bundled"
    _write(src / "default.yaml", "id: default\n")
    overlay = tmp_path / "bundled.macos"
    _write(overlay / "firefox.yaml", "id: firefox\n")
    dest = tmp_path / "support" / "layouts"

    assert macos_app.seed_layouts(src, dest, overlay=overlay) is True
    assert (dest / "default.yaml").read_text() == "id: default\n"
    # The overlay lands beside the layouts dir, where the daemon looks.
    assert (dest.parent / "layouts.macos" / "firefox.yaml").is_file()

    # A user's edits survive the next run: an existing dir is never re-seeded.
    (dest / "default.yaml").write_text("id: default\nedited: true\n")
    assert macos_app.seed_layouts(src, dest, overlay=overlay) is False
    assert "edited" in (dest / "default.yaml").read_text()


def test_bundle_version_prefers_env_override(monkeypatch, tmp_path: Path) -> None:
    # The release workflow passes the git tag (minus its `v`) this way, so a
    # rough CalVer tag is fine — no PEP 440 normalisation applies here.
    monkeypatch.setenv("DECKD_VERSION", "2026.09.23")
    assert macos_app.bundle_version(tmp_path / "pyproject.toml") == "2026.09.23"


def test_bundle_version_falls_back_to_pyproject(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DECKD_VERSION", "   ")
    pyproject = tmp_path / "pyproject.toml"
    _write(pyproject, '[project]\nname = "deckd"\nversion = "1.2.3"\n')
    assert macos_app.bundle_version(pyproject) == "1.2.3"


def test_bundle_info_plist_declares_tcc_usage() -> None:
    plist = macos_app.bundle_info_plist("1.2.3")
    assert plist["CFBundleShortVersionString"] == "1.2.3"
    assert plist["CFBundleVersion"] == "1.2.3"
    # Menu-bar only: no Dock icon, no main window.
    assert plist["LSUIElement"] is True
    # The daemon drives System Events via osascript; without this string
    # macOS denies the Apple Event with no prompt (issue #165).
    assert plist["NSAppleEventsUsageDescription"]


def test_bundle_info_plist_has_no_empty_strings() -> None:
    # An empty usage description suppresses the TCC prompt, so none of the
    # string values may be blank.
    for key, value in macos_app.bundle_info_plist("0.0.1").items():
        if isinstance(value, str):
            assert value.strip(), key


def test_app_argv_defaults_to_localhost(tmp_path: Path) -> None:
    argv = macos_app.app_argv(
        layouts_dir=tmp_path / "layouts", client_dist=tmp_path / "web"
    )
    assert "--bind" not in argv
    assert argv[argv.index("--layouts-dir") + 1] == str(tmp_path / "layouts")
    assert argv[argv.index("--client-dist") + 1] == str(tmp_path / "web")
    assert argv[argv.index("--port") + 1] == str(macos_app.DEFAULT_PORT)


def test_app_argv_lan_and_extras(tmp_path: Path) -> None:
    argv = macos_app.app_argv(
        layouts_dir=tmp_path / "l",
        client_dist=tmp_path / "w",
        bind=["0.0.0.0"],
        password_file=tmp_path / "pw",
        log_file=tmp_path / "log",
        verbose=True,
    )
    assert ["--bind", "0.0.0.0"] == argv[argv.index("--bind") : argv.index("--bind") + 2]
    assert str(tmp_path / "pw") in argv
    assert str(tmp_path / "log") in argv
    assert "--verbose" in argv


class _FakeServer:
    """Minimal ``Server`` stand-in for exercising ``ServerRunner``."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    async def start(self) -> None:
        self.started.set()
        try:
            await asyncio.sleep(3600)
        finally:
            self.stopped.set()

    def start_focus_watcher(self) -> None: ...
    def start_windows_watcher(self) -> None: ...
    def start_session_state_watcher(self) -> None: ...

    async def stop(self) -> None: ...


def test_server_runner_starts_and_stops(monkeypatch) -> None:
    import deckd.__main__ as main_mod

    fake = _FakeServer()
    monkeypatch.setattr(main_mod, "build_server", lambda _args: fake)

    runner = macos_app.ServerRunner(object())
    runner.start()
    try:
        assert runner.wait_ready(timeout=5)
        assert fake.started.wait(5)
        assert runner.error is None
    finally:
        runner.stop()
    assert fake.stopped.wait(5)
    assert runner.error is None
