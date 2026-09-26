"""Helpers for the packaged Linux AppImage (issue #168).

Linux-specific pieces of the AppImage launcher: the writable XDG data dir and
log file, the ``layouts.linux`` overlay, and first-run seeding. The
platform-independent mechanics live in ``deckd.app_bundle``; the frozen entry
point is ``packaging/linux/launcher.py``.

Everything here runs on any host (it is pure path/argv logic), so it is
unit-tested alongside ``deckd.macos_app``; the AppImage build itself needs
Linux tooling.
"""
from __future__ import annotations

import os
from pathlib import Path

from .app_bundle import (
    DEFAULT_PORT,
    app_argv,
    bundle_version,
    client_dist,
    layouts_src,
    resource_root,
)
from .app_bundle import overlay_src as _overlay_src
from .app_bundle import seed_layouts as _seed_layouts

__all__ = [
    "APP_NAME",
    "DEFAULT_PORT",
    "app_argv",
    "build_argv",
    "bundle_version",
    "client_dist",
    "data_dir",
    "default_log_file",
    "layouts_src",
    "overlay_src",
    "prepare",
    "resource_root",
    "seed_layouts",
]

APP_NAME = "deckd"


def data_dir() -> Path:
    """``$XDG_DATA_HOME/deckd`` (``~/.local/share/deckd``) — writable data.

    Layouts must be writable (the editor saves back to disk) but the AppImage
    payload is a read-only squashfs mount, so layouts are seeded here on first
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
    """Bundled Linux overlay layouts (``layouts.linux``)."""
    return _overlay_src(root, "linux")


def seed_layouts(src: Path, dest: Path, *, overlay: Path | None = None) -> bool:
    """Seed layouts + the ``.linux`` overlay into the writable data dir."""
    return _seed_layouts(src, dest, overlay=overlay, overlay_suffix="linux")


def prepare() -> tuple[Path, Path, Path]:
    """Seed writable data, returning (layouts_dir, client_dist, log_file)."""
    root = resource_root()
    layouts_dir = data_dir() / "layouts"
    seed_layouts(layouts_src(root), layouts_dir, overlay=overlay_src(root))
    log_file = default_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    return layouts_dir, client_dist(root), log_file


def build_argv(extra: list[str] | None = None) -> list[str]:
    """Daemon argv for the AppImage: seeded layouts, bundled client, log file.

    ``extra`` is passed through so the user can add flags (e.g.
    ``--bind 0.0.0.0`` to expose the surface on the LAN). Localhost-only by
    default.
    """
    layouts_dir, web, log_file = prepare()
    return app_argv(layouts_dir=layouts_dir, client_dist=web, log_file=log_file) + list(extra or [])
