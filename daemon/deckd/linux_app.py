"""Helpers for the packaged Linux AppImage (issue #168).

Linux-specific pieces of the AppImage launcher: the writable XDG data dir and
log file, the ``decks.linux`` overlay, and first-run seeding. The
platform-independent mechanics live in ``deckd.app_bundle``; the frozen entry
point is ``packaging/linux/launcher.py``.

Everything here runs on any host (it is pure path/argv logic), so it is
unit-tested alongside ``deckd.macos_app``; the AppImage build itself needs
Linux tooling.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .app_bundle import (
    DEFAULT_PORT,
    app_argv,
    bundle_version,
    client_dist,
    decks_src,
    resource_root,
)
from .app_bundle import overlay_src as _overlay_src
from .app_bundle import seed_decks as _seed_decks

__all__ = [
    "APP_NAME",
    "DEFAULT_PORT",
    "EXTRACT_INTEGRATION_FLAG",
    "app_argv",
    "build_argv",
    "bundle_version",
    "client_dist",
    "data_dir",
    "default_log_file",
    "extract_integration",
    "integration_src",
    "decks_src",
    "overlay_src",
    "prepare",
    "resource_root",
    "seed_decks",
]

APP_NAME = "deckd"

# Frozen-launcher-only flag: copy the AppDir's integration assets (udev rule,
# focus watchers, install helper) to a directory and exit. The install helper
# falls back to it when the AppImage runtime won't honour `--appimage-extract`
# — e.g. a binfmt wrapper like NixOS's `programs.appimage` runs the payload
# directly, so the runtime's own extraction flags never reach it.
EXTRACT_INTEGRATION_FLAG = "--extract-integration"


def data_dir() -> Path:
    """``$XDG_DATA_HOME/deckd`` (``~/.local/share/deckd``) — writable data.

    Decks must be writable (the editor saves back to disk) but the AppImage
    payload is a read-only squashfs mount, so decks are seeded here on first
    run. The shared password stays on the config side
    (``$XDG_CONFIG_HOME/deckd/password``), which the daemon already defaults to.
    """
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / APP_NAME


def default_log_file() -> Path:
    """``<data_dir>/deckd.log`` — where the AppImage tees its logs.

    Unlike a source install there is no journal: an AppImage launched from an
    XDG autostart entry has nowhere to put stderr, so the daemon writes a log
    file the user can tail.
    """
    return data_dir() / f"{APP_NAME}.log"


def overlay_src(root: Path) -> Path:
    """Bundled Linux overlay decks (``decks.linux``)."""
    return _overlay_src(root, "linux")


def integration_src() -> Path:
    """Bundled system-integration assets in the AppDir.

    The AppImage recipe places the udev rule, the GNOME/KWin focus watchers,
    and ``install-system-integration.sh`` under ``usr/share/deckd/integration``
    beside the frozen launcher (``usr/bin/deckd``).
    """
    return Path(sys.executable).resolve().parents[1] / "share" / "deckd" / "integration"


def extract_integration(dest: Path) -> None:
    """Copy the bundled integration assets to ``dest`` (created if needed)."""
    src = integration_src()
    if not src.is_dir():
        raise FileNotFoundError(f"no bundled integration assets at {src}")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)


def seed_decks(src: Path, dest: Path, *, overlay: Path | None = None) -> bool:
    """Seed decks + the ``.linux`` overlay into the writable data dir."""
    return _seed_decks(src, dest, overlay=overlay, overlay_suffix="linux")


def prepare() -> tuple[Path, Path, Path]:
    """Seed writable data, returning (decks_dir, client_dist, log_file)."""
    root = resource_root()
    decks_dir = data_dir() / "decks"
    seed_decks(decks_src(root), decks_dir, overlay=overlay_src(root))
    log_file = default_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return decks_dir, client_dist(root), log_file


def build_argv(extra: list[str] | None = None) -> list[str]:
    """Daemon argv for the AppImage: seeded decks, bundled client, log file.

    ``extra`` is passed through so the user can add flags (e.g.
    ``--bind 0.0.0.0`` to expose the surface on the LAN). Localhost-only by
    default.
    """
    decks_dir, web, log_file = prepare()
    return app_argv(decks_dir=decks_dir, client_dist=web, log_file=log_file) + list(extra or [])
