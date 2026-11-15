"""Unit tests for the ``desktop`` icon source's resolver (issue #187).

Every test builds a throwaway XDG data tree under ``tmp_path`` — a
``applications/*.desktop`` entry plus a ``icons/hicolor/<size>/apps``
theme — and points the index at it, so nothing reads the host's real
icon theme.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))

from deckd.desktop_icons import DesktopIconIndex, default_data_dirs


def _desktop(data: Path, desktop_id: str, body: str) -> None:
    path = data / "applications" / f"{desktop_id}.desktop"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _app(data: Path, desktop_id: str, *, name: str, icon: str, extra: str = "") -> None:
    _desktop(
        data,
        desktop_id,
        f"[Desktop Entry]\nType=Application\nName={name}\nIcon={icon}\nExec=true\n{extra}",
    )


def _icon(data: Path, size: str, name: str, ext: str = "svg") -> Path:
    path = data / "icons" / "hicolor" / size / "apps" / f"{name}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"{size}/{name}.{ext}".encode())
    return path


def test_resolves_desktop_id_to_scalable_svg(tmp_path: Path) -> None:
    _app(tmp_path, "com.gexperts.Tilix", name="Tilix", icon="com.gexperts.Tilix")
    svg = _icon(tmp_path, "scalable", "com.gexperts.Tilix")
    _icon(tmp_path, "48x48", "com.gexperts.Tilix", "png")

    index = DesktopIconIndex([tmp_path])

    assert index.icon_path("com.gexperts.Tilix") == svg


def test_prefers_largest_png_when_no_svg(tmp_path: Path) -> None:
    _app(tmp_path, "org.videolan.VLC", name="VLC", icon="vlc")
    _icon(tmp_path, "48x48", "vlc", "png")
    big = _icon(tmp_path, "256x256", "vlc", "png")
    _icon(tmp_path, "128x128", "vlc", "png")

    assert DesktopIconIndex([tmp_path]).icon_path("org.videolan.VLC") == big


def test_hidpi_scale_dirs_count_as_larger(tmp_path: Path) -> None:
    _app(tmp_path, "a", name="A", icon="a")
    _icon(tmp_path, "128x128", "a", "png")
    hidpi = _icon(tmp_path, "128x128@2", "a", "png")

    assert DesktopIconIndex([tmp_path]).icon_path("a") == hidpi


def test_falls_back_to_pixmaps(tmp_path: Path) -> None:
    _app(tmp_path, "code", name="Visual Studio Code", icon="vscode")
    pixmap = tmp_path / "pixmaps" / "vscode.png"
    pixmap.parent.mkdir(parents=True)
    pixmap.write_bytes(b"png")

    assert DesktopIconIndex([tmp_path]).icon_path("code") == pixmap


def test_theme_icon_beats_pixmap(tmp_path: Path) -> None:
    _app(tmp_path, "code", name="Code", icon="vscode")
    (tmp_path / "pixmaps").mkdir()
    (tmp_path / "pixmaps" / "vscode.png").write_bytes(b"png")
    themed = _icon(tmp_path, "16x16", "vscode", "png")

    assert DesktopIconIndex([tmp_path]).icon_path("code") == themed


def test_absolute_icon_path(tmp_path: Path) -> None:
    art = tmp_path / "opt" / "logo.png"
    art.parent.mkdir()
    art.write_bytes(b"png")
    _app(tmp_path, "tool", name="Tool", icon=str(art))

    assert DesktopIconIndex([tmp_path]).icon_path("tool") == art


def test_icon_name_with_extension_is_stripped(tmp_path: Path) -> None:
    _app(tmp_path, "old", name="Old", icon="old-app.png")
    png = _icon(tmp_path, "64x64", "old-app", "png")

    assert DesktopIconIndex([tmp_path]).icon_path("old") == png


def test_icon_found_in_a_different_data_dir(tmp_path: Path) -> None:
    """The flatpak / Nix case: the .desktop file and its icon can live in
    different XDG data dirs; the theme is searched across all of them."""
    apps_dir = tmp_path / "flatpak-exports"
    icons_dir = tmp_path / "system"
    _app(apps_dir, "com.spotify.Client", name="Spotify", icon="com.spotify.Client")
    svg = _icon(icons_dir, "scalable", "com.spotify.Client")

    assert DesktopIconIndex([apps_dir, icons_dir]).icon_path("com.spotify.Client") == svg


def test_earlier_data_dir_wins_for_same_desktop_id(tmp_path: Path) -> None:
    user, system = tmp_path / "user", tmp_path / "system"
    _app(user, "app", name="User copy", icon="user-icon")
    _app(system, "app", name="System copy", icon="system-icon")
    user_icon = _icon(system, "scalable", "user-icon")
    _icon(system, "scalable", "system-icon")

    index = DesktopIconIndex([user, system])

    assert index.icon_path("app") == user_icon
    assert [a.name for a in index.apps()] == ["User copy"]


def test_hidden_entry_masks_lower_precedence_copy(tmp_path: Path) -> None:
    user, system = tmp_path / "user", tmp_path / "system"
    _desktop(user, "app", "[Desktop Entry]\nType=Application\nName=App\nHidden=true\n")
    _app(system, "app", name="App", icon="app")
    _icon(system, "scalable", "app")

    index = DesktopIconIndex([user, system])

    assert index.icon_path("app") is None
    assert index.apps() == []


def test_subdirectory_desktop_ids_use_dashes(tmp_path: Path) -> None:
    """Desktop Entry spec: ``applications/kde4/foo.desktop`` -> ``kde4-foo``."""
    _app(tmp_path, "kde4/kate", name="Kate", icon="kate")
    svg = _icon(tmp_path, "scalable", "kate")

    assert DesktopIconIndex([tmp_path]).icon_path("kde4-kate") == svg


def test_apps_lists_only_entries_with_a_resolvable_icon(tmp_path: Path) -> None:
    _app(tmp_path, "b.app", name="Bravo", icon="b")
    _app(tmp_path, "a.app", name="alpha", icon="a")
    _app(tmp_path, "noicon", name="No icon", icon="missing")
    _desktop(tmp_path, "blank", "[Desktop Entry]\nType=Application\nName=Blank\n")
    _app(tmp_path, "hidden", name="Hidden", icon="a", extra="NoDisplay=true\n")
    _app(tmp_path, "link", name="Link", icon="a", extra="")
    (tmp_path / "applications" / "link.desktop").write_text(
        "[Desktop Entry]\nType=Link\nName=Link\nIcon=a\nURL=https://example.com\n"
    )
    _icon(tmp_path, "scalable", "a")
    _icon(tmp_path, "scalable", "b")

    apps = DesktopIconIndex([tmp_path]).apps()

    # Case-insensitive sort by display name.
    assert [(a.id, a.name) for a in apps] == [("a.app", "alpha"), ("b.app", "Bravo")]


def test_ignores_keys_outside_desktop_entry_group_and_localised_names(tmp_path: Path) -> None:
    _desktop(
        tmp_path,
        "app",
        "# comment\n[Desktop Entry]\nType=Application\nName[de]=Anwendung\nName=App\n"
        "Icon=app\n\n[Desktop Action new]\nName=New window\nIcon=other\n",
    )
    svg = _icon(tmp_path, "scalable", "app")

    index = DesktopIconIndex([tmp_path])

    assert index.icon_path("app") == svg
    assert [a.name for a in index.apps()] == ["App"]


def test_symbolic_icons_are_never_chosen(tmp_path: Path) -> None:
    _app(tmp_path, "app", name="App", icon="app")
    _icon(tmp_path, "symbolic", "app")
    png = _icon(tmp_path, "32x32", "app", "png")

    assert DesktopIconIndex([tmp_path]).icon_path("app") == png


def test_unknown_and_traversal_ids_resolve_to_none(tmp_path: Path) -> None:
    _app(tmp_path, "app", name="App", icon="app")
    _icon(tmp_path, "scalable", "app")
    index = DesktopIconIndex([tmp_path])

    for bad in ("nope", "../app", "app/../../etc/passwd", "", "/etc/passwd"):
        assert index.icon_path(bad) is None


def test_missing_and_unreadable_dirs_are_skipped(tmp_path: Path) -> None:
    _desktop(tmp_path, "broken", "\xff\xfe not a desktop file")
    index = DesktopIconIndex([tmp_path / "does-not-exist", tmp_path])

    assert index.apps() == []


def test_index_rescans_after_ttl(tmp_path: Path) -> None:
    now = [0.0]
    index = DesktopIconIndex([tmp_path], ttl=30.0, clock=lambda: now[0])
    assert index.icon_path("late") is None

    _app(tmp_path, "late", name="Late", icon="late")
    _icon(tmp_path, "scalable", "late")
    now[0] = 10.0
    assert index.icon_path("late") is None  # still cached

    now[0] = 31.0
    assert index.icon_path("late") is not None


def test_default_data_dirs_include_xdg_flatpak_and_nix(tmp_path: Path) -> None:
    home = tmp_path / "home"
    for p in (
        home / ".local/share",
        home / ".local/share/flatpak/exports/share",
        home / ".nix-profile/share",
        tmp_path / "usr/share",
    ):
        p.mkdir(parents=True)

    dirs = default_data_dirs(
        env={"XDG_DATA_DIRS": f"{tmp_path / 'usr/share'}:{tmp_path / 'missing'}", "USER": "jo"},
        home=home,
        system_dirs=[],
    )

    assert dirs == [
        home / ".local/share",
        tmp_path / "usr/share",
        home / ".local/share/flatpak/exports/share",
        home / ".nix-profile/share",
    ]


def test_default_data_dirs_dedupes_symlinked_paths(tmp_path: Path) -> None:
    home = tmp_path / "home"
    real = tmp_path / "real-share"
    real.mkdir(parents=True)
    home.mkdir()
    (home / ".nix-profile").mkdir()
    (home / ".nix-profile" / "share").symlink_to(real)

    dirs = default_data_dirs(
        env={"XDG_DATA_HOME": str(real), "XDG_DATA_DIRS": str(real)}, home=home, system_dirs=[]
    )

    assert dirs == [real]
