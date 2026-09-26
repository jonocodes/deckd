"""Helpers for the packaged macOS app bundle (issue #165).

macOS-specific pieces of the menu-bar wrapper: the bundle id, the writable
Application Support / Logs locations, the ``Info.plist``, and the
background-thread server runner the AppKit wrapper needs. The platform-
independent packaging mechanics (payload discovery, layout seeding, argv and
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

from .app_bundle import (
    DEFAULT_PORT,
    app_argv,
    bundle_version,
    client_dist,
    layouts_src,
    resource_root,
    seed_layouts,
)

__all__ = [
    "BUNDLE_ID",
    "DEFAULT_PORT",
    "APP_SUPPORT_DIRNAME",
    "ServerRunner",
    "app_argv",
    "app_support_dir",
    "bundle_info_plist",
    "bundle_version",
    "client_dist",
    "default_log_file",
    "layouts_src",
    "overlay_src",
    "resource_root",
    "seed_layouts",
]

log = logging.getLogger("deckd.macos_app")

BUNDLE_ID = "com.deckd.daemon"

# The daemon already defaults its password to ``~/.config/deckd/password``;
# keep that so the app and a CLI run share one secret. Layouts, however,
# must be writable (the editor saves back to disk) and the bundle is
# read-only, so they are seeded into Application Support on first run.
APP_SUPPORT_DIRNAME = "deckd"


def overlay_src(root: Path) -> Path:
    """Bundled macOS overlay layouts (``layouts.macos``)."""
    from .app_bundle import overlay_src as _overlay_src

    return _overlay_src(root, "macos")


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
