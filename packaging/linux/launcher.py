"""PyInstaller entry point for the deckd Linux AppImage (issue #168).

Frozen by ``packaging/linux/deckd.spec`` into the AppImage payload. It seeds
the bundled layouts into the writable XDG data dir, then runs the daemon
against the bundled client. Only ever frozen — the daemon never imports this.

Extra CLI args pass straight through, so
``./deckd-<version>-x86_64.AppImage --bind 0.0.0.0`` exposes the surface on
the LAN.
"""
from __future__ import annotations

import sys


def main() -> None:
    from deckd.__main__ import main as deckd_main
    from deckd.linux_app import build_argv

    extra = sys.argv[1:]
    sys.argv = ["deckd", *build_argv(extra)]
    deckd_main()


if __name__ == "__main__":
    main()
