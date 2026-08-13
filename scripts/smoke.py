"""Smoke test: boot server, hit /health, send WS press, verify shell + page.

Run with: python smoke.py

Uses a stable fixture layout (``scripts/smoke_fixtures/default.yaml``)
rather than the shipping ``layouts/`` directory (#77) — so a layout
edit can't break CI and the smoke harness has a deterministic widget
set to press. Override the directory with ``--layouts-dir``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

print("importing...", flush=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "daemon"))

import websockets
from aiohttp import ClientSession, web

from deckd.input import ScrollController
from deckd.server import Server
import deckd.actions as actions_mod


called: list[str] = []
scrolls: list[int] = []


async def fake_shell(cmd: str) -> None:
    called.append(cmd)
    print(f"  [fake-shell] {cmd}")


async def fake_terminal(target: bool | str = True) -> None:
    called.append(f"__terminal__({target!r})")
    print(f"  [fake-terminal] target={target!r}")


actions_mod._run_shell = fake_shell
actions_mod.run_terminal = fake_terminal


class FakeScrollSink:
    def emit_scroll(self, delta: int) -> None:
        scrolls.append(delta)
        print(f"  [fake-scroll] {delta}")

    def close(self) -> None:
        pass


async def main(layouts_dir: Path) -> None:
    print(f"starting server (layouts: {layouts_dir})...", flush=True)
    server = Server(
        layouts_dir=layouts_dir,
        host="127.0.0.1",
        port=18765,
        scroll=ScrollController(FakeScrollSink()),
    )
    runner = web.AppRunner(server.app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 18765)
    await site.start()
    print("server up", flush=True)
    try:
        print("hitting health...", flush=True)
        async with ClientSession() as http:
            async with http.get("http://127.0.0.1:18765/health") as r:
                body = await r.json()
                print("health:", body, flush=True)

            # /reload
            async with http.post("http://127.0.0.1:18765/reload") as r:
                print("reload:", await r.json(), flush=True)

        print("connecting ws...", flush=True)
        async with websockets.connect("ws://127.0.0.1:18765/ws", open_timeout=2, close_timeout=2) as ws:
            print("ws open", flush=True)
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            print("first:", first["type"], [w["id"] for w in first["widgets"]])

            await ws.send(json.dumps({"type": "press", "id": "open-url"}))
            await asyncio.sleep(0.05)
            print("shell called:", called)

            await ws.send(json.dumps({"type": "press", "id": "open-terminal"}))
            await asyncio.sleep(0.05)
            print("after terminal press, called:", called)

            await ws.send(json.dumps({"type": "press", "id": "xterm"}))
            await asyncio.sleep(0.05)
            print("after xterm press, called:", called)

            await ws.send(json.dumps({"type": "press", "id": "tilix"}))
            await asyncio.sleep(0.05)
            print("after tilix press, called:", called)

            await ws.send(json.dumps({"type": "jog", "id": "scroll-strip", "delta": 12}))
            await ws.send(json.dumps({"type": "jog_end", "id": "scroll-strip", "velocity": 0}))
            await asyncio.sleep(0.05)
            assert scrolls == [12]
            print("after jog:", scrolls)

        print("OK")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent
    default_layouts = repo_root / "scripts" / "smoke_fixtures"
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--layouts-dir",
        type=Path,
        default=default_layouts,
        help=f"Directory to load layouts from (default: {default_layouts}).",
    )
    args = parser.parse_args()
    asyncio.run(main(args.layouts_dir))
