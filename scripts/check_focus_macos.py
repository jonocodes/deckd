"""One-shot diagnostic for the macOS focus watcher.

Prints:
  - what osascript reports for the frontmost process (and its window title)
  - whether the auto-ignore rule says "this is the deckd client"
  - which deck ``resolve_deck`` would pick for that focused app

Useful when the daemon's deck doesn't switch as expected: it answers
"is osascript failing?", "is auto-ignore wrongly holding?", and
"is there no matching deck?" without having to read daemon logs.

Requires the flox environment (or any venv with ``pip install -e .``).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


async def _probe(port: int, decks_dir: Path) -> int:
    from deckd.decks import DeckStore, load_decks, resolve_deck
    from deckd.platform import AppInfo
    from deckd.platform_macos import MacFocusBackend

    overlay = decks_dir.parent / f"{decks_dir.name}.macos"
    if not overlay.is_dir():
        overlay = None

    backend = MacFocusBackend()
    try:
        app = await backend.get_active_app()
    except Exception as exc:
        print(f"ERROR: focus query failed ({exc.__class__.__name__}): {exc}")
        print("On macOS this is almost always a TCC permission issue --")
        print("grant Automation permission to the parent shell (Terminal / iTerm / cmux)")
        print("under System Settings -> Privacy & Security -> Automation, then re-run.")
        return 2

    print(f"osascript sees: app_id={app.app_id!r}  title={app.title!r}")

    store: DeckStore = load_decks(decks_dir, overlay)
    resolved = resolve_deck(store, app)

    # Reproduce the auto-ignore check exactly as Server._is_deckd_window does.
    title = (app.title or "").strip()
    port_match = bool(port) and str(port) in title
    exact_match = title.lower() == "deckd"
    print(
        f"auto-ignore:    port_in_title={port_match}  "
        f"exact_title_match={exact_match}  -> holds={port_match or exact_match}"
    )
    print(f"would resolve to deck: {resolved.id!r}")

    if (
        resolved.id == "default"
        and app.app_id
        and app.app_id.lower() in {"firefox", "safari", "chrome"}
    ):
        print(f"hint: {app.app_id!r} has no specific deck in this checkout,")
        print("      so the default fallback is correct.")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="daemon port (matched against the focused window's title by the auto-ignore check)",
    )
    parser.add_argument(
        "--decks-dir",
        type=Path,
        default=Path("decks"),
        help="base decks directory (overlay is auto-discovered as <name>.macos next to it)",
    )
    args = parser.parse_args()

    try:
        rc = asyncio.run(_probe(args.port, args.decks_dir))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
