"""Dev supervisor: runs the daemon as a child and auto-reloads/restarts on edits.

Watches `layouts/*.yaml` for live reload (POSTs /reload to the running daemon) and
`daemon/**/*.py` for full daemon restart. Layout edits do not restart the daemon
because the daemon already supports /reload; Python edits require a fresh process
because Python doesn't hot-reload itself.

Run with: python -m deckd.dev  (or `deckd-dev` once installed)
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from contextlib import suppress
from pathlib import Path

import aiohttp
from watchfiles import Change, awatch

log = logging.getLogger("deckd.dev")

REPO_ROOT = Path(__file__).resolve().parents[2]
DAEMON_DIR = REPO_ROOT / "daemon"
LAYOUTS_DIR = REPO_ROOT / "layouts"
DEFAULT_PORT = 8765


async def _start_daemon(port: int) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,  # populated below
        "-u",
        "-m",
        "deckd",
        "--layouts",
        str(LAYOUTS_DIR / "default.yaml"),
        "--port",
        str(port),
        cwd=str(REPO_ROOT),
        stdout=None,
        stderr=None,
    )


async def _post_reload(port: int) -> None:
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{port}/reload",
                timeout=aiohttp.ClientTimeout(total=2),
            ) as r:
                await r.read()
                log.info("layout reload sent (status=%s)", r.status)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        log.warning("layout reload failed: %s", exc)


def _classify(change: Change, path: str) -> str:
    p = Path(path)
    if p.suffix in {".yaml", ".yml"} and LAYOUTS_DIR in p.parents:
        return "layout"
    if p.suffix == ".py" and DAEMON_DIR in p.parents:
        return "daemon"
    return ""


def _wait_for_port(port: int, timeout_s: float = 5.0) -> None:
    import socket
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            if asyncio.get_event_loop().time() > deadline:
                raise SystemExit(f"daemon did not bind port {port} within {timeout_s}s")
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))


async def supervise(port: int = DEFAULT_PORT) -> None:
    proc = await _start_daemon(port)
    log.info("daemon started (pid=%s) — waiting for port…", proc.pid)
    for _ in range(50):
        if proc.returncode is not None:
            raise SystemExit(f"daemon exited rc={proc.returncode} before binding port {port}")
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            break
        except OSError:
            await asyncio.sleep(0.1)
    else:
        raise SystemExit(f"daemon did not bind port {port} within 5s")
    log.info("daemon listening on :%d", port)

    stop = asyncio.Event()

    def _on_signal(*_args):
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _on_signal)

    try:
        async for changes in awatch(REPO_ROOT, stop_event=stop, step=200):
            if stop.is_set():
                break
            kinds = {_classify(c, p) for c, p in changes}
            if "layout" in kinds:
                log.info("layout changed -> /reload")
                await _post_reload(port)
            if "daemon" in kinds:
                log.info("daemon code changed -> restart")
                if proc.returncode is None:
                    proc.terminate()
                    with suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(proc.wait(), timeout=3)
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
                proc = await _start_daemon(port)
                for _ in range(50):
                    try:
                        reader, writer = await asyncio.open_connection("127.0.0.1", port)
                        writer.close()
                        await writer.wait_closed()
                        log.info("daemon restarted (pid=%s)", proc.pid)
                        break
                    except OSError:
                        await asyncio.sleep(0.1)
    finally:
        if proc.returncode is None:
            with suppress(ProcessLookupError):
                proc.terminate()
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=3)
        if proc.returncode is None:
            with suppress(ProcessLookupError):
                proc.kill()
                await proc.wait()


def main() -> None:
    import sys
    port = int(os.environ.get("DECKD_PORT", str(DEFAULT_PORT)))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(supervise(port=port))


if __name__ == "__main__":
    main()
