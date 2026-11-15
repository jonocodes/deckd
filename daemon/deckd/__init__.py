"""deckd daemon — app-aware touch control surface for Linux."""

# The version is the git release tag (ADR-0013: CalVer, vYYYYMMDD.N).
# setuptools-scm writes ``_version.py`` when the package is installed (pip /
# uv / nix / the frozen app builds); a bare source tree that was never
# installed reports ``0+unknown``. In an editable install it is as fresh as
# the last ``just setup``.
def _read_version() -> str:
    try:
        from ._version import __version__ as version  # pyright: ignore[reportMissingImports]
    except ImportError:  # pragma: no cover - only in a never-installed tree
        return "0+unknown"
    return str(version)


__version__: str = _read_version()

# HTTP header carrying the shared password on the control endpoints (issue
# #16). Defined here — a dependency-free module both the server and the
# thin ``deckctl`` client import — so the two sides can't drift.
PASSWORD_HEADER = "X-Deckd-Password"
