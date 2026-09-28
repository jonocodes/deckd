"""Tests for the Linux AppImage helpers (issue #168).

The AppImage build itself needs Linux tooling, but everything path/argv-shaped
lives in ``deckd.linux_app`` and is exercised here on any host — the same
arrangement as ``test_app.py`` for the macOS bundle.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from deckd import app_bundle, linux_app


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_resource_root_dev_fallback(monkeypatch) -> None:
    monkeypatch.delattr(app_bundle.sys, "_MEIPASS", raising=False)
    root = linux_app.resource_root()
    assert (root / "daemon" / "deckd").is_dir()
    assert (root / "pyproject.toml").is_file()


def test_data_dir_honours_xdg_data_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert linux_app.data_dir() == tmp_path / "xdg" / "deckd"


def test_data_dir_defaults_to_local_share(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert linux_app.data_dir() == tmp_path / ".local" / "share" / "deckd"


def test_default_log_file_lives_in_data_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert linux_app.default_log_file() == tmp_path / "deckd" / "deckd.log"


def test_overlay_src_is_linux(tmp_path: Path) -> None:
    assert linux_app.overlay_src(tmp_path) == tmp_path / "layouts.linux"


def test_seed_layouts_uses_linux_overlay_suffix(tmp_path: Path) -> None:
    src = tmp_path / "bundled"
    _write(src / "default.yaml", "id: default\n")
    overlay = tmp_path / "bundled.linux"
    _write(overlay / "firefox.yaml", "id: firefox\n")
    dest = tmp_path / "data" / "layouts"

    assert linux_app.seed_layouts(src, dest, overlay=overlay) is True
    assert (dest / "default.yaml").read_text() == "id: default\n"
    # The daemon looks for ``layouts.linux`` beside the layouts dir.
    assert (dest.parent / "layouts.linux" / "firefox.yaml").is_file()

    # A user's edits survive: an existing dir is never re-seeded.
    assert linux_app.seed_layouts(src, dest, overlay=overlay) is False


def test_prepare_seeds_writable_layouts_once(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delattr(app_bundle.sys, "_MEIPASS", raising=False)

    layouts_dir, web, log_file = linux_app.prepare()
    assert layouts_dir == tmp_path / "deckd" / "layouts"
    assert layouts_dir.joinpath("default.yaml").exists()
    assert web.name == "web"
    assert log_file == tmp_path / "deckd" / "deckd.log"
    assert log_file.parent.is_dir()


def test_build_argv_passes_extra_through(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delattr(app_bundle.sys, "_MEIPASS", raising=False)

    argv = linux_app.build_argv(["--bind", "0.0.0.0"])
    assert argv[argv.index("--client-dist") + 1].endswith("web")
    assert argv[argv.index("--log-file") + 1].endswith("deckd.log")
    # Extra flags land after the bundled ones, so the user's win.
    assert argv[-2:] == ["--bind", "0.0.0.0"]


def test_build_argv_localhost_by_default(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delattr(app_bundle.sys, "_MEIPASS", raising=False)

    argv = linux_app.build_argv()
    assert "--bind" not in argv


def _fake_appdir(tmp_path: Path) -> Path:
    """An AppDir skeleton with the frozen launcher and integration assets."""
    appdir = tmp_path / "deckd.AppDir"
    (appdir / "usr" / "bin").mkdir(parents=True)
    exe = appdir / "usr" / "bin" / "deckd"
    exe.write_text("#!/bin/sh\n")
    integration = appdir / "usr" / "share" / "deckd" / "integration"
    _write(integration / "70-deckd-uinput.rules", "KERNEL==\"uinput\"\n")
    _write(integration / "gnome-shell" / "deckd-focus@local" / "extension.js", "// x\n")
    return appdir


def test_integration_src_is_beside_the_launcher(monkeypatch, tmp_path: Path) -> None:
    appdir = _fake_appdir(tmp_path)
    monkeypatch.setattr(linux_app.sys, "executable", str(appdir / "usr" / "bin" / "deckd"))

    assert linux_app.integration_src() == appdir / "usr" / "share" / "deckd" / "integration"


def test_extract_integration_copies_tree(monkeypatch, tmp_path: Path) -> None:
    appdir = _fake_appdir(tmp_path)
    monkeypatch.setattr(linux_app.sys, "executable", str(appdir / "usr" / "bin" / "deckd"))
    dest = tmp_path / "out"

    linux_app.extract_integration(dest)

    assert (dest / "70-deckd-uinput.rules").is_file()
    assert (dest / "gnome-shell" / "deckd-focus@local" / "extension.js").is_file()


def test_extract_integration_rejects_missing_assets(monkeypatch, tmp_path: Path) -> None:
    appdir = _fake_appdir(tmp_path)
    shutil.rmtree(appdir / "usr" / "share")
    monkeypatch.setattr(linux_app.sys, "executable", str(appdir / "usr" / "bin" / "deckd"))

    with pytest.raises(FileNotFoundError):
        linux_app.extract_integration(tmp_path / "out")
