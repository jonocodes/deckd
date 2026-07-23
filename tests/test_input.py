"""Tests for ``deckd.input`` helpers.

Focused on ``name_from_keycode`` -- the reverse lookup the macOS sink
uses to translate the wire's keycode list back to names for AppleScript.
A regression in this table (e.g. ``leftbrace`` winning over ``[``)
silently breaks ``super+[`` / ``super+]`` shortcuts, so we pin the
canonical form here.
"""
from __future__ import annotations

from deckd.input import name_from_keycode, text_to_combos


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


# ---------------------------------------------------------------------------
# text_to_combos (kbd mode, issue #23). Expected keycodes are from the
# kernel header (linux/input-event-codes.h), independent of _SINGLE_KEY_MAP.
# ---------------------------------------------------------------------------

KEY_LEFTSHIFT = 42


def test_text_to_combos_lowercase_and_digits_unshifted() -> None:
    assert text_to_combos("ab") == [[30], [48]]  # KEY_A, KEY_B
    assert text_to_combos("z") == [[44]]  # KEY_Z
    assert text_to_combos("10") == [[2], [11]]  # KEY_1, KEY_0
    assert text_to_combos("-") == [[12]]  # KEY_MINUS
    assert text_to_combos("/") == [[53]]  # KEY_SLASH


def test_text_to_combos_capitals_add_shift() -> None:
    assert text_to_combos("A") == [[KEY_LEFTSHIFT, 30]]
    assert text_to_combos("Z") == [[KEY_LEFTSHIFT, 44]]


def test_text_to_combos_shifted_symbols_us_layout() -> None:
    assert text_to_combos("!") == [[KEY_LEFTSHIFT, 2]]  # Shift+KEY_1
    assert text_to_combos("@") == [[KEY_LEFTSHIFT, 3]]  # Shift+KEY_2
    assert text_to_combos("_") == [[KEY_LEFTSHIFT, 12]]  # Shift+KEY_MINUS
    assert text_to_combos("?") == [[KEY_LEFTSHIFT, 53]]  # Shift+KEY_SLASH


def test_text_to_combos_space_and_full_printable_run() -> None:
    assert text_to_combos(" ") == [[57]]  # KEY_SPACE
    assert text_to_combos("a b") == [[30], [57], [48]]
    assert text_to_combos("Hi!") == [
        [KEY_LEFTSHIFT, 35],  # H
        [23],  # i
        [KEY_LEFTSHIFT, 2],  # !
    ]


def test_text_to_combos_drops_unknown_characters() -> None:
    assert text_to_combos("aéb") == [[30], [48]]
    assert text_to_combos("a🎉b") == [[30], [48]]
    assert text_to_combos("a\nb") == [[30], [48]]


def test_text_to_combos_empty_string() -> None:
    assert text_to_combos("") == []
