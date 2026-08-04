"""Tests for the ``confirm`` field on widgets (issues #69 / #108).

The field opts a widget into a daemon-authoritative confirmation handshake:
``confirm: true`` requires the widget to carry an ``action`` or a ``macro``
(blank/meter/stats/media/mediabrowser reject it). The wire shape is
plain-boolean; default ``false``; the daemon emits ``confirm: false`` on
every widget so the client can decide at render time whether to show a
danger affordance.
"""
from __future__ import annotations

import pytest

from deckd.layouts import Widget


def test_confirm_defaults_to_false_on_button() -> None:
    """A button widget with no ``confirm`` key defaults to ``false``."""
    w = Widget.model_validate({"id": "b", "kind": "button", "action": {"key": "a"}})
    assert w.confirm is False


def test_confirm_true_accepts_button_with_action() -> None:
    w = Widget.model_validate(
        {"id": "b", "kind": "button", "confirm": True, "action": {"key": "a"}}
    )
    assert w.confirm is True


def test_confirm_true_accepts_button_with_macro() -> None:
    """A macro widget is also confirmable; one confirm gates the whole sequence."""
    w = Widget.model_validate(
        {
            "id": "b",
            "kind": "button",
            "confirm": True,
            "macro": {"steps": [{"type": "key", "value": "a"}]},
        }
    )
    assert w.confirm is True


def test_confirm_true_rejected_on_widget_without_action_or_macro() -> None:
    """A bare button widget has nothing to confirm."""
    with pytest.raises(ValueError, match="confirm"):
        Widget.model_validate({"id": "b", "kind": "button", "confirm": True})


def test_confirm_true_rejected_on_meter() -> None:
    with pytest.raises(ValueError, match="confirm"):
        Widget.model_validate(
            {"id": "m", "kind": "meter", "source": "cpu_percent", "confirm": True}
        )


def test_confirm_true_rejected_on_stats() -> None:
    with pytest.raises(ValueError, match="confirm"):
        Widget.model_validate(
            {
                "id": "s",
                "kind": "stats",
                "metrics": [{"source": "cpu_percent"}],
                "confirm": True,
            }
        )


def test_confirm_true_rejected_on_media() -> None:
    """Media sub-actions are ungated; confirm on a media widget is rejected."""
    with pytest.raises(ValueError, match="confirm"):
        Widget.model_validate(
            {
                "id": "media",
                "kind": "media",
                "action": {"key": "space"},
                "confirm": True,
            }
        )


def test_confirm_true_rejected_on_mediabrowser() -> None:
    with pytest.raises(ValueError, match="confirm"):
        Widget.model_validate(
            {"id": "mb", "kind": "mediabrowser", "confirm": True}
        )


def test_confirm_false_harmless_on_blank() -> None:
    """A ``blank`` with an absent ``confirm`` (default ``false``) is fine."""
    w = Widget.model_validate({"id": "gap", "kind": "blank"})
    assert w.confirm is False


def test_confirm_false_explicit_harmless_on_meter() -> None:
    """``confirm: false`` on a meter is the default — no rejection."""
    w = Widget.model_validate(
        {"id": "m", "kind": "meter", "source": "cpu_percent", "confirm": False}
    )
    assert w.confirm is False


def test_confirm_serializes_always() -> None:
    """Plain ``model_dump`` always includes ``confirm`` — no exclude_defaults."""
    w = Widget.model_validate({"id": "b", "kind": "button", "action": {"key": "a"}})
    dumped = w.model_dump()
    assert dumped["confirm"] is False

    w2 = Widget.model_validate(
        {"id": "b", "kind": "button", "confirm": True, "action": {"key": "a"}}
    )
    dumped2 = w2.model_dump()
    assert dumped2["confirm"] is True
