"""Tests for ``deckd.input`` helpers.

Focused on ``name_from_keycode`` -- the reverse lookup the macOS sink
uses to translate the wire's keycode list back to names for AppleScript.
A regression in this table (e.g. ``leftbrace`` winning over ``[``)
silently breaks ``super+[`` / ``super+]`` shortcuts, so we pin the
canonical form here.
"""
from __future__ import annotations

from deckd.input import name_from_keycode


# ---------------------------------------------------------------------------
# Single-char aliases win over the longer evdev names
# ---------------------------------------------------------------------------


def test_name_from_keycode_prefers_single_char_alias() -> None:
    """``[`` and ``]`` / ``-`` / ``=`` map to the same code as their
    long evdev names; the single-char form must win so the macOS sink
    can emit ``keystroke "["`` instead of failing the HID-code lookup.
    """
    assert name_from_keycode(26) == "["
    assert name_from_keycode(27) == "]"
    assert name_from_keycode(12) == "-"
    assert name_from_keycode(13) == "="


def test_name_from_keycode_returns_long_name_when_no_single_char() -> None:
    """For keys without a single-char alias (arrows, function keys, etc.),
    the long evdev name is what callers get."""
    assert name_from_keycode(103) == "up"
    assert name_from_keycode(108) == "down"
    assert name_from_keycode(105) == "left"
    assert name_from_keycode(106) == "right"
    assert name_from_keycode(59) == "f1"
    assert name_from_keycode(88) == "f12"


def test_name_from_keycode_handles_modifiers() -> None:
    """Modifiers are also reverse-lookupable -- the macOS sink translates
    them to AppleScript ``command down`` / ``control down`` / etc."""
    assert name_from_keycode(29) == "ctrl"
    assert name_from_keycode(42) == "shift"
    assert name_from_keycode(56) == "alt"
    assert name_from_keycode(125) in {"super", "meta"}


def test_name_from_keycode_returns_none_for_unknown() -> None:
    """Codes outside the table return None -- the sink treats that as
    "skip this key" rather than crashing."""
    assert name_from_keycode(999) is None
    assert name_from_keycode(-1) is None


def test_name_from_keycode_handles_letters_and_digits() -> None:
    """The common-printable cases are single chars already; this is just
    a sanity check that they round-trip."""
    assert name_from_keycode(20) == "t"
    assert name_from_keycode(30) == "a"
    assert name_from_keycode(11) == "0"
    assert name_from_keycode(2) == "1"
