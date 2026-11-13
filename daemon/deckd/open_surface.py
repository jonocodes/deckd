"""Open the control surface in the desktop browser when the AppImage is launched
from the GUI (issue #168).

deckd has no window: the daemon serves the web client and everything else
happens in a browser. Launched from a terminal that is fine — the log says
where it is listening. Launched from an app menu or a file-manager
double-click, it looks like nothing happened. So the packaged launcher opens
the surface in the default browser once the daemon is up, and when a daemon is
already running (autostarted at login, or a second click) it just opens the
browser and exits instead of failing on the busy port.

Whether to open is decided by :func:`resolve_open`: explicit ``--open`` /
``--no-open`` win; otherwise it opens only when there is no terminal on stdin
and a graphical session is present. The autostart entry passes ``--no-open``
so logging in never pops a browser.

Everything here is injectable (probe, opener, clock) so it is unit-tested
without a network, a browser, or a frozen bundle.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping

__all__ = [
    "NO_OPEN_FLAG",
    "OPEN_FLAG",
    "browser_env",
    "launch_or_attach",
    "open_url",
    "open_when_ready",
    "probe",
    "resolve_open",
    "surface_url",
]

OPEN_FLAG = "--open"
NO_OPEN_FLAG = "--no-open"

# Bind specs that make the daemon reachable from this machine's own browser.
_V4_LOCAL = {"127.0.0.1", "0.0.0.0", "localhost"}
_V6_LOCAL = {"::1", "::"}


def resolve_open(
    extra: list[str],
    *,
    stdin_isatty: bool,
    environ: Mapping[str, str],
) -> tuple[bool, list[str]]:
    """Strip ``--open`` / ``--no-open`` from ``extra`` and decide whether to open.

    The last explicit flag wins. Without one, open only for a GUI launch: no
    terminal on stdin *and* a display to open a browser on. ``--help`` never
    opens anything.
    """
    explicit: bool | None = None
    rest: list[str] = []
    for arg in extra:
        if arg == OPEN_FLAG:
            explicit = True
        elif arg == NO_OPEN_FLAG:
            explicit = False
        else:
            rest.append(arg)
    if "-h" in rest or "--help" in rest:
        return False, rest
    if explicit is not None:
        return explicit, rest
    has_display = bool(environ.get("WAYLAND_DISPLAY") or environ.get("DISPLAY"))
    return (not stdin_isatty and has_display), rest


def surface_url(argv: list[str]) -> str | None:
    """The URL this machine's browser should open for a daemon started with ``argv``.

    ``None`` when the daemon won't be reachable on loopback (bound only to a
    LAN address or an interface) or its port is kernel-picked (``--port 0``).
    """
    from .__main__ import parse_args

    args = parse_args(argv)
    if args.port == 0:
        return None
    binds = args.bind
    if binds is None or any(b in _V4_LOCAL for b in binds):
        return f"http://127.0.0.1:{args.port}/"
    if any(b in _V6_LOCAL for b in binds):
        return f"http://[::1]:{args.port}/"
    return None


def probe(url: str, timeout: float = 1.0) -> bool:
    """True when a deckd daemon answers ``/health`` at ``url``.

    Checks the body's shape, not just a 200, so an unrelated server holding
    the port isn't mistaken for a running deckd.
    """
    try:
        with urllib.request.urlopen(f"{url}health", timeout=timeout) as resp:
            body = json.loads(resp.read())
    except (OSError, ValueError):
        return False
    return isinstance(body, dict) and body.get("ok") is True and "hostname" in body


def browser_env(environ: Mapping[str, str], *, frozen: bool) -> dict[str, str]:
    """The environment to launch the browser with.

    A PyInstaller bundle points ``LD_LIBRARY_PATH`` at its own libraries and
    saves the caller's value in ``LD_LIBRARY_PATH_ORIG``. A browser that
    inherits the bundle's path loads the wrong libssl/libstdc++ and crashes,
    so restore the original (or drop it) before handing off to ``xdg-open``.
    """
    env = dict(environ)
    if not frozen:
        return env
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig:
        env["LD_LIBRARY_PATH"] = orig
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def open_url(
    url: str,
    *,
    environ: Mapping[str, str] | None = None,
    frozen: bool | None = None,
    popen: Callable[..., object] = subprocess.Popen,
) -> bool:
    """Hand ``url`` to ``xdg-open``, detached. False when it isn't installed."""
    env = browser_env(
        os.environ if environ is None else environ,
        frozen=bool(getattr(sys, "frozen", False)) if frozen is None else frozen,
    )
    try:
        popen(
            ["xdg-open", url],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        print(f"deckd: could not run xdg-open; open {url} in a browser", file=sys.stderr)
        return False
    return True


def open_when_ready(
    url: str,
    *,
    is_up: Callable[[str], bool] = probe,
    opener: Callable[[str], bool] = open_url,
    timeout: float = 30.0,
    interval: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Poll until the daemon answers, then open the browser once.

    Gives up after ``timeout`` seconds (the daemon failed to start — its own
    error is in the log) without opening anything.
    """
    deadline = clock() + timeout
    while True:
        if is_up(url):
            return opener(url)
        if clock() >= deadline:
            return False
        sleep(interval)


def launch_or_attach(
    url: str,
    *,
    is_up: Callable[[str], bool] = probe,
    opener: Callable[[str], bool] = open_url,
    spawn: Callable[[Callable[[], object]], None],
) -> bool:
    """Decide what a GUI launch does. True means "done, exit now".

    A daemon already serving ``url`` → open the browser and exit, so a second
    click (or a click after autostart) never fights over the port. Otherwise
    schedule :func:`open_when_ready` via ``spawn`` and let the caller start
    the daemon.
    """
    if is_up(url):
        print(f"deckd is already running at {url}; opening it", file=sys.stderr)
        opener(url)
        return True
    spawn(lambda: open_when_ready(url, is_up=is_up, opener=opener))
    return False
