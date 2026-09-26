"""Platform-independent helpers for the packaged desktop artifacts.

Both the macOS app bundle (#165) and the Linux AppImage (#168) need the same
mechanical pieces: locate the frozen payload, find the bundled client and
layouts, seed layouts into a writable directory on first run, read the version
seam, and build the daemon argv. Those live here so they can be unit-tested on
any host, independent of the platform that ships them.

``deckd.macos_app`` and ``deckd.linux_app`` re-export what their wrappers need.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

DEFAULT_PORT = 8765


def resource_root() -> Path:
    """Directory holding the bundled payload.

    PyInstaller sets ``sys._MEIPASS`` to the onedir payload; in a source
    checkout we fall back to the repo root so the packaging entry points can be
    exercised without freezing.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[2]


def client_dist(root: Path) -> Path:
    """Bundled client build (``client/dist`` copied to ``web``)."""
    return root / "web"


def layouts_src(root: Path) -> Path:
    """Bundled layouts directory."""
    return root / "layouts"


def overlay_src(root: Path, suffix: str) -> Path:
    """Bundled per-platform overlay layouts (``layouts.<suffix>``)."""
    return root / f"layouts.{suffix}"


def bundle_version(pyproject: Path | None = None) -> str:
    """The version stamped into the artifact.

    ``DECKD_VERSION`` wins when set — release CI passes the git tag (minus a
    leading ``v``), so the tag is the single source for a release and the
    artifact name matches. Local builds fall back to ``version`` in
    ``pyproject.toml``.
    """
    override = os.environ.get("DECKD_VERSION", "").strip()
    if override:
        return override
    path = pyproject or Path(__file__).resolve().parents[2] / "pyproject.toml"
    for line in path.read_text().splitlines():
        if line.startswith("version = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise ValueError(f"no version found in {path}")


def seed_layouts(
    src: Path, dest: Path, *, overlay: Path | None = None, overlay_suffix: str = "macos"
) -> bool:
    """Copy bundled layouts into the writable data dir on first run.

    Returns ``True`` when it seeded, ``False`` when ``dest`` already existed.
    An existing directory is never overwritten, so a user's hand-edited
    layouts survive an upgrade (mirrors the Nix module's seed-once behaviour).
    The per-platform overlay is copied to the sibling ``<dest>.<suffix>``
    directory the daemon auto-discovers.
    """
    if dest.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    if overlay is not None and overlay.is_dir():
        overlay_dest = dest.parent / f"{dest.name}.{overlay_suffix}"
        if not overlay_dest.exists():
            shutil.copytree(overlay, overlay_dest)
    return True


def app_argv(
    *,
    layouts_dir: Path,
    client_dist: Path,
    port: int = DEFAULT_PORT,
    bind: list[str] | None = None,
    password_file: Path | None = None,
    log_file: Path | None = None,
    verbose: bool = False,
) -> list[str]:
    """Build the daemon argv the packaged entry points pass to ``parse_args``.

    Localhost-only unless ``bind`` is given, so the default stays safe.
    """
    argv = [
        "--layouts-dir", str(layouts_dir),
        "--client-dist", str(client_dist),
        "--port", str(port),
    ]
    for addr in bind or []:
        argv += ["--bind", addr]
    if password_file is not None:
        argv += ["--password-file", str(password_file)]
    if log_file is not None:
        argv += ["--log-file", str(log_file)]
    if verbose:
        argv.append("--verbose")
    return argv
