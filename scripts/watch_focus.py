"""Print active app/window changes for Spike #2.

Runs on any platform that ``default_backend()`` can dispatch: GNOME
Wayland (extension over D-Bus), any X11 session (``xdotool``), or
macOS (osascript). On failure, prints a backend-specific install
hint.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from deckd.platform import FocusBackendUnavailable, default_backend


async def watch(*, once: bool, interval_s: float) -> None:
    backend = default_backend()
    if once:
        app = await backend.get_active_app()
        print_app(app)
        return

    async for app in backend.watch_active_app(interval_s=interval_s):
        print_app(app)


def print_app(app) -> None:
    print(
        f"app_id={app.app_id!r} wm_class={app.wm_class!r} "
        f"pid={app.pid!r} title={app.title!r}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="watch_focus.py")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=0.1)
    args = parser.parse_args()
    try:
        asyncio.run(watch(once=args.once, interval_s=args.interval))
    except FocusBackendUnavailable as exc:
        print(f"focus watcher unavailable: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"hint: {exc.hint}", file=sys.stderr)
        else:
            print(
                "hint: run `just install-focus-extension`, then log out/in "
                "if GNOME has not loaded it yet",
                file=sys.stderr,
            )
        raise SystemExit(1) from exc
    except RuntimeError as exc:
        print(f"focus watcher unavailable: {exc}", file=sys.stderr)
        print(
            "hint: run `just install-focus-extension`, then log out/in "
            "if GNOME has not loaded it yet",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
