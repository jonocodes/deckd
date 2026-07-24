from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from .auth import PasswordError, default_password_path, load_or_create_password
from .input import LoggingKeySink, LoggingScrollSink, ScrollController, UinputSink
from .platform import default_backend
from .server import Server


async def _run(server: Server) -> None:
    loop = asyncio.get_running_loop()
    server_task = asyncio.create_task(server.start())
    server.start_focus_watcher()

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


def main() -> None:
    parser = argparse.ArgumentParser(prog="deckd")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
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
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if not 0 <= args.scroll_momentum_friction < 1:
        parser.error("--scroll-momentum-friction must be >= 0 and < 1")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    try:
        if sys.platform == "darwin":
            from .platform_macos import MacKeySink, MacScrollSink

            sink = MacKeySink()
            scroll_sink = MacScrollSink()
            key_sink = sink
        else:
            sink = UinputSink()
            scroll_sink = sink
            key_sink = sink
    except Exception as exc:
        logging.getLogger("deckd").warning(
            "platform sink unavailable; falling back to logging only: %s", exc
        )
        sink = None
        scroll_sink = LoggingScrollSink()
        key_sink = LoggingKeySink()

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

    def dbus_bus_factory(bus_type):
        from dbus_fast.aio import MessageBus

        return MessageBus(bus_type=bus_type)

    server = Server(
        layouts_dir=args.layouts_dir,
        host=args.host,
        port=args.port,
        scroll=ScrollController(
            sink=scroll_sink,
            momentum_friction=args.scroll_momentum_friction,
            momentum_cutoff=args.scroll_momentum_cutoff,
        ),
        key_sink=key_sink,
        dbus_bus_factory=dbus_bus_factory,
        focus_backend=focus_backend,
        overlay_dir=overlay_dir,
        password=password,
    )

    if args.client_dist is not None:
        server.app.router.add_static("/", args.client_dist, show_index=True, append_version=False)
        async def spa(_req):
            return _req.response(200, text=(args.client_dist / "index.html").read_text(), content_type="text/html")
        server.app.router.add_get("/{path:^(?!ws$|health$|.+\\..+$).*}", spa)

    asyncio.run(_run(server))


if __name__ == "__main__":
    main()
