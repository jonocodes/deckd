"""Tests for layout loading and per-app match resolution.

Seam under test: ``load_layouts(scan a directory of YAML files)`` returns a
queryable store that resolves an ``AppInfo`` to the right ``Layout``:
the first layout whose ``match`` list contains the focused app's ``app_id``
or ``wm_class``. When no layout matches, the layout with ``match: [default]``
is returned.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from deckd.layouts import Layout, load_layouts, resolve_layout
from deckd.platform import AppInfo


def _write(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text(body)
    return p


FIREFOX_LAYOUT = """
match:
  - firefox
widgets:
  - id: back
    kind: button
    label: Back
    grid: [0, 0, 1, 1]
    action:
      key: "alt+Left"
"""

TERMINAL_LAYOUT = """
match:
  - org.gnome.Console
widgets:
  - id: new-tab
    kind: button
    label: New tab
    grid: [0, 0, 1, 1]
    action:
      key: "ctrl+shift+t"
"""

DEFAULT_LAYOUT = """
match:
  - default
widgets:
  - id: home
    kind: button
    label: Home
    grid: [0, 0, 1, 1]
    action:
      shell: "xdg-open https://example.com"
"""

UNMATCHED_LAYOUT = """
match: []
widgets:
  - id: orphan
    kind: button
    label: Orphan
    grid: [0, 0, 1, 1]
"""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def test_load_layouts_reads_all_yaml_files(tmp_path: Path) -> None:
    _write(tmp_path, "firefox.yaml", FIREFOX_LAYOUT)
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)

    store = load_layouts(tmp_path)

    names = {l.id for l in store.layouts}
    assert "firefox" in names
    assert "default" in names
    assert len(store.layouts) == 2


def test_load_layouts_uses_match_token_as_layout_id(tmp_path: Path) -> None:
    _write(tmp_path, "firefox.yaml", FIREFOX_LAYOUT)
    store = load_layouts(tmp_path)
    assert "firefox" in store
    assert "nonexistent" not in store


def test_load_layouts_tolerates_non_yaml_files(tmp_path: Path) -> None:
    _write(tmp_path, "firefox.yaml", FIREFOX_LAYOUT)
    (tmp_path / "README.md").write_text("not a layout")
    (tmp_path / "notes.txt").write_text("not a layout")

    store = load_layouts(tmp_path)
    assert len(store.layouts) == 1


def test_load_layouts_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        load_layouts(tmp_path / "nope")


# ---------------------------------------------------------------------------
# Match resolution
# ---------------------------------------------------------------------------


def test_resolve_matches_on_app_id(tmp_path: Path) -> None:
    _write(tmp_path, "firefox.yaml", FIREFOX_LAYOUT)
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)

    app = AppInfo(app_id="firefox", wm_class="firefox", title="YouTube")
    layout = resolve_layout(store, app)
    assert layout is store["firefox"]


def test_resolve_matches_on_wm_class_when_app_id_is_none(tmp_path: Path) -> None:
    _write(tmp_path, "firefox.yaml", FIREFOX_LAYOUT)
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)

    app = AppInfo(app_id=None, wm_class="firefox", title="YouTube")
    layout = resolve_layout(store, app)
    assert layout is store["firefox"]


def test_resolve_falls_back_to_default_layout(tmp_path: Path) -> None:
    _write(tmp_path, "firefox.yaml", FIREFOX_LAYOUT)
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)

    app = AppInfo(app_id="totally.unknown.app", wm_class=None, title=None)
    layout = resolve_layout(store, app)
    assert layout is store["default"]


def test_resolve_picks_specific_layout_over_default(tmp_path: Path) -> None:
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    _write(tmp_path, "terminal.yaml", TERMINAL_LAYOUT)
    store = load_layouts(tmp_path)

    app = AppInfo(app_id="org.gnome.Console", wm_class="org.gnome.Console")
    layout = resolve_layout(store, app)
    assert layout is store["org.gnome.Console"]


def test_resolve_picks_first_matching_layout_in_load_order(tmp_path: Path) -> None:
    """When two layouts could match the same app, the first loaded wins."""
    body_a = """
match:
  - firefox
widgets:
  - id: a
    kind: button
    label: a
    grid: [0, 0, 1, 1]
"""
    body_b = """
match:
  - firefox
  - firefox-developer
widgets:
  - id: b
    kind: button
    label: b
    grid: [0, 0, 1, 1]
"""
    _write(tmp_path, "01-firefox.yaml", body_a)
    _write(tmp_path, "02-firefox.yaml", body_b)
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)

    app = AppInfo(app_id="firefox", wm_class="firefox")
    layout = resolve_layout(store, app)
    # First match wins — deterministic, ordered by file path.
    assert layout.id == "firefox"
    assert layout.widgets[0].id == "a"


def test_resolve_layouts_without_match_list_never_resolve(tmp_path: Path) -> None:
    _write(tmp_path, "orphan.yaml", UNMATCHED_LAYOUT)
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)

    # A real app should still fall back to default, not pick the orphan.
    app = AppInfo(app_id="firefox", wm_class="firefox")
    layout = resolve_layout(store, app)
    assert layout is store["default"]


def test_resolve_returns_default_when_app_id_is_unknown(tmp_path: Path) -> None:
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)

    app = AppInfo(app_id=None, wm_class=None, title="some window")
    layout = resolve_layout(store, app)
    assert layout is store["default"]


# ---------------------------------------------------------------------------
# Layout identity in the LayoutMessage
# ---------------------------------------------------------------------------


def test_layout_id_is_first_match_token(tmp_path: Path) -> None:
    _write(tmp_path, "firefox.yaml", FIREFOX_LAYOUT)
    store = load_layouts(tmp_path)
    firefox = store["firefox"]
    # Layout.id is a *content-derived* identity, decoupled from the filename.
    assert firefox.id == "firefox"


def test_layout_id_is_first_match_token_for_multi_match(tmp_path: Path) -> None:
    body = """
match:
  - code
  - code-insiders
widgets:
  - id: ext
    kind: button
    label: ext
    grid: [0, 0, 1, 1]
"""
    _write(tmp_path, "code.yaml", body)
    store = load_layouts(tmp_path)
    # The id is the first match token; only one entry is registered.
    assert "code" in store
    assert store["code"].id == "code"
    assert store["code"].match == ["code", "code-insiders"]


# ---------------------------------------------------------------------------
# Persistent jogstrip flag (T6/issue #12)
#
# Each layout may suppress the client's persistent right-side jogstrip with
# ``jogstrip: false``. Absent, the flag defaults to True so chrome renders
# the always-on scroll strip by default.
# ---------------------------------------------------------------------------


def test_layout_defaults_jogstrip_enabled_to_true(tmp_path: Path) -> None:
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)
    assert store["default"].jogstrip is True


def test_layout_with_jogstrip_false_parses(tmp_path: Path) -> None:
    body = """
match:
  - default
jogstrip: false
widgets:
  - id: home
    kind: button
    label: Home
    grid: [0, 0, 1, 1]
"""
    _write(tmp_path, "default.yaml", body)
    store = load_layouts(tmp_path)
    assert store["default"].jogstrip is False
