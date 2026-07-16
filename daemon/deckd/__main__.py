from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from .input import ScrollController, UinputSink, LoggingScrollSink, LoggingKeySink
from .server import Server


async def _run(server: Server) -> None:
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(server.start())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)

    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        await server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="deckd")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--layouts",
        type=Path,
        default=Path("layouts/default.yaml"),
        help="YAML layout file to load",
    )
    parser.add_argument(
        "--client-dist",
        type=Path,
        default=None,
        help="Optional path to built client (served at /)",
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
        sink = UinputSink()
    except Exception as exc:
        logging.getLogger("deckd").warning(
            "uinput unavailable; falling back to logging only: %s", exc
        )
        sink = None

    scroll_sink = sink if sink is not None else LoggingScrollSink()
    key_sink = sink if sink is not None else LoggingKeySink()

    server = Server(
        layouts_path=args.layouts,
        host=args.host,
        port=args.port,
        scroll=ScrollController(
            sink=scroll_sink,
            momentum_friction=args.scroll_momentum_friction,
            momentum_cutoff=args.scroll_momentum_cutoff,
        ),
        key_sink=key_sink,
    )

    if args.client_dist is not None:
        server.app.router.add_static("/", args.client_dist, show_index=True, append_version=False)
        async def spa(_req):
            return _req.response(200, text=(args.client_dist / "index.html").read_text(), content_type="text/html")
        server.app.router.add_get("/{path:^(?!ws$|health$|.+\\..+$).*}", spa)

    asyncio.run(_run(server))


if __name__ == "__main__":
    main()