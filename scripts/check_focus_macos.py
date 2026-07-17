"""One-shot diagnostic for the macOS focus watcher.

Prints:
  - what osascript reports for the frontmost process (and its window title)
  - whether the auto-ignore rule says "this is the deckd client"
  - which layout ``resolve_layout`` would pick for that focused app

Useful when the daemon's layout doesn't switch as expected: it answers
"is osascript failing?", "is auto-ignore wrongly holding?", and
"is there no matching layout?" without having to read daemon logs.

Requires the flox environment (or any venv with ``pip install -e .``).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


async def _probe() -> None:
    from deckd.layouts import LayoutStore, load_layouts, resolve_layout
    from deckd.platform import AppInfo
    from deckd.platform_macos import MacFocusBackend

    base = Path("layouts")
    overlay = Path("layouts.macos") if Path("layouts.macos").is_dir() else None

    backend = MacFocusBackend()
    try:
        app = await backend.get_active_app()
    except Exception as exc:
        print(f"ERROR: focus query failed ({exc.__class__.__name__}): {exc}")
        print("On macOS this is almost always a TCC permission issue --")
        print("grant Automation permission to the parent shell (Terminal / iTerm / cmux)")
        print("under System Settings -> Privacy & Security -> Automation, then re-run.")
        sys.exit(2)

    print(f"osascript sees: app_id={app.app_id!r}  title={app.title!r}")

    store: LayoutStore = load_layouts(base, overlay)
    resolved = resolve_layout(store, app)

    # Reproduce the auto-ignore check exactly as Server._is_deckd_window does.
    title = (app.title or "").strip()
    port = 8765
    port_match = bool(port) and str(port) in title
    exact_match = title.lower() == "deckd"
    auto_ignore = port_match or exact_match
    print(f"auto-ignore:    port_in_title={port_match}  exact_title_match={exact_match}  -> holds={auto_ignore}")
    print(f"would resolve to layout: {resolved.id!r}")

    if resolved.id in {l.id for l in store.layouts if l.id == "default"}:
        # Add a hint if the user's app_id is something we'd expect to see
        # a layout for but don't.
        if app.app_id and app.app_id.lower() in {"firefox", "safari", "chrome"}:
            print(f"hint: {app.app_id!r} has no specific layout in this checkout,")
            print("      so the default fallback is correct.")


def main() -> None:
    try:
        asyncio.run(_probe())
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
