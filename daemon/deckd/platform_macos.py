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

import asyncio
import logging
import os
import subprocess
from collections.abc import AsyncIterator, Sequence
from types import ModuleType
from typing import Any

from .input import MODIFIER_MAP, KeySink, ScrollSink, name_from_keycode
from .platform import AppInfo, PlatformBackend, RaiseWindowFailed, WindowInfo, _run

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


def _terminal_name() -> str:
    """Return the name of the terminal app this process runs under.

    Used for permission-setup instructions so the user knows exactly
    which app to add in System Settings (e.g. iTerm.app, Code, cmux,
    Terminal).
    """
    env = os.environ.get("TERM_PROGRAM", "")
    if env == "iTerm.app":
        return "iTerm.app"
    if env in ("Apple_Terminal", "Terminal"):
        return "Terminal.app"
    if any(k.startswith("VSCODE_") for k in os.environ):
        return "Code (VS Code)"
    try:
        ppid = os.getppid()
        name = subprocess.check_output(
            ["ps", "-o", "comm=", "-p", str(ppid)],
            text=True,
        ).strip()
        if name:
            return name
    except Exception:
        pass
    return env or "your terminal"


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

    def capabilities(self) -> frozenset[str]:
        return frozenset({"watch_active_app", "watch_windows", "raise_window"})

    async def watch_windows(
        self, *, interval_s: float = 0.1
    ) -> AsyncIterator[Sequence[WindowInfo]]:
        """Poll on-screen standard windows in front-to-back order.

        CGWindowList's order is front-to-back, which is the closest native
        macOS equivalent to the MRU ordering used by the Linux backends.
        Window numbers are stable for a window's lifetime and become the
        opaque ``window_id`` sent to the client.
        """
        last: Sequence[WindowInfo] | None = None
        while True:
            try:
                snapshot = await self._list_windows_once()
            except Exception as exc:
                log.debug("macOS watch_windows: %s", exc)
                snapshot = []
            if snapshot != last:
                last = snapshot
                yield snapshot
            await asyncio.sleep(interval_s)

    async def _list_windows_once(self) -> list[WindowInfo]:
        quartz = self._quartz()
        options = _cg_window_list_options(quartz)
        payloads = quartz.CGWindowListCopyWindowInfo(
            options, quartz.kCGNullWindowID
        ) or []
        return [
            _window_info_from_cg_payload(payload)
            for payload in payloads
            if _is_standard_cg_window(payload)
        ]

    async def raise_window(self, window_id: str) -> None:
        """Activate the owning app and raise the matching AX window."""
        try:
            quartz = self._quartz()
            target = int(window_id)
            options = _cg_window_list_options(quartz)
            payloads = quartz.CGWindowListCopyWindowInfo(
                options, quartz.kCGNullWindowID
            ) or []
            payload = next(
                (
                    item
                    for item in payloads
                    if _is_standard_cg_window(item)
                    and item.get("kCGWindowNumber") == target
                ),
                None,
            )
            if payload is None:
                raise RaiseWindowFailed(window_id)

            pid = payload.get("kCGWindowOwnerPID")
            if not isinstance(pid, int):
                raise RaiseWindowFailed(window_id)

            appkit, accessibility = _load_raise_apis()
            app = appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_(
                pid
            )
            if app is None or not app.activateWithOptions_(
                appkit.NSApplicationActivateIgnoringOtherApps
            ):
                raise RaiseWindowFailed(window_id)

            ax_app = accessibility.AXUIElementCreateApplication(pid)
            error, windows = accessibility.AXUIElementCopyAttributeValue(
                ax_app, accessibility.kAXWindowsAttribute, None
            )
            if error != accessibility.kAXErrorSuccess or windows is None:
                raise RaiseWindowFailed(window_id)
            for window in windows:
                error, number = accessibility.AXUIElementCopyAttributeValue(
                    window, accessibility.kAXWindowNumberAttribute, None
                )
                if error == accessibility.kAXErrorSuccess and number == target:
                    if accessibility.AXUIElementPerformAction(
                        window, accessibility.kAXRaiseAction
                    ) == accessibility.kAXErrorSuccess:
                        return
                    break
            raise RaiseWindowFailed(window_id)
        except Exception as exc:
            log.debug("macOS raise_window(%s): %s", window_id, exc)
            if isinstance(exc, RaiseWindowFailed):
                raise
            raise RaiseWindowFailed(window_id) from exc

    @staticmethod
    def _quartz() -> Any:
        quartz, available = _load_quartz()
        if not available or quartz is None:
            raise RuntimeError("PyObjC Quartz is required for macOS window enumeration")
        return quartz


def _load_raise_apis() -> tuple[ModuleType, ModuleType]:
    """Load AppKit and Accessibility lazily so Linux can import this module."""
    import AppKit  # type: ignore[import-not-found]
    import ApplicationServices  # type: ignore[import-not-found]

    return AppKit, ApplicationServices


def _is_standard_cg_window(payload: dict[str, Any]) -> bool:
    return (
        payload.get("kCGWindowLayer") == 0
        and isinstance(payload.get("kCGWindowNumber"), int)
        and isinstance(payload.get("kCGWindowOwnerPID"), int)
        and payload["kCGWindowOwnerPID"] > 0
    )


def _cg_window_list_options(quartz: Any) -> int:
    return (
        quartz.kCGWindowListOptionOnScreenOnly
        | quartz.kCGWindowListExcludeDesktopElements
    )


def _window_info_from_cg_payload(payload: dict[str, Any]) -> WindowInfo:
    """Map a CGWindowList dictionary to deckd's platform-neutral shape."""
    owner = payload.get("kCGWindowOwnerName")
    title = payload.get("kCGWindowName")
    return WindowInfo(
        window_id=str(payload["kCGWindowNumber"]),
        wm_class=owner if isinstance(owner, str) else None,
        app_name=owner if isinstance(owner, str) else None,
        gtk_application_id=None,
        sandboxed_app_id=None,
        title=title if isinstance(title, str) and title else None,
        workspace=None,
        minimized=False,
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

# AppleScript ``key code`` numbers (HID usage IDs) for keys that need
# layout-independent key codes. Letters and digits are sent as
# ``keystroke "x"`` -- easier and locale-correct. But bracket keys
# (``[`` / ``]``) vary by keyboard layout when sent as characters, so
# they go through ``key code`` instead so they always hit the same
# physical key.
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
    "[": 33,
    "]": 30,
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
        else:
            log.info(
                "[mac key] macOS 15+ may require Input Monitoring permission "
                "for %s (System Settings > Privacy & Security > Input Monitoring)",
                _terminal_name(),
            )
        # Track the held-button state so emit_pointer emits
        # ``LeftMouseDragged`` (not ``MouseMoved``) while the user is
        # mid-drag. The server drives this via pad_drag start/end.
        self._dragging_left = False
        self._check_accessibility()

    # -- key -----------------------------------------------------------------

    @staticmethod
    def _check_accessibility() -> None:
        """Check that osascript can send keystrokes via System Events.

        macOS 14+ may silently deny keystroke injection even when the
        terminal is listed in Accessibility preferences (a re-add often
        fixes it). This probe warns the user at startup with actionable
        instructions instead of failing silently on the first button
        press.
        """
        try:
            proc = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to keystroke ""'],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode != 0:
                term = _terminal_name()
                reason = proc.stderr.strip() or f"exit code {proc.returncode}"
                log.warning(
                    "[mac key] osascript keystroke probe failed: %s\n"
                    "  Grant Accessibility to %s in System Settings > Privacy & Security.\n"
                    "  If already listed, remove it, re-add it, then restart the terminal.",
                    reason,
                    term,
                )
        except FileNotFoundError:
            log.warning("[mac key] osascript not found; key injection unavailable")
        except subprocess.TimeoutExpired:
            log.warning("[mac key] osascript keystroke probe timed out")

    def emit_key(self, keycodes: list[int]) -> None:
        script = _build_keystroke_script(keycodes)
        if script is None:
            return
        proc = subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        _, err = proc.communicate()
        if err:
            log.warning("[mac key] osascript stderr: %s", err.strip())
        else:
            log.debug("[mac key] %s", script)

    # -- pointer / click (Quartz) -------------------------------------------

    def emit_pointer(self, dx: int, dy: int) -> None:
        if not self._has_quartz:
            log.info("[mac pointer log] dx=%s dy=%s (no Quartz)", dx, dy)
            return
        if dx == 0 and dy == 0:
            return
        Q = self._Q
        if Q is None:
            return
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
        if Q is None:
            return
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
            log.info(
                "[mac scroll] macOS 15+ may require Input Monitoring permission "
                "for %s (System Settings > Privacy & Security > Input Monitoring)",
                _terminal_name(),
            )
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
        if Q is None:
            return
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
