"""macOS backend: focus detection + key/pointer/scroll sinks.

No new native deps, no kernel extensions. Keys + focus shell out to
``osascript`` (AppleScript); scroll + pointer + click go through
PyObjC ``Quartz`` so we can do held-button drags the trackpad's
tap-and-a-half gesture needs. cliclick was an earlier choice for
pointer / click but couldn't model a held button across multiple
moves -- Quartz's ``LeftMouseDragged`` is.

Capability matrix (sketch):

  +-----------------------------+--------+------------------------------+
  | capability                  | works? | how                          |
  +-----------------------------+--------+------------------------------+
  | focus detection             | yes    | osascript + System Events    |
  | key injection (printable)   | yes    | osascript ``keystroke``      |
  | key injection (non-print)   | partial| osascript ``key code`` (map) |
  | combo modifiers             | yes    | ``using {command down}``     |
  | mouse click (left/right)    | yes    | PyObjC Quartz CG mouse event |
  | mouse relative motion       | yes    | PyObjC Quartz CG mouse event |
  | mouse drag (held-button)    | yes    | PyObjC Quartz LeftMouseDragged |
  | high-res wheel scroll       | yes    | PyObjC ``Quartz.CGEvent-     |
  |                             |        | CreateScrollWheelEvent``     |
  +-----------------------------+--------+------------------------------+

The Linux ``UinputSink`` covers the same wire protocol but emits Linux
evdev events.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from types import ModuleType

from .input import MODIFIER_MAP, KeySink, ScrollSink, name_from_keycode
from .platform import AppInfo, PlatformBackend, _run

log = logging.getLogger("deckd.platform_macos")


def _load_quartz() -> tuple[ModuleType | None, bool]:
    """Lazy import of ``pyobjc-framework-Quartz``. Returns ``(module, available)``.

    Both sinks (pointer / click and scroll) need the same module;
    centralising the try / except avoids the duplicated boilerplate and
    gives one place to log the install hint.
    """
    try:
        import Quartz  # type: ignore

        return Quartz, True
    except ImportError:
        return None, False

# ---------------------------------------------------------------------------
# Focus
# ---------------------------------------------------------------------------

# AppleScript returns three pipe-delimited fields. Pipe is rare enough in
# process names / window titles that this is fine as a sketch.
_FOCUS_SCRIPT = """
tell application "System Events"
  set frontProc to first process whose frontmost is true
  set procName to name of frontProc
  try
    set winTitle to name of front window of frontProc
  on error
    set winTitle to ""
  end try
  return procName & "|||" & winTitle
end tell
"""


class MacFocusBackend(PlatformBackend):
    """Read the frontmost app's process name + front window title via
    System Events. ``app_id`` is the process name; ``wm_class`` is left
    None (the Mac concept doesn't map 1:1).
    """

    async def get_active_app(self) -> AppInfo:
        out = await _run("osascript", "-e", _FOCUS_SCRIPT)
        proc_name, _, title = out.partition("|||")
        return AppInfo(
            app_id=proc_name.strip() or None,
            wm_class=None,
            title=title.strip() or None,
        )


# ---------------------------------------------------------------------------
# Key sink (osascript keystroke / key code)
# ---------------------------------------------------------------------------

# AppleScript modifier clauses. ``super``/``meta`` map to Command (the Mac
# "super" key); ``alt`` maps to Option; ``ctrl`` maps to Control.
_MOD_CLAUSE: dict[str, str] = {
    "ctrl": "control",
    "shift": "shift",
    "alt": "option",
    "super": "command",
    "meta": "command",
}

# AppleScript ``key code`` numbers (HID usage IDs) for the non-printable
# keys we care about. Letters and digits are sent as ``keystroke "x"``
# instead -- easier and locale-correct.
_MAC_KEY_CODE: dict[str, int] = {
    "esc": 53, "escape": 53,
    "tab": 48,
    "enter": 36, "return": 36,
    "space": 49,
    "backspace": 51,
    "delete": 117, "del": 117,
    "home": 115,
    "end": 119,
    "pageup": 116, "pgup": 116,
    "pagedown": 121, "pgdn": 121,
    "up": 126,
    "down": 125,
    "left": 123,
    "right": 124,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "capslock": 57,
}


def _build_keystroke_script(keycodes: Sequence[int]) -> str | None:
    """Translate an evdev keycode list into a single AppleScript line.

    Returns ``None`` when the translation can't be expressed (e.g. an
    unknown keycode); the caller should log and skip.
    """
    if not keycodes:
        return None

    mods: list[str] = []
    main_name: str | None = None
    for kc in keycodes:
        name = name_from_keycode(kc)
        if name is None:
            log.warning("[mac key] unknown evdev keycode %s", kc)
            return None
        if name in MODIFIER_MAP:
            clause = _MOD_CLAUSE.get(name)
            if clause is None:
                return None
            mods.append(clause)
        else:
            # ``parse_key_combo`` always puts the main key last, so the last
            # non-modifier keycode wins.
            main_name = name

    if main_name is None:
        log.warning("[mac key] no main key in combo %s", keycodes)
        return None

    mod_clause = ""
    if mods:
        mod_clause = " using {" + ", ".join(f"{m} down" for m in mods) + "}"

    # Printable single-char -> ``keystroke "x"``; everything else -> ``key code N``.
    if len(main_name) == 1 and main_name.isprintable() and main_name not in _MAC_KEY_CODE:
        return f'tell application "System Events" to keystroke "{main_name}"{mod_clause}'

    mac_code = _MAC_KEY_CODE.get(main_name)
    if mac_code is None:
        log.warning("[mac key] no macOS mapping for key %r", main_name)
        return None
    return f'tell application "System Events" to key code {mac_code}{mod_clause}'


class MacKeySink(KeySink):
    """Emit keys via osascript. Pointer + click + drag via PyObjC Quartz.

    Quartz is needed (over the simpler cliclick path) because the
    trackpad's tap-and-a-half gesture requires a held-button drag --
    cliclick only knows ``click`` (down+up in one shot) and ``move``,
    so it can't model the "press, move with button held, then release"
    sequence the wire protocol demands. Quartz's CGEvent lets us split
    those into ``LeftMouseDown`` / ``LeftMouseDragged`` / ``LeftMouseUp``.
    """

    def __init__(self) -> None:
        self._Q, self._has_quartz = _load_quartz()
        if not self._has_quartz:
            log.warning(
                "[mac key] PyObjC Quartz not available; "
                "trackpad pointer / clicks will log only "
                "(install with: pip install pyobjc-framework-Quartz)"
            )
        # Track the held-button state so emit_pointer emits
        # ``LeftMouseDragged`` (not ``MouseMoved``) while the user is
        # mid-drag. The server drives this via pad_drag start/end.
        self._dragging_left = False

    # -- key -----------------------------------------------------------------

    def emit_key(self, keycodes: list[int]) -> None:
        script = _build_keystroke_script(keycodes)
        if script is None:
            return
        # Fire and forget: osascript is too slow to block the event loop on
        # the first call (TCC prompt can take seconds). The key reaches the
        # focused app a few ms later; the wire protocol doesn't await.
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.debug("[mac key] %s", script)

    # -- pointer / click (Quartz) -------------------------------------------

    def emit_pointer(self, dx: int, dy: int) -> None:
        if not self._has_quartz:
            log.info("[mac pointer log] dx=%s dy=%s (no Quartz)", dx, dy)
            return
        if dx == 0 and dy == 0:
            return
        Q = self._Q
        # ``LeftMouseDragged`` keeps the left button logically held in the
        # event stream; ``MouseMoved`` is plain cursor motion with no
        # button. Picking the right one is what makes the tap-and-a-half
        # drag-lock feel native (selections / windows actually drag).
        event_type = Q.kCGEventLeftMouseDragged if self._dragging_left else Q.kCGEventMouseMoved
        # Compute the new absolute cursor position rather than setting the
        # delta fields. ``CGEventCreateMouseEvent`` with a (0, 0) cursor
        # position is read by Quartz as "warp the cursor to (0, 0)"; the
        # deltaX / deltaY fields are then ignored (or applied in addition
        # to the warp), so the cursor snaps to a screen corner on every
        # event instead of moving relative to where it was. Posting at
        # ``current + delta`` is the reliable path.
        #
        # Quartz mouse-event coordinates use top-left origin with Y down,
        # same as CSS / iOS / Windows -- so dy from the wire (screen-down)
        # maps directly to positive Y on the cursor.
        current = _cursor_pos(Q)
        new_pos = Q.CGPoint(current.x + dx, current.y + dy)
        event = Q.CGEventCreateMouseEvent(
            None, event_type, new_pos, Q.kCGMouseButtonLeft
        )
        Q.CGEventPost(Q.kCGHIDEventTap, event)
        log.debug("[mac pointer] dx=%s dy=%s -> (%.1f, %.1f)", dx, dy, new_pos.x, new_pos.y)

    def emit_click(self, button: str, pressed: bool) -> None:
        if not self._has_quartz:
            log.info("[mac click log] button=%s pressed=%s (no Quartz)", button, pressed)
            return
        Q = self._Q
        if button == "left":
            down_type, up_type = Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp
            button_code = Q.kCGMouseButtonLeft
        elif button == "right":
            down_type, up_type = Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp
            button_code = Q.kCGMouseButtonRight
        else:
            log.warning("[mac click] unknown button %r", button)
            return
        event_type = down_type if pressed else up_type
        # Use the current cursor position, not (0, 0). Same trap as
        # emit_pointer: a (0, 0) position warps the cursor to the top-left
        # before the down / up registers, so taps feel like the cursor
        # snapped away. The user's last emit_pointer already placed the
        # cursor where they want the click; reuse that.
        current = _cursor_pos(Q)
        event = Q.CGEventCreateMouseEvent(None, event_type, current, button_code)
        Q.CGEventPost(Q.kCGHIDEventTap, event)
        if button == "left":
            self._dragging_left = pressed
        log.debug("[mac click] button=%s pressed=%s", button, pressed)

    def close(self) -> None:
        pass


def _cursor_pos(Q: ModuleType):
    """Read the current cursor position. Wraps the CGEventCreate + CGEventGetLocation
    pair so emit_pointer / emit_click don't repeat the dance."""
    return Q.CGEventGetLocation(Q.CGEventCreate(None))


# ---------------------------------------------------------------------------
# Scroll sink
# ---------------------------------------------------------------------------


class MacScrollSink(ScrollSink):
    """Synthetic-wheel sink via PyObjC + Quartz.

    macOS doesn't expose wheel injection through AppleScript. Quartz's
    ``CGEventCreateScrollWheelEvent`` is the only path that reaches the
    focused window's scroll view the same way a real trackpad or mouse
    wheel does. Requires ``pyobjc-framework-Quartz``; the sink falls
    back to log-only if it's not importable.

    The wire protocol emits ``REL_WHEEL_HI_RES`` deltas (1/120 of a
    wheel detent). We accumulate them and emit one ``kCGScrollEventUnitLine``
    event per detent, matching the Linux ``UinputSink`` behaviour.
    """

    # 1 detent (line) == 120 REL_WHEEL_HI_RES units, the same ratio Linux uses.
    DETENT = 120

    def __init__(self) -> None:
        self._Quartz, self._available = _load_quartz()
        if self._available:
            log.info("[mac scroll] Quartz loaded; wheel events will be injected")
        else:
            log.warning(
                "[mac scroll] PyObjC Quartz not available; "
                "jogstrip will log only "
                "(install with: pip install pyobjc-framework-Quartz)"
            )
        self._wheel_remainder = 0

    def emit_scroll(self, delta: int) -> None:
        if delta == 0:
            return
        if not self._available:
            log.info("[mac scroll log] delta=%s (no Quartz)", delta)
            return
        self._wheel_remainder += delta
        detents = self._wheel_remainder // self.DETENT
        if detents == 0:
            return
        self._wheel_remainder -= int(detents) * self.DETENT
        Q = self._Quartz
        event = Q.CGEventCreateScrollWheelEvent(
            None,
            Q.kCGScrollEventUnitLine,
            1,  # one wheel axis (vertical)
            int(detents),
        )
        Q.CGEventPost(Q.kCGHIDEventTap, event)
        log.debug("[mac scroll] line events=%s (delta=%s)", int(detents), delta)

    def close(self) -> None:
        pass
