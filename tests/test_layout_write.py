"""Tests for the layout write API primitives (issues #99 / #84 / #85).

Covers the three unit seams behind the ``PUT /layouts/{id}`` (save) and
``POST /layouts`` (create) endpoints:

* ``slugify_layout_id`` — derives a filesystem-safe filename stem from a
  layout's primary ``match`` token (S1).
* the layout-level duplicate widget-id validator on :class:`Layout` (S2).
* ``reconcile_and_write_layout`` — comment-preserving reconcile of a
  client snapshot onto a fresh on-disk YAML, atomic temp-write +
  ``os.replace`` (S3).

The HTTP endpoints themselves are integration-tested in
``tests/test_layout_write_api.py`` (S4).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from deckd.layouts import Layout, reconcile_and_write_layout, slugify_layout_id


# ---------------------------------------------------------------------------
# S1 — slugify_layout_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("match_token", "expected"),
    [
        ("Slack", "slack"),
        ("firefox", "firefox"),
        ("com.gexperts.Tilix", "com.gexperts.tilix"),
        ("Tilix", "tilix"),
        # A ``title:`` web-app glob: ``:`` and ``*`` are not filesystem-safe.
        ("title:*YouTube*", "title-youtube"),
        # Mixed-case with separators collapses runs of separator chars.
        ("My Cool App", "my-cool-app"),
    ],
)
def test_slugify_layout_id(match_token: str, expected: str) -> None:
    assert slugify_layout_id(match_token) == expected


def test_slugify_layout_id_rejects_blank_result() -> None:
    """A match token that slugifies to the empty string can't name a file."""
    with pytest.raises(ValueError):
        slugify_layout_id("***")


# ---------------------------------------------------------------------------
# S2 — layout-level duplicate widget-id validator
# ---------------------------------------------------------------------------


def _widget(wid: str, kind: str = "button") -> dict:
    return {"id": wid, "kind": kind}


def test_layout_accepts_unique_widget_ids() -> None:
    layout = Layout.model_validate(
        {
            "match": ["firefox"],
            "widgets": [_widget("back"), _widget("forward")],
        }
    )
    assert [w.id for w in layout.widgets] == ["back", "forward"]


def test_layout_rejects_duplicate_widget_ids() -> None:
    """#85 layout-level duplicate-id validator: two same ids is a schema error."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc_info:
        Layout.model_validate(
            {
                "match": ["firefox"],
                "widgets": [_widget("back"), _widget("back")],
            }
        )
    messages = " ".join(e["msg"] for e in exc_info.value.errors())
    assert "duplicate widget id" in messages
    assert "'back'" in messages


 # ---------------------------------------------------------------------------
 # S3 — reconcile_and_write_layout (comment-preserving, atomic, canonical)
 # ---------------------------------------------------------------------------


import os

from ruamel.yaml import YAML

from deckd.layouts import load_layout


def _layout_dict(match: list[str], widgets: list[dict], **extra: object) -> dict:
    out: dict = {"match": match, "widgets": widgets}
    out.update(extra)
    return out


def _button(wid: str, label: str | None = None, action_shell: str | None = None) -> dict:
    w: dict = {"id": wid, "kind": "button"}
    if label is not None:
        w["label"] = label
    if action_shell is not None:
        w["action"] = {"shell": action_shell}
    return w


def _read_yaml(path: Path) -> dict:
    y = YAML()
    return y.load(path.read_text()) or {}


def _canonical(path: Path) -> dict:
    """The post-save canonical shape a 200 response echoes."""
    return load_layout(path).model_dump()


def test_write_creates_new_file_from_scratch(tmp_path: Path) -> None:
    path = tmp_path / "slack.yaml"
    snap = _layout_dict(["Slack"], [_button("snooze", "Snooze", action_shell="echo hi")])

    reconcile_and_write_layout(path, snap)

    assert path.exists()
    on_disk = _read_yaml(path)
    # No stored `id` — the canonical id comes from match[0] on re-read.
    assert "id" not in on_disk
    assert on_disk["match"] == ["Slack"]
    assert on_disk["widgets"][0]["id"] == "snooze"
    assert on_disk["widgets"][0]["label"] == "Snooze"
    assert _canonical(path)["id"] == "Slack"


def test_write_preserves_comments_on_unchanged_structure(tmp_path: Path) -> None:
    path = tmp_path / "firefox.yaml"
    path.write_text(
        "# top comment explaining the layout\n"
        "match:\n"
        "  - firefox\n"
        "widgets:\n"
        "  # a button for going back\n"
        "  - id: back\n"
        "    kind: button\n"
        "    label: Back\n"
        "    action:\n"
        "      shell: echo back\n"
    )
    snap = _layout_dict(["firefox"], [_button("back", "Back", action_shell="echo back")])

    reconcile_and_write_layout(path, snap)

    text = path.read_text()
    assert "# top comment explaining the layout" in text
    assert "# a button for going back" in text


def test_write_edits_scalar_field_preserving_widget_comments(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text(
        "match:\n  - app\nwidgets:\n  - id: go\n    kind: button\n"
        "    # the label comment must survive a label edit\n"
        "    label: Old\n    action:\n      shell: old-cmd\n"
    )
    snap = _layout_dict(["app"], [_button("go", "New", action_shell="new-cmd")])

    reconcile_and_write_layout(path, snap)

    text = path.read_text()
    assert "# the label comment must survive a label edit" in text
    on_disk = _read_yaml(path)
    assert on_disk["widgets"][0]["label"] == "New"
    assert on_disk["widgets"][0]["action"]["shell"] == "new-cmd"


def test_write_reorders_widgets_by_id(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text(
        "match:\n  - app\n"
        "widgets:\n  - id: a\n    kind: button\n  - id: b\n    kind: button\n"
    )
    snap = _layout_dict(["app"], [_button("b"), _button("a")])

    reconcile_and_write_layout(path, snap)

    ids = [w["id"] for w in _read_yaml(path)["widgets"]]
    assert ids == ["b", "a"]


def test_write_adds_and_deletes_widgets_by_id(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text(
        "match:\n  - app\n"
        "widgets:\n"
        "  - id: keep\n    kind: button\n"
        "  - id: drop\n    kind: button\n"
    )
    snap = _layout_dict(
        ["app"],
        [_button("keep"), _button("added", "Added", action_shell="echo added")],
    )

    reconcile_and_write_layout(path, snap)

    ids = [w["id"] for w in _read_yaml(path)["widgets"]]
    assert ids == ["keep", "added"]
    assert _canonical(path)["widgets"][1]["action"]["shell"] == "echo added"


def test_write_replaces_match_sequence_atomically(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text(
        "match:\n  - app\n  - alias\nwidgets:\n  - id: w\n    kind: button\n"
    )
    snap = _layout_dict(["only-app"], [_button("w")])

    reconcile_and_write_layout(path, snap)

    on_disk = _read_yaml(path)
    assert on_disk["match"] == ["only-app"]
    assert _canonical(path)["id"] == "only-app"


def test_write_reconciles_nested_icon_map(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text(
        "match:\n  - app\n"
        "widgets: []\n"
        "icon:\n  source: lucide\n  name: old-name\n"
    )
    snap = _layout_dict("match" and ["app"], [], icon={"source": "lucide", "name": "new-name"})

    reconcile_and_write_layout(path, snap)

    on_disk = _read_yaml(path)
    assert on_disk["icon"]["source"] == "lucide"
    assert on_disk["icon"]["name"] == "new-name"


@pytest.mark.parametrize(
    "color",
    [
        # Hex — the shape the editor's `<input type="color">` swatch emits.
        # Leading `#` is a YAML comment character, so this only survives if
        # the writer quotes it.
        "#1e3a8a",
        # The escape hatches the swatch can't represent but the schema
        # accepts: a CSS named colour and a functional notation (#115).
        "rebeccapurple",
        "hsl(220, 70%, 40%)",
    ],
)
def test_write_round_trips_widget_color_unchanged(tmp_path: Path, color: str) -> None:
    """#115 AC4: a colour chosen in the editor saves byte-identical.

    The picker is free to normalise what it *shows*; what the client sends
    is authoritative and must reach disk — and come back out of a re-read —
    with no rewriting.
    """
    path = tmp_path / "app.yaml"
    path.write_text("match:\n  - app\nwidgets:\n  - id: go\n    kind: button\n")
    widget = _button("go", "Go")
    widget["color"] = color
    snap = _layout_dict(["app"], [widget])

    reconcile_and_write_layout(path, snap)

    assert _read_yaml(path)["widgets"][0]["color"] == color
    # And through a full parse, which is what the 200 response echoes back.
    assert _canonical(path)["widgets"][0]["color"] == color


def test_write_clearing_widget_color_drops_the_key(tmp_path: Path) -> None:
    """#115 AC3: clearing the field sends no `color`, so disk loses it.

    The panel deletes the key rather than sending null, so an unset widget
    stays unset in the YAML instead of gaining an explicit `color: null`.
    """
    path = tmp_path / "app.yaml"
    path.write_text(
        "match:\n  - app\n"
        'widgets:\n  - id: go\n    kind: button\n    color: "#1e3a8a"\n'
    )
    snap = _layout_dict(["app"], [_button("go")])

    reconcile_and_write_layout(path, snap)

    assert "color" not in _read_yaml(path)["widgets"][0]
    assert _canonical(path)["widgets"][0]["color"] is None


def test_write_is_atomic_no_tempfile_leak_on_success(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text("match:\n  - app\nwidgets: []\n")
    snap = _layout_dict(["app"], [])

    reconcile_and_write_layout(path, snap)

    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp") or ".yaml.tmp" in p.name]
    assert leftovers == []
    assert path.exists()


def test_write_removes_top_level_key_dropped_from_snapshot(tmp_path: Path) -> None:
    # The editor sends a full snapshot; a key it omits is removed from disk
    # (full-snapshot authoritativeness, carrying comments only for kept keys).
    path = tmp_path / "app.yaml"
    path.write_text(
        "match:\n  - app\n"
        "widgets: []\n"
        "display_name: Old Name\n"
        "theme: '#1e3a8a'\n"
    )
    # Snapshot drops display_name and theme entirely.
    snap = {"match": ["app"], "widgets": []}

    reconcile_and_write_layout(path, snap)

    on_disk = _read_yaml(path)
    assert "display_name" not in on_disk
    assert "theme" not in on_disk


def test_write_renders_indented_sequences_matching_repo_style(tmp_path: Path) -> None:
    """A fresh file emits block sequences indented two spaces under their key,
    matching every shipping layout (``match:\n  - firefox``), not ruamel's
    default flush-left ``match:\n- firefox``. Valid YAML either way, but the
    repo's hand-authored style is the convention the editor writes into."""
    path = tmp_path / "slack.yaml"
    snap = _layout_dict(["Slack"], [_button("snooze", "Snooze")])
    reconcile_and_write_layout(path, snap)
    text = path.read_text()
    assert "match:\n  - Slack\n" in text
    assert "  - id: snooze\n" in text


def test_write_preserves_comments_and_key_order_on_unchanged_widget(
    tmp_path: Path,
) -> None:
    """A shipping-style widget (comment before a key, keys in declaration
    order) keeps its comment and order when a *different* widget is edited.

    Regression for the reconcile reassigning every scalar key: reassigning
    an unchanged value drops ruamel's attached comment and reorders the key
    to the snapshot's order, mangling hand-authored layouts on save. The
    fix skips reassignment when the value is unchanged so the original node
    (comment + position) rides along untouched.
    """
    path = tmp_path / "firefox.yaml"
    path.write_text(
        "match:\n  - firefox\n"
        "widgets:\n"
        "  - id: back\n"
        "    kind: button\n"
        "    # label: Back\n"
        "    label: Back\n"
        "    action:\n"
        "      key: alt+Left\n"
        "  - id: forward\n"
        "    kind: button\n"
        "    # label: Forward\n"
        "    label: Forward\n"
        "    action:\n"
        "      key: alt+Right\n"
    )
    # Edit only the `back` widget; `forward` is byte-identical to the source.
    snap = _layout_dict(
        ["firefox"],
        [
            {"id": "back", "kind": "button", "label": "Backward", "action": {"key": "alt+Left"}},
            {"id": "forward", "kind": "button", "label": "Forward", "action": {"key": "alt+Right"}},
        ],
    )
    reconcile_and_write_layout(path, snap)

    text = path.read_text()
    # The unchanged widget's comment survives at its original position...
    assert "    # label: Forward\n    label: Forward\n" in text
    # ...and its key order is preserved (label before action, not reordered).
    forward_block = text.split("  - id: forward", 1)[1]
    assert forward_block.index("label: Forward") < forward_block.index("action:")
    # The edited widget carries the new value and still parses.
    assert "label: Backward" in text
    assert _canonical(path)["id"] == "firefox"