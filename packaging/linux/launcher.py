"""PyInstaller entry point for the deckd Linux AppImage (issue #168).

Frozen by ``packaging/linux/deckd.spec`` into the AppImage payload. It seeds
the bundled decks into the writable XDG data dir, then runs the daemon
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

A GUI launch (app menu, file-manager double-click) opens the surface in the
default browser once the daemon is up; if a daemon is already running it just
opens the browser and exits. ``--open`` / ``--no-open`` force either way (the
autostart entry passes ``--no-open``). See ``deckd.open_surface``.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path


def main() -> None:
    from deckd import linux_app, open_surface
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

    stdin_isatty = bool(sys.stdin and sys.stdin.isatty())
    want_open, extra = open_surface.resolve_open(
        extra, stdin_isatty=stdin_isatty, environ=os.environ
    )
    argv = linux_app.build_argv(extra)
    if want_open:
        url = open_surface.surface_url(argv)
        if url is None:
            print(
                "deckd: not listening on loopback; open the surface from its LAN URL",
                file=sys.stderr,
            )
        elif open_surface.launch_or_attach(
            url,
            spawn=lambda job: threading.Thread(target=job, daemon=True).start(),
        ):
            return

    sys.argv = ["deckd", *argv]
    deckd_main()


if __name__ == "__main__":
    main()
