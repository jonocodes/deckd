from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from .server import Server


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
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    server = Server(layouts_path=args.layouts, host=args.host, port=args.port)

    if args.client_dist is not None:
        server.app.router.add_static("/", args.client_dist, show_index=True, append_version=False)
        async def spa(_req):
            return _req.response(200, text=(args.client_dist / "index.html").read_text(), content_type="text/html")
        server.app.router.add_get("/{path:^(?!ws$|health$|.+\\..+$).*}", spa)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: loop.create_task(server.stop()))

    try:
        loop.run_until_complete(server.start())
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(server.stop())
        loop.close()


if __name__ == "__main__":
    main()