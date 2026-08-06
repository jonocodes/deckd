"""Tests for ``deckd.platform_macos._build_keystroke_script``.

This is the pure-Python translation that turns an evdev keycode list
(modifiers + main key) into a one-line AppleScript. The actual
``osascript`` call is fire-and-forget so we can't integration-test it
cleanly; the string output is what we assert on.

Runs on any platform -- the function doesn't import Quartz / osascript.
"""
from __future__ import annotations

import pytest

from deckd.input import parse_key_combo
from deckd.platform import WindowInfo
from deckd.platform_macos import (
    MacFocusBackend,
    _build_keystroke_script,
    _is_standard_cg_window,
    _window_info_from_cg_payload,
)


# ---------------------------------------------------------------------------
# Printables: keystroke "<char>"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "combo,expected",
    [
        ("t", 'tell application "System Events" to keystroke "t"'),
        ("a", 'tell application "System Events" to keystroke "a"'),
        ("0", 'tell application "System Events" to keystroke "0"'),
        ("=", 'tell application "System Events" to keystroke "="'),
        ("-", 'tell application "System Events" to keystroke "-"'),
        ("[", 'tell application "System Events" to key code 33'),
        ("]", 'tell application "System Events" to key code 30'),
    ],
)
def test_printable_char_emits_keystroke_literal(combo: str, expected: str) -> None:
    """Single-character printables go out as ``keystroke "<char>"`` --
    locale-correct, no HID-code lookup needed. This is the path that
    fixed the ``super+[`` shortcut regression."""
    assert _build_keystroke_script(parse_key_combo(combo)) == expected


# ---------------------------------------------------------------------------
# Combos: using {<modifier> down}
# ---------------------------------------------------------------------------


def test_super_modifier_maps_to_command() -> None:
    """``super`` is the Mac "Command" key -- the modifier clause uses
    ``command down``."""
    script = _build_keystroke_script(parse_key_combo("super+t"))
    assert script == (
        'tell application "System Events" to keystroke "t" '
        "using {command down}"
    )


def test_ctrl_maps_to_control() -> None:
    script = _build_keystroke_script(parse_key_combo("ctrl+a"))
    assert 'using {control down}' in script
    assert 'keystroke "a"' in script


def test_alt_maps_to_option() -> None:
    script = _build_keystroke_script(parse_key_combo("alt+Tab"))
    assert 'using {option down}' in script
    assert "key code 48" in script  # Tab's HID code


def test_meta_and_super_both_become_command() -> None:
    """``meta`` is an alias for ``super`` on Linux; both should yield
    ``command down`` on macOS."""
    a = _build_keystroke_script(parse_key_combo("super+a"))
    b = _build_keystroke_script(parse_key_combo("meta+a"))
    assert a == b


def test_multiple_modifiers_combine_in_order() -> None:
    """Modifiers are emitted in the order they appear in the input --
    the wire protocol always puts them first so the test combo matches
    the canonical order, but the clause should still emit all of them."""
    script = _build_keystroke_script(parse_key_combo("ctrl+shift+Right"))
    assert script == (
        'tell application "System Events" to key code 124 '
        "using {control down, shift down}"
    )


def test_super_plus_bracket_uses_key_code() -> None:
    """``super+[`` now uses ``key code 33`` instead of ``keystroke "["``
    for layout-independent key injection. The keystroke path broke on
    non-US keyboard layouts where ``[`` requires Option."""
    script = _build_keystroke_script(parse_key_combo("super+["))
    assert script == (
        'tell application "System Events" to key code 33 '
        "using {command down}"
    )


# ---------------------------------------------------------------------------
# Non-printables: key code <HID>
# ---------------------------------------------------------------------------


def test_function_key_uses_hid_code() -> None:
    """F1 -> key code 122 (HID usage ID); no modifiers."""
    assert _build_keystroke_script(parse_key_combo("F1")) == (
        'tell application "System Events" to key code 122'
    )


def test_arrow_uses_hid_code() -> None:
    assert _build_keystroke_script(parse_key_combo("Up")) == (
        'tell application "System Events" to key code 126'
    )


def test_return_uses_hid_code() -> None:
    assert _build_keystroke_script(parse_key_combo("Return")) == (
        'tell application "System Events" to key code 36'
    )


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_empty_keycodes_returns_none() -> None:
    """An empty list (e.g. parsed combo with no known keys) yields
    None -- the sink logs and skips rather than emitting ``key code``
    with nothing."""
    assert _build_keystroke_script([]) is None


def test_unknown_keycode_returns_none() -> None:
    """A keycode not in either forward table is untranslatable; the
    sink logs and skips rather than crashing."""
    assert _build_keystroke_script([29, 999]) is None


def test_unknown_main_key_returns_none() -> None:
    """If the main key isn't printable AND isn't in the HID map, we
    bail out -- we don't want to emit garbage key codes."""
    # ``foo`` is not in MODIFIER_MAP or _SINGLE_KEY_MAP.
    assert _build_keystroke_script([20, 9999]) is None


def test_only_modifiers_returns_none() -> None:
    """A combo that ends up modifier-only (e.g. a parse that lost the
    main key) returns None -- the sink shouldn't emit ``keystroke``
    with no character."""
    # Pass a keycode that's only in MODIFIER_MAP, twice.
    assert _build_keystroke_script([29, 29]) is None


# ---------------------------------------------------------------------------
# Window enumeration
# ---------------------------------------------------------------------------


def test_cg_window_payload_maps_to_window_info() -> None:
    """CGWindowList's standard-window fields map to the shared wire shape."""
    assert _window_info_from_cg_payload(
        {
            "kCGWindowNumber": 42,
            "kCGWindowOwnerPID": 4242,
            "kCGWindowOwnerName": "Firefox",
            "kCGWindowName": "YouTube",
            "kCGWindowLayer": 0,
        }
    ) == WindowInfo(
        window_id="42",
        wm_class="Firefox",
        gtk_application_id=None,
        sandboxed_app_id=None,
        title="YouTube",
        workspace=None,
        minimized=False,
        app_name="Firefox",
    )


def test_mac_focus_backend_advertises_window_surfaces() -> None:
    assert MacFocusBackend().capabilities() == frozenset(
        {"watch_active_app", "watch_windows", "raise_window"}
    )


# ---------------------------------------------------------------------------
# CGWindowList standard-window filter
# ---------------------------------------------------------------------------


def _cg_window(number, pid, layer=0, owner="App", title="w"):
    return {
        "kCGWindowNumber": number,
        "kCGWindowOwnerPID": pid,
        "kCGWindowOwnerName": owner,
        "kCGWindowName": title,
        "kCGWindowLayer": layer,
    }


def test_is_standard_cg_window_accepts_normal_window() -> None:
    """A layer-0 window owned by a real PID is a user window the
    switcher should list."""
    assert _is_standard_cg_window(_cg_window(42, 4242))


@pytest.mark.parametrize(
    "payload,reason",
    [
        # Desktop / menu-bar / dock overlays live on non-zero layers;
        # filtering them keeps the switcher list to user windows.
        (_cg_window(7, 4242, layer=2147483631), "non-zero layer"),
        # Window numbers must be int (a malformed payload shouldn't crash);
        # CGWindowList always yields ints so a non-int is a corrupt entry.
        ({"kCGWindowLayer": 0, "kCGWindowNumber": "x", "kCGWindowOwnerPID": 4242}, "non-int number"),
        # PID 0 is the kernel (LaunchDM / loginwindow internals); not a
        # user-raisable app, so the gate refuses it.
        ({"kCGWindowLayer": 0, "kCGWindowNumber": 9, "kCGWindowOwnerPID": 0}, "pid 0"),
        # A missing PID entirely is a corrupt entry, not a window to list.
        ({"kCGWindowLayer": 0, "kCGWindowNumber": 9, "kCGWindowOwnerPID": None}, "missing pid"),
    ],
)
def test_is_standard_cg_window_rejects_noise(payload, reason) -> None:
    assert not _is_standard_cg_window(payload)


def test_cg_window_options_helper_combines_flags() -> None:
    """The option flags gate the list to on-screen, non-desktop windows
    — pinning the combination keeps a future edit from accidentally
    dropping one half of the filter."""
    class _FakeQuartz:
        kCGWindowListOptionOnScreenOnly = 1
        kCGWindowListExcludeDesktopElements = 4

    from deckd.platform_macos import _cg_window_list_options

    assert _cg_window_list_options(_FakeQuartz) == 5
