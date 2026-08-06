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

from deckd.layouts import Layout, Widget, load_layouts, resolve_layout
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
    action:
      shell: "xdg-open https://example.com"
"""

UNMATCHED_LAYOUT = """
match: []
widgets:
  - id: orphan
    kind: button
    label: Orphan
"""




def test_media_schema_accepts_typed_controls_and_volume_fallback_actions() -> None:
    widget = Widget.model_validate(
        {
            "id": "media",
            "kind": "media",
            "controls": ["play", "volume"],
            "volume_up_action": {"key": "volumeup"},
            "volume_down_action": {"key": "volumedown"},
        }
    )
    assert widget.controls == ["play", "volume"]


def test_raise_action_round_trips_from_yaml_shape() -> None:
    widget = Widget.model_validate(
        {"id": "raise", "kind": "button", "action": {"raise": "org.mozilla.firefox"}}
    )
    assert widget.action is not None
    assert widget.action.raise_ == "org.mozilla.firefox"
    assert widget.action.model_dump(by_alias=True)["raise"] == "org.mozilla.firefox"


@pytest.mark.parametrize("controls", [[], ["play", "play"], ["unknown"]])
def test_media_schema_rejects_invalid_controls(controls: list[str]) -> None:
    with pytest.raises(ValueError):
        Widget.model_validate({"id": "media", "kind": "media", "controls": controls})


def test_media_schema_rejects_empty_password_ref() -> None:
    with pytest.raises(ValueError):
        Widget.model_validate(
            {"id": "media", "kind": "media", "media_http": {"password_ref": ""}}
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("controls", ["play"]),
        ("media_http", {}),
        ("art_source", ["vlc"]),
        ("previous_action", {"key": "left"}),
        ("next_action", {"key": "right"}),
        ("volume_up_action", {"key": "volumeup"}),
        ("volume_down_action", {"key": "volumedown"}),
    ],
)
def test_media_only_fields_rejected_on_other_widgets(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="media-only"):
        Widget.model_validate({"id": "button", "kind": "button", field: value})


# --- Reflow schema (ADR-0010): size span, blank, overflow ------------------


def test_widget_size_defaults_to_none() -> None:
    """An absent ``size`` is a plain 1x1 cell; there is no ``grid`` field."""
    w = Widget.model_validate({"id": "b", "kind": "button"})
    assert w.size is None
    assert not hasattr(w, "grid")


@pytest.mark.parametrize("size", [[2, 1], [1, 3], "full"])
def test_widget_accepts_valid_size(size: object) -> None:
    w = Widget.model_validate({"id": "b", "kind": "button", "size": size})
    assert w.size == size


@pytest.mark.parametrize("size", [[0, 1], [1, -2], [1], [1, 2, 3], "big"])
def test_widget_rejects_bad_size(size: object) -> None:
    with pytest.raises(ValueError):
        Widget.model_validate({"id": "b", "kind": "button", "size": size})


def test_blank_widget_accepts_only_size() -> None:
    blank = Widget.model_validate({"id": "gap", "kind": "blank", "size": [2, 1]})
    assert blank.kind == "blank"
    assert blank.size == [2, 1]


@pytest.mark.parametrize(
    "field,value",
    [
        ("label", "x"),
        ("icon", {"source": "lucide", "name": "x"}),
        ("color", "#fff"),
        ("action", {"key": "a"}),
    ],
)
def test_blank_widget_rejects_content_fields(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="blank"):
        Widget.model_validate({"id": "gap", "kind": "blank", field: value})


def test_layout_overflow_defaults_to_shrink_to_fit() -> None:
    layout = Layout.model_validate({"match": ["x"], "widgets": []})
    assert layout.overflow == "shrink-to-fit"


def test_layout_accepts_shrink_to_fit_overflow() -> None:
    layout = Layout.model_validate(
        {"match": ["x"], "widgets": [], "overflow": "shrink-to-fit"}
    )
    assert layout.overflow == "shrink-to-fit"


def test_layout_rejects_unknown_overflow() -> None:
    with pytest.raises(ValueError):
        Layout.model_validate({"match": ["x"], "widgets": [], "overflow": "wrap"})




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
"""
    body_b = """
match:
  - firefox
  - firefox-developer
widgets:
  - id: b
    kind: button
    label: b
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


SITE_LAYOUT = """
match:
  - "title:*- YouTube*"
widgets:
  - id: play
    kind: button
    label: Play
    action:
      key: "k"
"""


def test_resolve_matches_on_title_glob(tmp_path: Path) -> None:
    _write(tmp_path, "youtube.yaml", SITE_LAYOUT)
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)

    app = AppInfo(
        app_id="firefox",
        wm_class="firefox",
        title="Some Video - YouTube — Mozilla Firefox",
    )
    assert resolve_layout(store, app).id == "title:*- YouTube*"


def test_resolve_title_match_is_case_insensitive(tmp_path: Path) -> None:
    _write(tmp_path, "youtube.yaml", SITE_LAYOUT)
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)

    app = AppInfo(app_id="firefox", wm_class="firefox", title="clip - youtube")
    assert resolve_layout(store, app).id == "title:*- YouTube*"


def test_resolve_title_match_wins_over_generic_app_layout(tmp_path: Path) -> None:
    """A ``title:`` site layout beats a generic browser layout that also
    matches, regardless of file load order."""
    # firefox.yaml sorts before youtube.yaml, so without site-priority the
    # generic firefox layout would win first-match-wins.
    _write(tmp_path, "firefox.yaml", FIREFOX_LAYOUT)
    _write(tmp_path, "youtube.yaml", SITE_LAYOUT)
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)

    app = AppInfo(
        app_id="firefox",
        wm_class="firefox",
        title="Some Video - YouTube — Mozilla Firefox",
    )
    assert resolve_layout(store, app).id == "title:*- YouTube*"


def test_resolve_falls_back_to_app_layout_when_title_does_not_match(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "firefox.yaml", FIREFOX_LAYOUT)
    _write(tmp_path, "youtube.yaml", SITE_LAYOUT)
    _write(tmp_path, "default.yaml", DEFAULT_LAYOUT)
    store = load_layouts(tmp_path)

    app = AppInfo(app_id="firefox", wm_class="firefox", title="Hacker News")
    assert resolve_layout(store, app).id == "firefox"


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
"""
    _write(tmp_path, "code.yaml", body)
    store = load_layouts(tmp_path)
    # The id is the first match token; only one entry is registered.
    assert "code" in store
    assert store["code"].id == "code"
    assert store["code"].match == ["code", "code-insiders"]


def test_resolve_id_maps_friendly_names_to_canonical_id(tmp_path: Path) -> None:
    """The ``?layout=`` demo pin resolves friendly names case-insensitively
    against id / display_name / match tokens, so ``tilix`` finds the layout
    whose id is the reverse-DNS token ``com.gexperts.Tilix``."""
    body = """
match:
  - com.gexperts.Tilix
  - Tilix
display_name: Tilix
widgets:
  - id: split
    kind: button
    label: split
"""
    _write(tmp_path, "tilix.yaml", body)
    store = load_layouts(tmp_path)
    canonical = "com.gexperts.Tilix"
    assert store.resolve_id(canonical) == canonical  # exact id
    assert store.resolve_id("tilix") == canonical  # display_name, case-folded
    assert store.resolve_id("Tilix") == canonical  # match token
    assert store.resolve_id("nonexistent") is None


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
"""
    _write(tmp_path, "default.yaml", body)
    with pytest.raises(SystemExit):
        load_layouts(tmp_path)


def test_action_terminal_true_parses(tmp_path: Path) -> None:
    """``terminal: true`` opens the auto-detected emulator and loads fine."""
    body = """
match:
  - default
widgets:
  - id: term
    kind: button
    action:
      terminal: true
"""
    _write(tmp_path, "default.yaml", body)
    store = load_layouts(tmp_path)
    assert store.default().widgets[0].action.terminal is True


def test_action_terminal_string_rejected_with_guidance(tmp_path: Path) -> None:
    """A command string on ``terminal`` is a load error that points the user
    at ``terminal: true`` or a ``shell:`` action (issue: shell/terminal split)."""
    body = """
match:
  - default
widgets:
  - id: term
    kind: button
    action:
      terminal: "tilix"
"""
    _write(tmp_path, "default.yaml", body)
    with pytest.raises(SystemExit) as exc:
        load_layouts(tmp_path)
    msg = str(exc.value)
    assert "terminal: true" in msg
    assert 'shell: "tilix"' in msg


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
    default = store.default()
    assert default.widgets, "shipping default.yaml has no widgets"


# ---------------------------------------------------------------------------
# url: action primitive
# ---------------------------------------------------------------------------


def test_action_url_parses(tmp_path: Path) -> None:
    """A url: action loads without error."""
    body = """
match:
  - default
widgets:
  - id: url-btn
    kind: button
    action:
      url: "https://example.com"
"""
    _write(tmp_path, "default.yaml", body)
    store = load_layouts(tmp_path)
    assert store.default().widgets[0].action.url == "https://example.com"


def test_action_url_rejects_unknown_scheme(tmp_path: Path) -> None:
    """A non-http/https/file URL is a load-time error."""
    body = """
match:
  - default
widgets:
  - id: url-btn
    kind: button
    action:
      url: "ftp://example.com"
"""
    _write(tmp_path, "default.yaml", body)
    with pytest.raises(SystemExit):
        load_layouts(tmp_path)


def test_action_url_accepts_file_scheme(tmp_path: Path) -> None:
    """file:// URLs are accepted."""
    body = """
match:
  - default
widgets:
  - id: url-btn
    kind: button
    action:
      url: "file:///tmp/test.html"
"""
    _write(tmp_path, "default.yaml", body)
    store = load_layouts(tmp_path)
    assert store.default().widgets[0].action.url == "file:///tmp/test.html"


# ---------------------------------------------------------------------------
# text: action primitive
# ---------------------------------------------------------------------------


def test_action_text_simulate_mode_parses(tmp_path: Path) -> None:
    """A text: action with text_mode: simulate loads without error."""
    body = """
match:
  - default
widgets:
  - id: text-btn
    kind: button
    action:
      text: "hello"
      text_mode: simulate
"""
    _write(tmp_path, "default.yaml", body)
    store = load_layouts(tmp_path)
    a = store.default().widgets[0].action
    assert a.text == "hello"
    assert a.text_mode == "simulate"


def test_action_text_paste_mode_parses(tmp_path: Path) -> None:
    """A text: action with text_mode: paste loads without error."""
    body = """
match:
  - default
widgets:
  - id: text-btn
    kind: button
    action:
      text: "hello world"
      text_mode: paste
"""
    _write(tmp_path, "default.yaml", body)
    store = load_layouts(tmp_path)
    a = store.default().widgets[0].action
    assert a.text == "hello world"
    assert a.text_mode == "paste"
    assert a.restore_clipboard is True


def test_action_text_defaults_to_simulate(tmp_path: Path) -> None:
    """When text_mode is omitted, it defaults to None (treated as simulate)."""
    body = """
match:
  - default
widgets:
  - id: text-btn
    kind: button
    action:
      text: "hello"
"""
    _write(tmp_path, "default.yaml", body)
    store = load_layouts(tmp_path)
    a = store.default().widgets[0].action
    assert a.text == "hello"
    assert a.text_mode is None


def test_action_text_rejects_empty_string(tmp_path: Path) -> None:
    """An empty text value is a load-time error."""
    body = """
match:
  - default
widgets:
  - id: text-btn
    kind: button
    action:
      text: ""
"""
    _write(tmp_path, "default.yaml", body)
    with pytest.raises(SystemExit):
        load_layouts(tmp_path)
