"""PyInstaller entry point for the deckd Linux AppImage (issue #168).

Frozen by ``packaging/linux/deckd.spec`` into the AppImage payload. It seeds
the bundled layouts into the writable XDG data dir, then runs the daemon
against the bundled client. Only ever frozen — the daemon never imports this.

Extra CLI args pass straight through, so
``./deckd-<version>-x86_64.AppImage --bind 0.0.0.0`` exposes the surface on
the LAN.

One arg is intercepted here rather than passed on:
``--extract-integration DIR`` copies the AppDir's ``usr/share/deckd/integration``
tree to DIR and exits. ``install-system-integration.sh`` uses it as a fallback
when the AppImage runtime can't be asked to extract itself (a binfmt wrapper
like NixOS's ``programs.appimage`` runs the payload directly, so the runtime's
``--appimage-extract`` never sees the flag).
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    from deckd import linux_app
    from deckd.__main__ import main as deckd_main

    extra = sys.argv[1:]
    if extra[:1] == [linux_app.EXTRACT_INTEGRATION_FLAG]:
        if len(extra) != 2:
            raise SystemExit(f"usage: deckd {linux_app.EXTRACT_INTEGRATION_FLAG} DIR")
        try:
            linux_app.extract_integration(Path(extra[1]))
        except (OSError, FileNotFoundError) as exc:
            raise SystemExit(f"error: {exc}") from exc
        return

    sys.argv = ["deckd", *linux_app.build_argv(extra)]
    deckd_main()


if __name__ == "__main__":
    main()
