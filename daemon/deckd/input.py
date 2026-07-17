from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Protocol

log = logging.getLogger("deckd.input")


class ScrollSink(Protocol):
    def emit_scroll(self, delta: int) -> None:
        """Emit one high-resolution vertical wheel delta."""

    def close(self) -> None:
        """Release any OS resources held by the sink."""


class KeySink(Protocol):
    """Sink for synthetic input events emitted via uinput.

    T2 introduced this for keystrokes; T8 widened it to cover the trackpad's
    pointer motion and mouse buttons. In production a single ``UinputSink``
    device backs all three methods; tests use a recording fake.
    """

    def emit_key(self, keycodes: list[int]) -> None:
        """Press and release the given evdev keycodes as a combo."""

    def emit_pointer(self, dx: int, dy: int) -> None:
        """Emit a relative pointer-motion event (REL_X / REL_Y)."""

    def emit_click(self, button: str, pressed: bool) -> None:
        """Press (``pressed=True``) or release a mouse button.

        ``button`` is one of ``"left"``, ``"right"``, ``"middle"``.
        """

    def close(self) -> None:
        """Release any OS resources held by the sink."""


# ---------------------------------------------------------------------------
# Key name → Linux input event code (evdev keycodes)
# ---------------------------------------------------------------------------

MODIFIER_MAP: dict[str, int] = {
    "ctrl":  29,  # KEY_LEFTCTRL
    "shift": 42,  # KEY_LEFTSHIFT
    "alt":    56,  # KEY_LEFTALT
    "super": 125,  # KEY_LEFTMETA
    "meta":  125,  # KEY_LEFTMETA  (alias)
}

_SINGLE_KEY_MAP: dict[str, int] = {
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34, "h": 35,
    "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49, "o": 24, "p": 25,
    "q": 16, "r": 19, "s": 31, "t": 20, "u": 22, "v": 47, "w": 17, "x": 45,
    "y": 21, "z": 44,
    "0": 11, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8,
    "8": 9, "9": 10,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64,
    "f7": 65, "f8": 66, "f9": 67, "f10": 68, "f11": 87, "f12": 88,
    "esc": 1, "escape": 1,
    "tab": 15,
    "enter": 28, "return": 28,
    "space": 57,
    "backspace": 14,
    "delete": 111, "del": 111,
    "insert": 110, "ins": 110,
    "home": 102,
    "end": 107,
    "pageup": 104, "pgup": 104,
    "pagedown": 109, "pgdn": 109,
    "up": 103,
    "down": 108,
    "left": 105,
    "right": 106,
    "minus": 12, "-": 12,
    "equal": 13, "=": 13,
    "leftbrace": 26, "[": 26,
    "rightbrace": 27, "]": 27,
    "semicolon": 39, ";": 39,
    "apostrophe": 40, "'": 40,
    "grave": 41, "`": 41,
    "backslash": 43, "\\": 43,
    "comma": 51, ",": 51,
    "dot": 52, ".": 52,
    "slash": 53, "/": 53,
    "capslock": 58,
    "print": 99, "sysrq": 99,
    "scrolllock": 70,
    "pause": 119,
}

ALL_REGISTERED_KEYCODES: list[int] = list(
    set(list(MODIFIER_MAP.values()) + list(_SINGLE_KEY_MAP.values()))
)


def parse_key_combo(key_string: str) -> list[int]:
    """Parse a key-combo string like ``"ctrl+t"`` into evdev keycodes.

    Modifiers come first; the final token is the main key.  All tokens are
    case-insensitive.  Unknown tokens are logged and dropped.
    """
    tokens = [t.strip().lower() for t in key_string.split("+")]
    if not tokens:
        return []

    *modifiers, main = tokens
    keycodes: list[int] = []

    for mod in modifiers:
        code = MODIFIER_MAP.get(mod)
        if code is not None:
            keycodes.append(code)
        else:
            log.warning("[key parse] unknown modifier %r in %r", mod, key_string)

    code = MODIFIER_MAP.get(main) or _SINGLE_KEY_MAP.get(main)
    if code is not None:
        keycodes.append(code)
    else:
        log.warning("[key parse] unknown key %r in %r", main, key_string)

    return keycodes


def name_from_keycode(keycode: int) -> str | None:
    """Reverse of :data:`MODIFIER_MAP` + :data:`_SINGLE_KEY_MAP`.

    Returns the canonical (lowercase) name for an evdev keycode, or ``None``
    if the code isn't in either table. Used by backends (e.g. macOS) that
    receive a keycode list and need to translate to their own event names.

    When a code has multiple names (e.g. ``[`` and ``leftbrace`` both map to
    26), the single-character form is preferred — macOS's ``keystroke``
    translates printable literals directly, so ``"["`` round-trips through
    AppleScript without needing an HID-code lookup.
    """
    candidates = _NAMES_BY_KEYCODE.get(keycode)
    if not candidates:
        return None
    for name in candidates:
        if len(name) == 1:
            return name
    return candidates[0]


_NAMES_BY_KEYCODE: dict[int, list[str]] = {}
for _k, _v in MODIFIER_MAP.items():
    _NAMES_BY_KEYCODE.setdefault(_v, []).append(_k)
for _k, _v in _SINGLE_KEY_MAP.items():
    _NAMES_BY_KEYCODE.setdefault(_v, []).append(_k)


# ---------------------------------------------------------------------------
# Fallback / logging sinks
# ---------------------------------------------------------------------------


class LoggingScrollSink:
    """Fallback sink used when python-evdev or /dev/uinput is unavailable."""

    def emit_scroll(self, delta: int) -> None:
        log.info("[scroll log] REL_WHEEL_HI_RES=%s", delta)

    def close(self) -> None:
        pass


class LoggingKeySink:
    """Fallback sink that logs key + pointer events when uinput is unavailable."""

    def emit_key(self, keycodes: list[int]) -> None:
        log.info("[key log] keycodes=%s", keycodes)

    def emit_pointer(self, dx: int, dy: int) -> None:
        log.info("[pointer log] dx=%s dy=%s", dx, dy)

    def emit_click(self, button: str, pressed: bool) -> None:
        log.info("[click log] button=%s pressed=%s", button, pressed)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Combined uinput sink (single device for scroll + key)
# ---------------------------------------------------------------------------


class UinputSink:
    """Single write-only uinput device supporting EV_REL (scroll) and
    EV_KEY (keyboard) events."""

    def __init__(self) -> None:
        try:
            from evdev import UInput, ecodes
        except ImportError as exc:
            raise RuntimeError(
                "evdev is not installed; install deckd with the uinput extra"
            ) from exc

        class WriteOnlyUInput(UInput):
            def _find_device(self, fd: int):
                return None

        self._ecodes = ecodes
        self._mouse_buttons: dict[str, int] = {
            "left": ecodes.BTN_LEFT,
            "right": ecodes.BTN_RIGHT,
            "middle": ecodes.BTN_MIDDLE,
        }
        capabilities: dict[int, Sequence[int]] = {
            ecodes.EV_REL: [
                ecodes.REL_WHEEL,
                ecodes.REL_WHEEL_HI_RES,
                ecodes.REL_X,
                ecodes.REL_Y,
            ],
            ecodes.EV_KEY: (
                ALL_REGISTERED_KEYCODES + list(self._mouse_buttons.values())
            ),
        }
        self._device = WriteOnlyUInput(capabilities, name="deckd")
        self._wheel_remainder = 0
        log.info("created write-only uinput device at %s", self._device.devnode)

    # -- scroll ---------------------------------------------------------------

    def emit_scroll(self, delta: int) -> None:
        if delta == 0:
            return
        self._device.write(self._ecodes.EV_REL, self._ecodes.REL_WHEEL_HI_RES, delta)

        self._wheel_remainder += delta
        detents = int(self._wheel_remainder / 120)
        if detents:
            self._wheel_remainder -= detents * 120
            self._device.write(self._ecodes.EV_REL, self._ecodes.REL_WHEEL, detents)
        self._device.syn()
        log.debug("[scroll] REL_WHEEL_HI_RES=%s", delta)

    # -- key ------------------------------------------------------------------

    def emit_key(self, keycodes: list[int]) -> None:
        if not keycodes:
            return
        for kc in keycodes:
            self._device.write(self._ecodes.EV_KEY, kc, 1)
        self._device.syn()
        for kc in reversed(keycodes):
            self._device.write(self._ecodes.EV_KEY, kc, 0)
        self._device.syn()
        log.debug("[key] keycodes=%s", keycodes)

    # -- pointer / click ------------------------------------------------------

    def emit_pointer(self, dx: int, dy: int) -> None:
        if dx == 0 and dy == 0:
            return
        if dx:
            self._device.write(self._ecodes.EV_REL, self._ecodes.REL_X, dx)
        if dy:
            self._device.write(self._ecodes.EV_REL, self._ecodes.REL_Y, dy)
        self._device.syn()
        log.debug("[pointer] dx=%s dy=%s", dx, dy)

    def emit_click(self, button: str, pressed: bool) -> None:
        code = self._mouse_buttons.get(button)
        if code is None:
            log.warning("[click] unknown button %r", button)
            return
        self._device.write(self._ecodes.EV_KEY, code, 1 if pressed else 0)
        self._device.syn()
        log.debug("[click] button=%s pressed=%s", button, pressed)

    # -- close ----------------------------------------------------------------

    def close(self) -> None:
        self._device.close()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_scroll_sink() -> ScrollSink:
    try:
        return UinputSink()
    except Exception as exc:
        log.warning("uinput scroll unavailable; falling back to logging only: %s", exc)
        return LoggingScrollSink()


def make_key_sink() -> KeySink:
    try:
        return UinputSink()
    except Exception as exc:
        log.warning("uinput key unavailable; falling back to logging only: %s", exc)
        return LoggingKeySink()


# ---------------------------------------------------------------------------
# ScrollController
# ---------------------------------------------------------------------------


class ScrollController:
    def __init__(
        self,
        sink: ScrollSink | None = None,
        *,
        momentum_friction: float = 0.90,
        momentum_cutoff: int = 20,
    ) -> None:
        self._sink = sink if sink is not None else make_scroll_sink()
        self._momentum_tasks: dict[str, asyncio.Task[None]] = {}
        self._momentum_friction = momentum_friction
        self._momentum_cutoff = momentum_cutoff
        self._closed = False

    def jog(self, widget_id: str, delta: int) -> None:
        if self._closed:
            return
        self._cancel_momentum(widget_id)
        self._sink.emit_scroll(delta)

    def jog_end(self, widget_id: str, velocity: int) -> None:
        if self._closed:
            return
        self._cancel_momentum(widget_id)
        if abs(velocity) < self._momentum_cutoff:
            return
        self._momentum_tasks[widget_id] = asyncio.create_task(
            self._run_momentum(widget_id, velocity)
        )

    async def _run_momentum(self, widget_id: str, velocity: int) -> None:
        frame_s = 1 / 60
        remainder = 0.0
        try:
            while abs(velocity) >= self._momentum_cutoff:
                await asyncio.sleep(frame_s)
                delta = velocity * frame_s + remainder
                whole = int(delta)
                remainder = delta - whole
                if whole:
                    self._sink.emit_scroll(whole)
                velocity = int(velocity * self._momentum_friction)
        finally:
            self._momentum_tasks.pop(widget_id, None)

    def _cancel_momentum(self, widget_id: str) -> None:
        task = self._momentum_tasks.pop(widget_id, None)
        if task is not None:
            task.cancel()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = list(self._momentum_tasks.values())
        self._momentum_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._sink.close()
