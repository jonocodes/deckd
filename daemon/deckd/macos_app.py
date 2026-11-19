"""Helpers for the packaged macOS app bundle (issue #165).

macOS-specific pieces of the menu-bar wrapper: the bundle id, the writable
Application Support / Logs locations, the ``Info.plist``, and the
background-thread server runner the AppKit wrapper needs. The platform-
independent packaging mechanics (payload discovery, deck seeding, argv and
version) live in ``deckd.app_bundle`` and are re-exported here so
``packaging/macos/menubar.py`` keeps importing them from one place.

Everything in this module runs on the Linux dev/CI hosts; AppKit itself does
not, which is why ``menubar.py`` stays a thin wrapper.

The wrapper that uses them is ``packaging/macos/menubar.py``, frozen by
``packaging/macos/deckd.spec`` into ``deckd.app``.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
from pathlib import Path
from typing import Protocol

from .app_bundle import (
    DEFAULT_PORT,
    app_argv,
    bundle_version,
    client_dist,
    decks_src,
    resource_root,
    seed_decks,
)

__all__ = [
    "BUNDLE_ID",
    "DEFAULT_PORT",
    "APP_SUPPORT_DIRNAME",
    "LAN_DEFAULTS_KEY",
    "LanAccess",
    "ServerRunner",
    "app_argv",
    "app_support_dir",
    "bundle_info_plist",
    "bundle_version",
    "client_dist",
    "default_log_file",
    "decks_src",
    "overlay_src",
    "resource_root",
    "seed_decks",
]

log = logging.getLogger("deckd.macos_app")

BUNDLE_ID = "com.deckd.daemon"

# The daemon already defaults its password to ``~/.config/deckd/password``;
# keep that so the app and a CLI run share one secret. Decks, however,
# must be writable (the editor saves back to disk) and the bundle is
# read-only, so they are seeded into Application Support on first run.
APP_SUPPORT_DIRNAME = "deckd"

# User-defaults key for the menu's "Allow LAN access" choice. Documented
# (`defaults write com.deckd.daemon AllowLAN -bool true`), so don't rename.
LAN_DEFAULTS_KEY = "AllowLAN"


def overlay_src(root: Path) -> Path:
    """Bundled macOS overlay decks (``decks.macos``)."""
    from .app_bundle import overlay_src as _overlay_src

    return _overlay_src(root, "macos")


class _BoolDefaults(Protocol):
    """The slice of ``NSUserDefaults`` that ``LanAccess`` uses."""

    def objectForKey_(self, key: str) -> object | None: ...
    def setBool_forKey_(self, value: bool, key: str) -> None: ...


class LanAccess:
    """The app's "Allow LAN access" choice, remembered across launches.

    Backed by the app's user defaults (``NSUserDefaults`` in the
    ``com.deckd.daemon`` domain), so it survives quits, reboots, and in-place
    upgrades, and can be set without the menu bar at all:

        defaults write com.deckd.daemon AllowLAN -bool false   # localhost-only

    (then relaunch). On by default, so a fresh install is reachable from a
    phone or tablet straight away; the shared password still gates every
    non-localhost client. Only an explicit "off" (the menu item, or
    ``-bool false``) keeps it localhost-only.
    """

    def __init__(self, defaults: _BoolDefaults) -> None:
        self._defaults = defaults

    @property
    def enabled(self) -> bool:
        # ``objectForKey_`` is nil for a key never written, which
        # ``boolForKey_`` would report as False (indistinguishable from
        # an explicit off).
        saved = self._defaults.objectForKey_(LAN_DEFAULTS_KEY)
        return True if saved is None else bool(saved)

    def toggle(self) -> bool:
        """Flip and persist the choice; return the new state."""
        new = not self.enabled
        self._defaults.setBool_forKey_(new, LAN_DEFAULTS_KEY)
        return new

    def bind(self) -> list[str] | None:
        """``--bind`` addresses for the daemon: all interfaces, or default."""
        return ["0.0.0.0"] if self.enabled else None


def menubar_icon_paths(root: Path) -> tuple[Path, Path] | None:
    """The ``(1x, 2x)`` menu-bar template PNGs, or ``None`` if not bundled.

    Frozen builds put them at the bundle root (``root`` is ``sys._MEIPASS``);
    a source checkout keeps them beside the spec in ``packaging/macos``.
    ``packaging/macos/menubar.py`` loads both reps into one template image.
    """
    candidates = (root, root / "packaging" / "macos")
    for base in candidates:
        one_x = base / "deckd-menubar.png"
        if one_x.is_file():
            return one_x, base / "deckd-menubar@2x.png"
    return None


def app_support_dir() -> Path:
    """``~/Library/Application Support/deckd`` — the writable data dir."""
    return Path.home() / "Library" / "Application Support" / APP_SUPPORT_DIRNAME


def default_log_file() -> Path:
    """``~/Library/Logs/deckd.log`` — where the app tees its logs."""
    return Path.home() / "Library" / "Logs" / "deckd.log"


def bundle_info_plist(version: str) -> dict[str, object]:
    """Info.plist entries for ``deckd.app`` (issue #165).

    Kept here (not inline in ``deckd.spec``) so the TCC-relevant keys are
    unit-testable on the Linux dev/CI hosts.

    ``NSAppleEventsUsageDescription`` is load-bearing: the daemon drives
    keystrokes and focus by shelling out to ``osascript`` → System Events,
    and macOS attributes those Apple Events to the *responsible process* —
    the bundle, not the ``osascript`` child. Without this string the
    Automation prompt can't be shown, so macOS refuses the event
    (``errAEEventNotPermitted``, -1743) — the silent failure #165 fixes.
    """
    return {
        "LSUIElement": True,
        "CFBundleName": "deckd",
        "CFBundleDisplayName": "deckd",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSAppleEventsUsageDescription": (
            "deckd sends keystrokes and focuses windows through System "
            "Events when you press buttons on your deck."
        ),
    }


class ServerRunner:
    """Run the deckd asyncio server on a background thread.

    The macOS app owns the main thread for AppKit, so the server gets its own
    event loop on a daemon thread. ``start()`` is idempotent while running;
    ``stop()`` cancels the server task (so ``serve`` runs its ``server.stop()``
    cleanup) and joins the thread.
    """

    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._server: object | None = None
        self._error: BaseException | None = None
        self._ready = threading.Event()

    @property
    def error(self) -> BaseException | None:
        """The exception that ended the server thread, if any."""
        return self._error

    def wait_ready(self, timeout: float | None = None) -> bool:
        """Block until the server task is created (or the thread exits)."""
        return self._ready.wait(timeout)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._error = None
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run, name="deckd-server", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        from .__main__ import build_server, serve

        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            self._server = build_server(self._args)
            loop.run_until_complete(
                serve(
                    self._server,  # type: ignore[arg-type]
                    install_signal_handlers=False,
                    on_started=self._on_started,
                )
            )
        except BaseException as exc:  # noqa: BLE001 — surfaced via ``error``
            self._error = exc
            log.exception("deckd server thread exited")
        finally:
            self._loop = None
            self._task = None
            self._server = None
            loop.close()
            self._ready.set()

    def _on_started(self, task: asyncio.Task[None]) -> None:
        self._task = task
        self._ready.set()

    def stop(self, timeout: float = 5.0) -> None:
        loop = self._loop
        task = self._task
        if loop is not None and not loop.is_closed() and task is not None:
            loop.call_soon_threadsafe(task.cancel)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self._thread = None
