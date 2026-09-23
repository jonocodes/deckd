from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Callable

from aiohttp import web

from .auth import PasswordError, default_password_path, load_or_create_password
from .input import (
    KeySink,
    LoggingKeySink,
    LoggingScrollSink,
    ScrollController,
    ScrollSink,
    UinputSink,
)
from .logging_setup import setup_logging
from .platform import default_backend, default_sensor_manager
from .media import MediaManager
from .server import PortInUseError, Server


async def _run(server: Server) -> None:
    loop = asyncio.get_running_loop()
    server_task = asyncio.create_task(server.start())
    server.start_focus_watcher()
    # Stage 2 (#120 / #126): start the windows watcher alongside the
    # focus watcher. ``start_windows_watcher`` is a no-op when the
    # backend lacks ``watch_windows`` (X11, headless), so the wiring
    # stays unconditional at the call site. macOS gained the surface
    # in #135 via Quartz CGWindowList.
    server.start_windows_watcher()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, server_task.cancel)

    try:
        await server_task
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()


def _overlay_dir_for(layouts_dir: Path) -> Path:
    """Pick a per-platform overlay dir next to ``layouts_dir``.

    Convention: ``<name>.linux`` or ``<name>.macos``. The path is
    always returned; whether it actually exists is the caller's
    concern (``Server`` treats a missing overlay as a no-op).
    """
    suffix = {"darwin": "macos"}.get(sys.platform, "linux")
    return layouts_dir.parent / f"{layouts_dir.name}.{suffix}"


def _build_sinks() -> tuple[object | None, ScrollSink, KeySink]:
    """Pick the (device, scroll, key) sinks for this process.

    ``DECKD_FAKE_INPUT`` forces the logging sinks on *every* platform.
    The e2e suite needs a daemon that records injections instead of
    performing them, and its Linux trick — shadowing ``evdev`` with
    ``PYTHONPATH=scripts/no-evdev`` so ``UinputSink`` raises — has no
    macOS analogue: ``MacKeySink`` imports nothing shadowable and would
    type real keystrokes into whatever window happens to be focused on
    the developer's desktop.
    """
    if os.environ.get("DECKD_FAKE_INPUT"):
        logging.getLogger("deckd").warning(
            "DECKD_FAKE_INPUT set; input is logged, not injected"
        )
        return None, LoggingScrollSink(), LoggingKeySink()
    try:
        if sys.platform == "darwin":
            from .platform_macos import MacKeySink, MacScrollSink

            sink = MacKeySink()
            return sink, MacScrollSink(), sink
        sink = UinputSink()
        return sink, sink, sink
    except Exception as exc:
        logging.getLogger("deckd").warning(
            "platform sink unavailable; falling back to logging only: %s", exc
        )
        return None, LoggingScrollSink(), LoggingKeySink()


def _client_build_id(dist: Path) -> str:
    """Stable fingerprint of a built client tree.

    Hashes every file's relative path and bytes, so a rebuilt bundle always
    yields a new id (Vite renames content-hashed assets, and the walk covers
    unhashed files like ``manifest.json`` too). The running client compares
    this value against the one it saw last and hard-reloads when it changes —
    see ``client/src/update-check.ts``.
    """
    digest = hashlib.sha256()
    for path in sorted(p for p in dist.rglob("*") if p.is_file()):
        digest.update(path.relative_to(dist).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


@web.middleware
async def _client_cache_headers(
    request: web.Request, handler: Callable[[web.Request], Any]
) -> web.StreamResponse:
    """Force a fresh shell without giving up content-addressed caching.

    The SPA HTML, manifest, and other unhashed files answer ``no-store`` so a
    phone (including an installed PWA) must re-fetch them from the daemon.
    ``/assets/*`` files are content-hashed by Vite — a changed byte means a
    changed filename — so those stay immutable and cheap to cache. A handler
    that sets its own ``Cache-Control`` is never overridden.
    """
    response = await handler(request)
    route = request.match_info.route
    if not (
        getattr(route, "name", None) in ("client_spa", "client_spa_fallback")
        or isinstance(getattr(route, "resource", None), web.StaticResource)
    ):
        return response
    if "Cache-Control" not in response.headers:
        if request.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-store"
    return response


def _add_client_routes(server: Server, dist: Path) -> None:
    """Serve the built client at ``/`` with the freshness headers.

    Split out of ``main`` so tests can boot an app around a throwaway dist
    directory without the full argparse surface.
    """
    index_text = (dist / "index.html").read_text()

    async def spa(_req: web.Request) -> web.Response:
        # SPA fallback: serve the built index.html for any path
        # without a file extension that isn't a reserved route
        # (``/ws``, ``/health``, ``/reload``, ``/layout/...``).
        return web.Response(text=index_text, content_type="text/html")

    # Register the SPA routes BEFORE add_static so they win the
    # match for ``/`` and other extension-less paths. ``add_static``
    # would otherwise claim ``/`` first and return a directory
    # listing, breaking ``/?demo=meter``-style entry points.
    #
    # The fallback regex must not swallow real files: ``[^.]+$`` admits
    # deep links like ``/settings`` and ``/now-playing`` (client view
    # routes, ADR-0011's reload target) while letting dotted paths
    # (``/assets/*``, ``/manifest.json``) fall through to the static
    # handler. Reserved daemon routes are excluded explicitly.
    server.app.router.add_get("/", spa, name="client_spa")
    server.app.router.add_get(
        "/{path:(?!ws$|health$|reload$|layout($|/))[^.]+$}",
        spa,
        name="client_spa_fallback",
    )
    server.app.router.add_static("/", dist, show_index=False, append_version=False)
    server.app.middlewares.append(_client_cache_headers)


def main() -> None:
    from .bind import DEFAULT_BIND

    parser = argparse.ArgumentParser(prog="deckd")
    parser.add_argument(
        "--bind",
        action="append",
        default=None,
        metavar="ADDR",
        help=(
            "Address (or 'iface:<name>') to bind the daemon to. Repeatable. "
            "Defaults to 127.0.0.1 + ::1 (localhost only). Examples: "
            "--bind 0.0.0.0, --bind 192.168.1.5, --bind iface:wlan0."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Listen port (issue #66). ``0`` asks the kernel to pick one.",
    )
    parser.add_argument(
        "--layouts-dir",
        type=Path,
        default=Path("layouts"),
        help="Directory of per-app YAML layouts (one file per app + default.yaml)",
    )
    parser.add_argument(
        "--no-overlay",
        action="store_true",
        help="Skip the per-platform overlay (layouts.<platform>) even if present",
    )
    parser.add_argument(
        "--no-focus",
        action="store_true",
        help="Disable the focus watcher (serve only the default layout)",
    )
    parser.add_argument(
        "--client-dist",
        type=Path,
        default=None,
        help="Optional path to built client (served at /)",
    )
    parser.add_argument(
        "--password-file",
        type=Path,
        default=None,
        help=(
            "Shared password every client must present. Defaults to "
            "$XDG_CONFIG_HOME/deckd/password (~/.config/deckd/password); "
            "generated on first start if absent."
        ),
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable password auth entirely (all connections allowed)",
    )
    parser.add_argument(
        "--scroll-momentum-friction",
        type=float,
        default=0.90,
        help="Momentum decay per 60Hz frame; 0 disables momentum, values below 1 decay",
    )
    parser.add_argument(
        "--scroll-momentum-cutoff",
        type=int,
        default=20,
        help="Stop momentum when absolute velocity drops below this high-res-wheel-units/sec value",
    )
    parser.add_argument(
        "--log-format",
        choices=("text", "json"),
        default="text",
        help="Logging output format. ``json`` is structured (one JSON object per record); ``text`` is the human-readable default.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Append logs to this path in addition to stderr (issue #70).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if not 0 <= args.scroll_momentum_friction < 1:
        parser.error("--scroll-momentum-friction must be >= 0 and < 1")

    setup_logging(
        level=logging.DEBUG if args.verbose else logging.INFO,
        fmt=args.log_format,
    )
    if args.log_file is not None:
        # Issue #70: the structured-log feed should be tee'd to a
        # file so an AI agent tailing the daemon can correlate
        # against the metrics / events endpoints without re-running
        # the process. The handler is added on top of the stderr
        # handler set up by ``setup_logging``; we copy the active
        # formatter so file output matches stderr exactly.
        from .logging_setup import JsonFormatter

        file_handler = logging.FileHandler(args.log_file)
        file_handler.setFormatter(
            JsonFormatter() if args.log_format == "json"
            else logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        logging.getLogger().addHandler(file_handler)

    sink, scroll_sink, key_sink = _build_sinks()

    focus_backend = None if args.no_focus else default_backend()
    if focus_backend is not None:
        logging.getLogger("deckd").info(
            "focus backend: %s (sys.platform=%s)",
            type(focus_backend).__name__,
            sys.platform,
        )

    overlay_dir = None if args.no_overlay else _overlay_dir_for(args.layouts_dir)
    if overlay_dir is not None and overlay_dir.is_dir():
        logging.getLogger("deckd").info("loading layouts overlay from %s", overlay_dir)

    if args.no_auth:
        password = None
        logging.getLogger("deckd").warning(
            "remote-client auth disabled (--no-auth); all connections allowed"
        )
    else:
        password_path = args.password_file or default_password_path()
        try:
            password = load_or_create_password(password_path)
        except PasswordError as exc:
            parser.error(str(exc))

    # ``dbus-fast`` is an optional extra (issue #27). It backs the ``dbus:``
    # action primitive and MPRIS now-playing — both Linux-only in practice
    # (org.mpris.*, login1, GNOME ScreenSaver), so ``setup-macos`` skips the
    # `[dbus]` extra. Probe the import once here: when it is absent, wire
    # ``None`` as the factory. Both the MPRIS auto-discovery and every
    # ``dbus:`` dispatch already guard on ``factory is None`` and skip cleanly.
    dbus_bus_factory: "Callable[[Any], Any] | None" = None
    try:
        from dbus_fast.aio import MessageBus
    except ImportError:
        logging.getLogger("deckd").warning(
            "dbus-fast not installed; D-Bus actions and MPRIS now-playing "
            "disabled (install the '[dbus]' extra to enable)"
        )
    else:
        def _make_dbus_bus(bus_type):
            return MessageBus(bus_type=bus_type)

        dbus_bus_factory = _make_dbus_bus

    # Test-only seam (analogous to the ``PYTHONPATH=scripts/no-evdev``
    # input shim): when ``DECKD_FAKE_MPRIS`` names a JSON file, skip the
    # real session-bus backend and inject a pre-seeded
    # ``FakeMprisBackend``. This lets the Playwright e2e boot a real
    # daemon that reports a "player is playing" now-playing surface
    # without a session bus or a real MPRIS player on the runner. The
    # JSON is ``{row_id: {field: value}}`` (see ``build_fake_mpris``).
    # Never set in production; when absent the real backend path (the
    # ``connect_mpris_backend`` auto-discovery in ``Server``) is used.
    fake_mpris_backend = None
    fake_mpris_path = os.environ.get("DECKD_FAKE_MPRIS")
    if fake_mpris_path:
        import json as _json

        from .mpris import build_fake_mpris

        seed = _json.loads(Path(fake_mpris_path).read_text())
        fake_mpris_backend = build_fake_mpris(seed)
        logging.getLogger("deckd").warning(
            "DECKD_FAKE_MPRIS set; injecting fake MPRIS backend from %s "
            "(%d row(s)) — test-only, no session bus opened",
            fake_mpris_path,
            len(seed),
        )

    # Fingerprint the served client so ``/health`` can tell a running client
    # whether the bundle it loaded is still the one on disk (issue: stale
    # installed PWAs). Recomputed per daemon start — the deploy path is
    # rebuild + restart.
    client_build = (
        _client_build_id(args.client_dist) if args.client_dist is not None else None
    )

    server = Server(
        layouts_dir=args.layouts_dir,
        bind=args.bind if args.bind is not None else list(DEFAULT_BIND),
        port=args.port,
        scroll=ScrollController(
            sink=scroll_sink,
            momentum_friction=args.scroll_momentum_friction,
            momentum_cutoff=args.scroll_momentum_cutoff,
        ),
        key_sink=key_sink,
        dbus_bus_factory=dbus_bus_factory,
        mpris_backend=fake_mpris_backend,
        focus_backend=focus_backend,
        overlay_dir=overlay_dir,
        password=password,
        sensor_manager=default_sensor_manager(),
        media_manager=MediaManager(),
        client_build=client_build,
    )

    if args.client_dist is not None:
        _add_client_routes(server, args.client_dist)

    try:
        asyncio.run(_run(server))
    except PortInUseError as exc:
        # Fail fast with the actionable message instead of a raw asyncio
        # traceback ending in OSError: [Errno 98].
        logging.getLogger("deckd").error("%s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
