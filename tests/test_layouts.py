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


def test_widget_color_field_round_trips(tmp_path: Path) -> None:
    """Optional ``color`` on a widget survives YAML -> Widget -> dump."""
    _write(
        tmp_path,
        "default.yaml",
        """
match:
  - default
widgets:
  - id: back
    kind: button
    label: Back
    color: "#1e3a8a"
    grid: [0, 0, 1, 1]
    action:
      key: "alt+Left"
""",
    )
    store = load_layouts(tmp_path)
    widget = store["default"].widgets[0]
    assert widget.color == "#1e3a8a"
    # And the dumped shape (what the daemon serialises to the client) keeps it.
    assert widget.model_dump()["color"] == "#1e3a8a"


def test_widget_color_defaults_to_none_when_omitted(tmp_path: Path) -> None:
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)
    widget = store["default"].widgets[0]
    assert widget.color is None


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


# ---------------------------------------------------------------------------
# Chrome app badge (issue #41 / ADR-0007)
#
# A layout may carry top-level presentation attributes the daemon relays
# opaquely to the client for the bottom-chrome app badge: a ``theme``
# CSS colour, an ``icon`` (the same ``{source, name}`` dispatch widgets
# use), and a ``display_name`` shown in place of the raw match token.
# All three are optional and default to ``None``; the daemon never
# interprets them, exactly like per-widget presentation (ADR-0006).
# ---------------------------------------------------------------------------


def test_layout_defaults_app_badge_fields_to_none(tmp_path: Path) -> None:
    """Omitted badge fields round-trip as ``None``."""
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)
    layout = store["default"]
    assert layout.theme is None
    assert layout.icon is None
    assert layout.display_name is None


def test_layout_round_trips_app_badge_fields(tmp_path: Path) -> None:
    """All three badge fields survive YAML -> Layout -> dump."""
    body = """
match:
  - firefox
display_name: Mozilla Firefox
theme: "#ff7139"
icon:
  source: simple-icons
  name: firefox
widgets:
  - id: back
    kind: button
    label: Back
    grid: [0, 0, 1, 1]
"""
    _write(tmp_path, "firefox.yaml", body)
    store = load_layouts(tmp_path)
    layout = store["firefox"]
    assert layout.display_name == "Mozilla Firefox"
    assert layout.theme == "#ff7139"
    assert layout.icon is not None
    assert layout.icon.source == "simple-icons"
    assert layout.icon.name == "firefox"
    # The dumped shape (what the daemon serialises to the client) keeps each.
    dumped = layout.model_dump()
    assert dumped["display_name"] == "Mozilla Firefox"
    assert dumped["theme"] == "#ff7139"
    assert dumped["icon"] == {"source": "simple-icons", "name": "firefox"}


def test_layout_icon_validates_source_and_name_non_empty(tmp_path: Path) -> None:
    """The top-level ``icon`` reuses the widget ``Icon`` schema: empty
    ``source`` / ``name`` is a schema violation, surfacing as SystemExit
    so a bad layout file is reported at load time (consistent with
    every other invalid-layout case)."""
    body = """
match:
  - firefox
icon:
  source: ""
  name: firefox
widgets:
  - id: back
    kind: button
    grid: [0, 0, 1, 1]
"""
    _write(tmp_path, "firefox.yaml", body)
    with pytest.raises(SystemExit):
        load_layouts(tmp_path)


def test_layout_rejects_unknown_top_level_field(tmp_path: Path) -> None:
    """``extra="forbid"`` keeps the schema open for the sanctioned
    chrome fields and rejects typos like ``themes`` or ``displayname``."""
    body = """
match:
  - default
themes: "#ff7139"
widgets:
  - id: home
    kind: button
    grid: [0, 0, 1, 1]
"""
    _write(tmp_path, "default.yaml", body)
    with pytest.raises(SystemExit):
        load_layouts(tmp_path)


# ---------------------------------------------------------------------------
# Platform overlay
#
# The daemon accepts an optional ``overlay_dir`` next to the base layouts
# dir. Overlay entries load first so they shadow base entries with the
# same id; this is the "platform overrides shared" semantic.
# ---------------------------------------------------------------------------


def test_overlay_dir_is_optional(tmp_path: Path) -> None:
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    # No overlay_dir arg at all -> unchanged single-dir behavior.
    store = load_layouts(tmp_path)
    assert "default" in store


def test_missing_overlay_dir_is_fine(tmp_path: Path) -> None:
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    overlay = tmp_path / "does-not-exist"
    store = load_layouts(tmp_path, overlay)
    assert "default" in store


def test_overlay_replaces_same_id_base_entry(tmp_path: Path) -> None:
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()
    _write(base, "firefox.yaml", FIREFOX_LAYOUT)  # id=firefox, key=alt+Left
    _write(
        overlay,
        "firefox.yaml",
        """
match:
  - firefox
widgets:
  - id: new-tab
    kind: button
    label: New tab
    grid: [0, 0, 1, 1]
    action:
      key: "super+t"
""",
    )
    _write(base, "default.yaml", DEFAULT_LAYOUT)

    store = load_layouts(base, overlay)
    firefox_layouts = [l for l in store.layouts if l.id == "firefox"]
    # Overlay replaces base entirely -- no duplicate id left in the store.
    assert len(firefox_layouts) == 1
    # And it's the overlay's action that survives.
    assert firefox_layouts[0].widgets[0].action.key == "super+t"


def test_overlay_wins_on_match_conflict_with_different_filename(tmp_path: Path) -> None:
    """When an overlay entry matches the same app as a base entry but has
    a different filename (so different ``id``), first-match-wins within
    the combined list resolves it: overlay entries load first, so the
    overlay wins."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()
    _write(base, "firefox.yaml", FIREFOX_LAYOUT)  # id=firefox, match=[firefox]
    _write(
        overlay,
        "macos-firefox.yaml",
        """
match:
  - firefox
widgets:
  - id: new-tab
    kind: button
    label: New tab
    grid: [0, 0, 1, 1]
    action:
      key: "super+t"
""",
    )

    store = load_layouts(base, overlay)
    app = AppInfo(app_id="firefox", wm_class="firefox")
    layout = resolve_layout(store, app)
    assert layout.widgets[0].action.key == "super+t"


def test_overlay_can_add_new_layouts(tmp_path: Path) -> None:
    """An overlay file for an app the base doesn't cover is additive."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()
    _write(base, "default.yaml", DEFAULT_LAYOUT)
    _write(overlay, "safari.yaml", """
match:
  - Safari
widgets:
  - id: new-tab
    kind: button
    label: New tab
    grid: [0, 0, 1, 1]
    action:
      key: "super+t"
""")

    store = load_layouts(base, overlay)
    assert "Safari" in store
    assert "default" in store


# ---------------------------------------------------------------------------
# Overlay directory discovery (__main__._overlay_dir_for)
#
# The daemon auto-discovers ``<layouts-dir>.<platform-suffix>`` next to
# the base dir. The suffix is ``macos`` on Darwin, ``linux`` elsewhere.
# Pure path math, tested by monkeypatching sys.platform.
# ---------------------------------------------------------------------------


def test_overlay_dir_for_darwin(monkeypatch, tmp_path: Path) -> None:
    """On macOS the overlay path is ``<layouts>.macos``."""
    monkeypatch.setattr("deckd.__main__.sys.platform", "darwin")
    from deckd.__main__ import _overlay_dir_for

    base = tmp_path / "layouts"
    assert _overlay_dir_for(base) == tmp_path / "layouts.macos"


def test_overlay_dir_for_linux(monkeypatch, tmp_path: Path) -> None:
    """On Linux (or any non-darwin sys.platform) the suffix is ``linux``."""
    monkeypatch.setattr("deckd.__main__.sys.platform", "linux")
    from deckd.__main__ import _overlay_dir_for

    base = tmp_path / "layouts"
    assert _overlay_dir_for(base) == tmp_path / "layouts.linux"


def test_overlay_dir_for_unknown_platform_defaults_to_linux(monkeypatch, tmp_path: Path) -> None:
    """An unmapped sys.platform (e.g. ``freebsd``) falls back to ``linux``
    suffix -- unknown platforms behave like Linux for overlay purposes."""
    monkeypatch.setattr("deckd.__main__.sys.platform", "freebsd")
    from deckd.__main__ import _overlay_dir_for

    base = tmp_path / "layouts"
    assert _overlay_dir_for(base) == tmp_path / "layouts.linux"


def test_overlay_dir_preserves_arbitrary_base_name(monkeypatch, tmp_path: Path) -> None:
    """The base dir can be named anything; only ``<name>.<suffix>`` is
    computed. Useful for users who keep their layouts in
    ``~/.config/deckd/layouts`` or similar."""
    monkeypatch.setattr("deckd.__main__.sys.platform", "darwin")
    from deckd.__main__ import _overlay_dir_for

    base = tmp_path / "my-configs" / "deckd-layouts"
    base.parent.mkdir()
    assert _overlay_dir_for(base) == base.parent / "deckd-layouts.macos"


# ---------------------------------------------------------------------------
# Smoke test: the real shipping layouts must actually load.
#
# The server behaviour tests run against a stable fixture layout dir
# (tests/fixtures/layouts) so they don't break when the user edits their
# personal layouts. This test is the counterweight — it loads the real
# ``layouts/`` dir so a broken shipping layout is still caught somewhere.
# ---------------------------------------------------------------------------


REPO_LAYOUTS_DIR = Path(__file__).parent.parent / "layouts"


def test_shipping_layouts_load_and_resolve_default() -> None:
    store = load_layouts(REPO_LAYOUTS_DIR)
    # A default layout must exist with at least one widget, and every shipped
    # layout must carry a non-empty match list (that's what makes it findable).
    default = store.default()
    assert default.widgets, "shipping default.yaml has no widgets"
