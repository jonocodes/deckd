"""Resolver for the ``desktop`` icon source (issue #187).

A deck author can pick ``icon: {source: desktop, name: <desktop-id>}`` to
show an app's own full-colour icon — the one the host's dock/launcher
shows — instead of a bundled Lucide / Simple Icons glyph. It is opt-in
only: nothing in deckd applies a ``desktop`` icon automatically.

Resolution follows the freedesktop specs, read-only and pure Python (no
PyGObject / Gtk, which would weigh down the AppImage / tarball):

1. Index ``applications/**/*.desktop`` across the XDG data dirs. The
   desktop id is the path under ``applications/`` with ``/`` -> ``-``
   (Desktop Entry spec); the first data dir to provide an id wins, and a
   ``Hidden=true`` entry masks lower-precedence copies.
2. Resolve the entry's ``Icon=`` key: an absolute path is used as-is;
   a bare name is looked up in the ``hicolor`` theme (where apps install
   their own icons) across *every* data dir — a flatpak's ``.desktop``
   and its icon are exported side by side, but a Nix-installed app's
   may not be — preferring ``scalable`` SVG, then the largest PNG, then
   ``pixmaps/``. Symbolic icons are never chosen.

The ``/desktop-apps/<id>/icon`` route serves only ids this index found,
so a client-supplied string never becomes a filesystem path.
"""
from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ICON_EXTENSIONS = (".svg", ".png")
CONTENT_TYPES = {".svg": "image/svg+xml", ".png": "image/png"}

# ``scalable`` outranks every raster size; ``48x48@2`` counts as 96.
_SCALABLE_SCORE = 1_000_000
_SIZE_DIR = re.compile(r"^(\d+)x(\d+)(?:@(\d+))?$")
# A pixmap only wins when no theme dir has the icon at any size.
_PIXMAP_SCORE = 0


@dataclass(frozen=True)
class DesktopApp:
    """One installed app with a resolvable icon."""

    id: str
    name: str
    icon: Path


def default_data_dirs(
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    system_dirs: Sequence[Path] | None = None,
) -> list[Path]:
    """The XDG data dirs to search, in precedence order.

    ``XDG_DATA_HOME`` + ``XDG_DATA_DIRS`` first, then the flatpak export
    and Nix profile dirs appended explicitly: a daemon started from a
    systemd user unit, the AppImage, or a non-login shell often has a
    trimmed ``XDG_DATA_DIRS`` that misses them. Only existing dirs are
    returned, de-duplicated by resolved path (Nix profiles are symlinks).
    """
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    data_home = env.get("XDG_DATA_HOME") or str(home / ".local/share")
    data_dirs = [p for p in (env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if p]
    if system_dirs is None:
        system_dirs = [
            Path("/var/lib/flatpak/exports/share"),
            Path("/etc/profiles/per-user") / env.get("USER", "") / "share",
            Path("/run/current-system/sw/share"),
        ]
    candidates = [
        Path(data_home),
        *(Path(p) for p in data_dirs),
        home / ".local/share/flatpak/exports/share",
        home / ".nix-profile/share",
        *system_dirs,
    ]
    result: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        try:
            if not path.is_dir():
                continue
            real = path.resolve()
        except OSError:
            continue
        if real not in seen:
            seen.add(real)
            result.append(path)
    return result


def _size_score(dirname: str) -> int | None:
    if dirname == "scalable":
        return _SCALABLE_SCORE
    m = _SIZE_DIR.match(dirname)
    if not m:
        return None  # ``symbolic`` and anything unrecognised
    return int(m.group(1)) * int(m.group(3) or 1)


def _listdir(path: Path) -> list[Path]:
    try:
        return list(path.iterdir())
    except OSError:
        return []


def _parse_desktop_entry(path: Path) -> dict[str, str] | None:
    """The ``[Desktop Entry]`` group's unlocalised keys, or None if unreadable."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    group: str | None = None
    keys: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            continue
        if group != "Desktop Entry" or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if "[" in key:  # ``Name[de]`` — only the unlocalised value is used
            continue
        keys.setdefault(key, value.strip())
    return keys if group is not None else None


class DesktopIconIndex:
    """Lazily-built, periodically refreshed desktop-id -> icon index.

    Rebuilt on access once ``ttl`` seconds have passed, so an app
    installed while the daemon runs shows up without a restart. ``clock``
    is injectable for tests.
    """

    def __init__(
        self,
        data_dirs: Sequence[Path] | None = None,
        *,
        ttl: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._data_dirs = list(data_dirs) if data_dirs is not None else None
        self._ttl = ttl
        self._clock = clock
        self._built_at: float | None = None
        self._apps: dict[str, DesktopApp] = {}

    def icon_path(self, desktop_id: str) -> Path | None:
        app = self._index().get(desktop_id)
        return app.icon if app else None

    def apps(self) -> list[DesktopApp]:
        """Installed, displayable apps with an icon, sorted by name."""
        return sorted(self._index().values(), key=lambda a: (a.name.casefold(), a.id))

    def _index(self) -> dict[str, DesktopApp]:
        now = self._clock()
        if self._built_at is None or now - self._built_at >= self._ttl:
            self._apps = self._scan()
            self._built_at = now
        return self._apps

    def _scan(self) -> dict[str, DesktopApp]:
        dirs = self._data_dirs if self._data_dirs is not None else default_data_dirs()
        icons = self._scan_icons(dirs)
        entries: dict[str, dict[str, str] | None] = {}
        for data_dir in dirs:
            apps_root = data_dir / "applications"
            try:
                files = sorted(apps_root.rglob("*.desktop"))
            except OSError:
                continue
            for file in files:
                desktop_id = "-".join(file.relative_to(apps_root).with_suffix("").parts)
                if desktop_id in entries:
                    continue  # an earlier data dir already claimed (or masked) it
                keys = _parse_desktop_entry(file)
                if keys is None:
                    continue
                entries[desktop_id] = None if keys.get("Hidden") == "true" else keys
        apps: dict[str, DesktopApp] = {}
        for desktop_id, keys in entries.items():
            if keys is None or keys.get("Type") != "Application" or keys.get("NoDisplay") == "true":
                continue
            icon = self._resolve_icon(keys.get("Icon", ""), icons)
            if icon is not None:
                apps[desktop_id] = DesktopApp(desktop_id, keys.get("Name") or desktop_id, icon)
        return apps

    @staticmethod
    def _scan_icons(dirs: Sequence[Path]) -> dict[str, Path]:
        """Best icon file per icon name across every data dir's hicolor theme."""
        best: dict[str, tuple[int, int, int, Path]] = {}

        def offer(name: str, score: int, order: int, path: Path) -> None:
            # Higher score wins; on a tie, svg over png, then the earlier dir.
            rank = (score, path.suffix == ".svg", -order)
            current = best.get(name)
            if current is None or rank > current[:3]:
                best[name] = (*rank, path)

        for order, data_dir in enumerate(dirs):
            for size_dir in _listdir(data_dir / "icons" / "hicolor"):
                score = _size_score(size_dir.name)
                if score is None:
                    continue
                for file in _listdir(size_dir / "apps"):
                    if file.suffix in ICON_EXTENSIONS and file.is_file():
                        offer(file.stem, score, order, file)
            for file in _listdir(data_dir / "pixmaps"):
                if file.suffix in ICON_EXTENSIONS and file.is_file():
                    offer(file.stem, _PIXMAP_SCORE, order, file)
        return {name: entry[3] for name, entry in best.items() if not name.endswith("-symbolic")}

    @staticmethod
    def _resolve_icon(icon: str, icons: Mapping[str, Path]) -> Path | None:
        if not icon:
            return None
        if os.path.isabs(icon):
            path = Path(icon)
            return path if path.suffix in ICON_EXTENSIONS and path.is_file() else None
        stem, ext = os.path.splitext(icon)
        if ext in ICON_EXTENSIONS:
            icon = stem  # legacy ``Icon=foo.png``
        return icons.get(icon)
