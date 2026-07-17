"""Dev supervisor: runs the daemon as a child and restarts it on Python edits.

Layout YAML is watched by the daemon itself (see
``Server.run_layouts_watcher``) so live-config editing works regardless of
whether this supervisor is running. This process exists solely because
Python doesn't hot-reload itself — any edit under ``daemon/**/*.py``
requires spawning a fresh process.

Any CLI args this supervisor doesn't recognise are forwarded verbatim to
the child, so ``deckd-dev --host 0.0.0.0 --verbose`` works the same as
``deckd --host 0.0.0.0 --verbose`` (plus the restart-on-edit behaviour).

Run with: python -m deckd.dev  (or `deckd-dev` once installed)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from contextlib import suppress
from pathlib import Path

from watchfiles import Change, awatch

log = logging.getLogger("deckd.dev")

REPO_ROOT = Path(__file__).resolve().parents[2]
DAEMON_DIR = REPO_ROOT / "daemon"
LAYOUTS_DIR = REPO_ROOT / "layouts"
DEFAULT_PORT = 8765


async def _start_daemon(port: int, child_args: list[str]) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-m",
        "deckd",
        "--layouts-dir",
        str(LAYOUTS_DIR),
        "--port",
        str(port),
        *child_args,
        cwd=str(REPO_ROOT),
        stdout=None,
        stderr=None,
    )


def _is_daemon_source(change: Change, path: str) -> bool:
    p = Path(path)
    return p.suffix == ".py" and DAEMON_DIR in p.parents


async def _wait_for_bind(port: int, timeout_s: float = 5.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            if asyncio.get_event_loop().time() > deadline:
                raise SystemExit(f"daemon did not bind port {port} within {timeout_s}s")
            await asyncio.sleep(0.1)


async def supervise(port: int = DEFAULT_PORT, child_args: list[str] | None = None) -> None:
    args = child_args or []
    proc = await _start_daemon(port, args)
    log.info("daemon started (pid=%s) — waiting for port…", proc.pid)
    await _wait_for_bind(port)
    log.info("daemon listening on :%d", port)

    stop = asyncio.Event()

    def _on_signal(*_args):
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _on_signal)

    try:
        async for changes in awatch(DAEMON_DIR, stop_event=stop, step=200):
            if stop.is_set():
                break
            if not any(_is_daemon_source(c, p) for c, p in changes):
                continue
            log.info("daemon code changed -> restart")
            if proc.returncode is None:
                proc.terminate()
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(proc.wait(), timeout=3)
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            proc = await _start_daemon(port, args)
            await _wait_for_bind(port)
            log.info("daemon restarted (pid=%s)", proc.pid)
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
    parser = argparse.ArgumentParser(
        prog="deckd-dev",
        description="Run deckd under a Python-file-restart supervisor.",
        epilog="Any unrecognised args are forwarded to the deckd child process.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="daemon port (also forwarded to the child)",
    )
    args, forward = parser.parse_known_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    asyncio.run(supervise(port=args.port, child_args=forward))


if __name__ == "__main__":
    main()
