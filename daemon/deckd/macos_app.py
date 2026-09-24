"""Helpers for the packaged macOS app bundle (issue #165).

Platform-independent pieces of the menu-bar wrapper: resource discovery,
first-run layout seeding, argv construction for the embedded server, and a
background-thread server runner. These live in the daemon package (rather
than ``packaging/macos/menubar.py``) so they can be unit-tested on Linux —
AppKit itself cannot be.

The wrapper that uses them is ``packaging/macos/menubar.py``, frozen by
``packaging/macos/deckd.spec`` into ``deckd.app``.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
import threading
from pathlib import Path

log = logging.getLogger("deckd.macos_app")

BUNDLE_ID = "com.deckd.daemon"
DEFAULT_PORT = 8765

# The daemon already defaults its password to ``~/.config/deckd/password``;
# keep that so the app and a CLI run share one secret. Layouts, however,
# must be writable (the editor saves back to disk) and the bundle is
# read-only, so they are seeded into Application Support on first run.
APP_SUPPORT_DIRNAME = "deckd"


def resource_root() -> Path:
    """Directory holding the bundled Resources.

    PyInstaller sets ``sys._MEIPASS`` to the onedir payload (inside
    ``deckd.app/Contents/Frameworks``); in a source checkout we fall back to
    the repo root so ``menubar.py`` can be exercised without freezing.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[2]


def client_dist(root: Path) -> Path:
    """Bundled client build (``client/dist`` copied to ``web``)."""
    return root / "web"


def layouts_src(root: Path) -> Path:
    """Bundled layouts directory."""
    return root / "layouts"


def overlay_src(root: Path) -> Path:
    """Bundled macOS overlay layouts (``layouts.macos``)."""
    return root / "layouts.macos"


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


def seed_layouts(src: Path, dest: Path, *, overlay: Path | None = None) -> bool:
    """Copy bundled layouts into the writable data dir on first run.

    Returns ``True`` when it seeded, ``False`` when ``dest`` already existed.
    An existing directory is never overwritten, so a user's hand-edited
    layouts survive an app upgrade (mirrors the Nix module's seed-once
    behaviour). The per-platform overlay is copied to the sibling
    ``<dest>.macos`` directory the daemon auto-discovers.
    """
    if dest.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    if overlay is not None and overlay.is_dir():
        overlay_dest = dest.parent / f"{dest.name}.macos"
        if not overlay_dest.exists():
            shutil.copytree(overlay, overlay_dest)
    return True


def app_argv(
    *,
    layouts_dir: Path,
    client_dist: Path,
    port: int = DEFAULT_PORT,
    bind: list[str] | None = None,
    password_file: Path | None = None,
    log_file: Path | None = None,
    verbose: bool = False,
) -> list[str]:
    """Build the daemon argv the app passes to ``parse_args``.

    Localhost-only unless ``bind`` is given (the menu's LAN toggle supplies
    ``["0.0.0.0"]``), so the default stays safe.
    """
    argv = [
        "--layouts-dir", str(layouts_dir),
        "--client-dist", str(client_dist),
        "--port", str(port),
    ]
    for addr in bind or []:
        argv += ["--bind", addr]
    if password_file is not None:
        argv += ["--password-file", str(password_file)]
    if log_file is not None:
        argv += ["--log-file", str(log_file)]
    if verbose:
        argv.append("--verbose")
    return argv


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
