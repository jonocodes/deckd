"""macOS backend: focus detection + key/pointer/scroll sinks.

Cheap shim over AppleScript (``osascript``) and, when present, ``cliclick``.
No new native deps, no kernel extensions. TCC will prompt the first time
osascript asks System Events to do something on the daemon's behalf.

Capability matrix (sketch):

  +-----------------------------+--------+------------------------------+
  | capability                  | works? | how                          |
  +-----------------------------+--------+------------------------------+
  | focus detection             | yes    | osascript + System Events    |
  | key injection (printable)   | yes    | osascript ``keystroke``      |
  | key injection (non-print)   | partial| osascript ``key code`` (map) |
  | combo modifiers             | yes    | ``using {command down}``     |
  | mouse click (left/right)    | yes    | cliclick ``c:``/``rc:``      |
  | mouse relative motion       | yes    | cliclick ``dx:``/``dy:``     |
  | high-res wheel scroll       | yes    | PyObjC ``Quartz.CGEvent-     |
  |                             |        | CreateScrollWheelEvent``     |
  +-----------------------------+--------+------------------------------+

The Linux ``UinputSink`` covers the same wire protocol but emits Linux evdev
events. This module emits nothing locally -- it shells out to ``osascript``
and ``cliclick`` so the events reach real apps.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from collections.abc import Sequence

from .input import MODIFIER_MAP, KeySink, ScrollSink, name_from_keycode
from .platform import AppInfo, PlatformBackend, _run

log = logging.getLogger("deckd.platform_macos")

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
    """Emit keys via osascript. Pointer + clicks delegate to ``cliclick``
    when it's on PATH, log a warning otherwise.
    """

    def __init__(self) -> None:
        self._cliclick = shutil.which("cliclick")
        if self._cliclick is None:
            log.warning(
                "[mac key] cliclick not found on PATH; "
                "trackpad pointer + clicks will log only "
                "(install with: brew install cliclick)"
            )
        self._warned_no_cliclick = False

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

    # -- pointer / click (cliclick) -----------------------------------------

    def emit_pointer(self, dx: int, dy: int) -> None:
        if self._cliclick is None:
            if not self._warned_no_cliclick:
                log.warning("[mac pointer] skipping dx=%s dy=%s (no cliclick)", dx, dy)
                self._warned_no_cliclick = True
            return
        subprocess.Popen(
            [self._cliclick, f"dx:{dx}", f"dy:{dy}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.debug("[mac pointer] dx=%s dy=%s", dx, dy)

    def emit_click(self, button: str, pressed: bool) -> None:
        # Only emit on press -- the matching release would just re-click.
        if not pressed:
            return
        if self._cliclick is None:
            if not self._warned_no_cliclick:
                log.warning("[mac click] skipping button=%s (no cliclick)", button)
                self._warned_no_cliclick = True
            return
        verb = "rc:." if button == "right" else "c:."
        subprocess.Popen(
            [self._cliclick, verb],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.debug("[mac click] button=%s", button)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Scroll sink
# ---------------------------------------------------------------------------


class MacScrollSink(ScrollSink):
    """Synthetic-wheel sink via PyObjC + Quartz.

    macOS doesn't expose wheel injection through AppleScript or any
    open-source tool I trust to keep working (cliclick, Hammerspoon
    aside). Quartz's ``CGEventCreateScrollWheelEvent`` is the only path
    that reaches the focused window's scroll view the same way a real
    trackpad or mouse wheel does. Requires ``pyobjc-framework-Quartz``;
    the sink falls back to log-only if it's not importable.

    The wire protocol emits ``REL_WHEEL_HI_RES`` deltas (1/120 of a
    wheel detent). We accumulate them and emit one ``kCGScrollEventUnitLine``
    event per detent, matching the Linux ``UinputSink`` behaviour.
    """

    # 1 detent (line) == 120 REL_WHEEL_HI_RES units, the same ratio Linux uses.
    DETENT = 120

    def __init__(self) -> None:
        try:
            import Quartz  # type: ignore

            self._Quartz = Quartz
            self._available = True
            log.info("[mac scroll] Quartz loaded; wheel events will be injected")
        except ImportError:
            self._Quartz = None
            self._available = False
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


# ---------------------------------------------------------------------------
# Re-export so __main__.py can ask ``platform_macos.is_macos()`` cleanly.
# ---------------------------------------------------------------------------


def is_macos() -> bool:
    return sys.platform == "darwin"
