"""Static-file check for the PWA manifest (T7 / issue #13).

Guards against accidental deletion or field-removal — the manifest lives
in ``client/public/`` and is copied verbatim into ``client/dist/`` at
Vite build time, so a build-free filesystem read is enough to catch
regressions without spinning up a daemon or a browser.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
CLIENT_PUBLIC = REPO_ROOT / "client" / "public"
CLIENT_INDEX = REPO_ROOT / "client" / "index.html"

MANIFEST_PATH = CLIENT_PUBLIC / "manifest.json"
ICON_PATH = CLIENT_PUBLIC / "icon.svg"


def test_manifest_file_exists() -> None:
    assert MANIFEST_PATH.is_file(), f"missing PWA manifest at {MANIFEST_PATH}"


def test_manifest_is_valid_json() -> None:
    json.loads(MANIFEST_PATH.read_text())


@pytest.fixture
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def test_manifest_declares_standalone_display(manifest: dict) -> None:
    """ADR-0004: PWA installs fullscreen with no browser chrome."""
    assert manifest["display"] == "standalone"


def test_manifest_does_not_lock_orientation(manifest: dict) -> None:
    """ADR-0004: both portrait and landscape are supported."""
    # ``"any"`` or absent both mean "don't lock". Anything else is a regression.
    assert manifest.get("orientation", "any") == "any"


def test_manifest_has_install_metadata(manifest: dict) -> None:
    """Fields Chrome uses to decide the install prompt is eligible."""
    assert manifest["name"]
    assert manifest["short_name"]
    assert manifest["start_url"]
    assert manifest["scope"]


def test_manifest_theme_matches_html_meta(manifest: dict) -> None:
    """Manifest theme colour must match the ``<meta name="theme-color">`` in
    index.html so the OS status bar doesn't flash on install."""
    assert manifest["theme_color"] in CLIENT_INDEX.read_text()


def test_manifest_lists_at_least_one_icon(manifest: dict) -> None:
    icons = manifest.get("icons", [])
    assert len(icons) >= 1
    for icon in icons:
        assert icon.get("src")
        assert icon.get("type")
        # ``sizes`` may be ``"any"`` for SVGs.
        assert icon.get("sizes")


def test_icon_file_exists_and_is_svg() -> None:
    assert ICON_PATH.is_file(), f"missing icon at {ICON_PATH}"
    body = ICON_PATH.read_text()
    assert body.lstrip().startswith("<svg")
    # Maskable icons need a padded safe zone; the design leaves ~15% margin
    # around the 512x512 canvas. Guard against someone shrinking it.
    assert 'viewBox="0 0 512 512"' in body
