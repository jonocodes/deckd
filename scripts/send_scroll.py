"""Send synthetic jogstrip scroll events to a running deckd daemon.

Usage:
    .venv/bin/python -u scripts/send_scroll.py
    sleep 2 && .venv/bin/python -u scripts/send_scroll.py

Keep deckd running first, then put the desktop pointer over a scrollable app
before running this script. The sleep form is useful on the same desktop because
it gives you time to move the pointer away from the terminal.
"""

from __future__ import annotations

import argparse
import asyncio
import json

import websockets


async def send_scroll(url: str, *, delta: int, frames: int, delay: float) -> None:
    async with websockets.connect(url, open_timeout=2, close_timeout=2) as ws:
        await ws.recv()  # initial layout push
        for _ in range(frames):
            await ws.send(json.dumps({"type": "jog", "id": "scroll-strip", "delta": delta}))
            await asyncio.sleep(delay)
        await ws.send(json.dumps({"type": "jog_end", "id": "scroll-strip", "velocity": 0}))


def main() -> None:
    parser = argparse.ArgumentParser(prog="send_scroll.py")
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws")
    parser.add_argument("--delta", type=int, default=30)
    parser.add_argument("--frames", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.016)
    args = parser.parse_args()

    asyncio.run(send_scroll(args.url, delta=args.delta, frames=args.frames, delay=args.delay))


if __name__ == "__main__":
    main()
