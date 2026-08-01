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