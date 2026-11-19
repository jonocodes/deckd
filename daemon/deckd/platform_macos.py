"""macOS backend: focus detection + window enumeration/raise + key/pointer/scroll sinks.

No new native deps, no kernel extensions. Keys + focus shell out to
``osascript`` (AppleScript); scroll + pointer + click go through
PyObjC ``Quartz`` so we can do held-button drags the trackpad's
tap-and-a-half gesture needs. cliclick was an earlier choice for
pointer / click but couldn't model a held button across multiple
moves -- Quartz's ``LeftMouseDragged`` is.

Window enumeration + raise (switcher parity, #135) happen in-process
too: ``Quartz.CGWindowListCopyWindowInfo`` yields on-screen windows
(front-to-back = MRU proxy) and AppKit ``NSRunningApplication`` +
``ApplicationServices`` Accessibility raise the chosen one. Window
numbers are stable for a window's lifetime and serve as the opaque
``window_id`` sent to the client. Accessibility consent is gated by
``MacKeySink._check_accessibility`` at keysink startup.

Capability matrix (sketch):

  +-----------------------------+--------+------------------------------+
  | capability                  | works? | how                          |
  +-----------------------------+--------+------------------------------+
  | focus detection             | yes    | osascript + System Events    |
  | window enumeration          | yes    | Quartz ``CGWindowList``      |
  | raise window                | yes    | AppKit + Accessibility (AX)  |
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
import ctypes
import functools
import logging
import os
import re
import subprocess
import sys
import threading
from collections.abc import AsyncIterator, Callable, Sequence
from types import ModuleType
from typing import Any

from .macos_app import BUNDLE_ID
from .input import MODIFIER_MAP, KeySink, PermissionDenied, ScrollSink, name_from_keycode
from .platform import AppInfo, PlatformBackend, RaiseWindowFailed, WindowInfo, _run
from .protocol import HealthIssue

log = logging.getLogger("deckd.platform_macos")

# Health-issue ids for the two System Events grants (#195, #196).
ACCESSIBILITY_MISSING = "accessibility_missing"
AUTOMATION_MISSING = "automation_system_events_missing"


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
    # Inside a .app bundle (the DMG install) the parent is launchd, and
    # the TCC grant belongs to the bundle itself, so name that instead.
    bundle, sep, _ = sys.executable.partition(".app/Contents/MacOS/")
    if sep:
        return os.path.basename(bundle) + ".app"
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


def _responsible_app_name() -> str:
    """The app macOS charges this process's permissions to.

    TCC grants follow the *responsible* process: inside the packaged app
    that is ``deckd.app`` itself (its parent is launchd, which is no help
    to a user hunting through Settings); from a checkout it is whatever
    terminal / editor launched the daemon.
    """
    if getattr(sys, "frozen", False):
        return "deckd.app"
    return _terminal_name()


def _log_input_monitoring_hint(prefix: str) -> None:
    log.info(
        "%s macOS 15+ may require Input Monitoring permission for %s "
        "(System Settings > Privacy & Security > Input Monitoring)",
        prefix,
        _responsible_app_name(),
    )


def _accessibility_missing_issue(app: str, bundle_id: str | None) -> HealthIssue:
    """The ``accessibility_missing`` health issue, naming ``app`` (#195).

    The re-add step is for a stale grant: an ad-hoc build gets a new code
    identity on every rebuild, and the first certificate-signed build
    changes it once (#194), so Settings can show deckd switched on while the
    grant no longer applies. macOS 26's Settings gives no reliable way to
    remove that entry, so when the bundle id is known (the packaged app)
    the step gives the ``tccutil`` command that clears it. From a checkout
    the grant is the terminal's, whose bundle id we don't know.
    """
    if bundle_id is not None:
        stale = (
            f"Turn on {app}. If it is already listed and on, run "
            f"`tccutil reset Accessibility {bundle_id}` in Terminal, then add "
            f"{app} again with +."
        )
    else:
        stale = (
            f"Turn on {app}. If it is already listed and on, switch it off "
            "and on again, or remove it and add it back with +."
        )
    return HealthIssue(
        id=ACCESSIBILITY_MISSING,
        severity="error",
        title="Accessibility permission missing",
        detail=(
            f"macOS isn't letting {app} control the mouse and keyboard. "
            "Buttons that open apps still work."
        ),
        fix_steps=[
            "On the Mac, open System Settings → Privacy & Security → Accessibility.",
            stale,
            "This warning clears by itself a few seconds after the grant. If "
            f"buttons still do nothing after that, quit and reopen {app}.",
        ],
        affects=["pointer", "scroll", "key", "raise_window"],
    )


def _automation_missing_issue(app: str, bundle_id: str | None) -> HealthIssue:
    """The ``automation_system_events_missing`` health issue (#196).

    Automation entries can't be added with + in Settings: macOS lists an
    app only after it has asked once. So when the entry is missing (or on
    but stale, the same story as Accessibility), the way back is to reset
    the decision and let deckd's next System Events call ask again. The
    focus poller makes that call within a second, so the prompt appears
    on its own.
    """
    if bundle_id is not None:
        missing = (
            f"If {app} isn't listed, or System Events is already on, run "
            f"`tccutil reset AppleEvents {bundle_id}` in Terminal, then click "
            "OK when macOS asks to let it control System Events."
        )
    else:
        missing = (
            f"If {app} isn't listed, quit and reopen it, then click OK when "
            "macOS asks to let it control System Events."
        )
    return HealthIssue(
        id=AUTOMATION_MISSING,
        severity="error",
        title="Automation permission missing",
        detail=(
            f"macOS isn't letting {app} control System Events, so key "
            "buttons do nothing and the deck may not follow the app in front."
        ),
        fix_steps=[
            "On the Mac, open System Settings → Privacy & Security → Automation.",
            f"Under {app}, turn on System Events.",
            missing,
            "This warning clears by itself a few seconds after the grant.",
        ],
        affects=["key", "focus"],
    )


# ---------------------------------------------------------------------------
# Permission failures seen at action time (#196)
# ---------------------------------------------------------------------------

# AppleScript error numbers that mean "a TCC grant is missing", keyed to
# the health issue that explains the fix. -1743 is errAEEventNotPermitted
# (Automation of System Events denied); 1002 is System Events refusing
# ``keystroke`` / ``key code`` because osascript's responsible app lacks
# Accessibility.
_PERMISSION_ERRORS: dict[int, str] = {
    -1743: AUTOMATION_MISSING,
    1002: ACCESSIBILITY_MISSING,
}

# osascript prints ``<range>: execution error: <text> (<number>)``. The
# message text is localised, so classify by the trailing number only.
_OSA_ERROR_NUMBER = re.compile(r"execution error: .*\((-?\d+)\)\s*$")


def classify_osascript_error(stderr: str) -> str | None:
    """Map osascript stderr to a health-issue id, or ``None`` if unrelated."""
    for line in stderr.splitlines():
        match = _OSA_ERROR_NUMBER.search(line)
        if match is not None:
            return _PERMISSION_ERRORS.get(int(match.group(1)))
    return None


class PermissionLedger:
    """What osascript calls have shown about the two System Events grants.

    The proactive checks (``AXIsProcessTrusted``, ``AEDeterminePermission-
    ToAutomateTarget``) can be unavailable or disagree with what osascript
    actually gets, so every System Events call reports its result here
    too. A denial is held until a later call proves the grant: a focus
    query that succeeds proves Automation; a keystroke that succeeds
    proves both. Shared by the key sink (which records) and the focus
    backend (which records and reports), and read from the health
    poller's worker thread, hence the lock.
    """

    def __init__(self) -> None:
        self._denied: set[str] = set()
        self._lock = threading.Lock()

    def observe(self, returncode: int, stderr: str, *, keystroke: bool) -> str | None:
        """Record one System Events call. Returns the denied issue id, if any."""
        issue = classify_osascript_error(stderr) if returncode != 0 else None
        with self._lock:
            if issue is not None:
                self._denied.add(issue)
                if issue == ACCESSIBILITY_MISSING:
                    # System Events answered, so the Apple event got through.
                    self._denied.discard(AUTOMATION_MISSING)
                return issue
            if returncode == 0:
                self._denied.discard(AUTOMATION_MISSING)
                if keystroke:
                    self._denied.discard(ACCESSIBILITY_MISSING)
        return None

    def denied(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._denied)


# The process-wide ledger: the key sink and focus backend are built
# separately (``__main__`` / ``default_backend``) but must share it.
PERMISSIONS = PermissionLedger()

_KEYSTROKE_PROBE = 'tell application "System Events" to keystroke ""'


def _probe_keystroke() -> tuple[int, str]:
    """Send an empty keystroke through System Events: ``(returncode, stderr)``.

    Exercises both grants without typing anything. Only run while a denial
    is held (see :meth:`MacFocusBackend.health_issues`), so a healthy host
    never pays for it.
    """
    try:
        proc = subprocess.run(
            ["osascript", "-e", _KEYSTROKE_PROBE],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, str(exc)
    return proc.returncode, proc.stderr


def _blocked_message(issue_id: str) -> str:
    """The toast for a key press the OS refused (#196)."""
    app = _responsible_app_name()
    if issue_id == AUTOMATION_MISSING:
        return (
            f"Key press blocked: {app} needs Automation permission to "
            "control System Events."
        )
    return f"Key press blocked: {app} needs Accessibility permission."


# ---------------------------------------------------------------------------
# Proactive Automation check (#196)
# ---------------------------------------------------------------------------

_SYSTEM_EVENTS_BUNDLE_ID = "com.apple.systemevents"
_AE_NO_ERR = 0
_AE_EVENT_NOT_PERMITTED = -1743  # errAEEventNotPermitted


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


class _AEDesc(ctypes.Structure):
    _fields_ = [("descriptorType", ctypes.c_uint32), ("dataHandle", ctypes.c_void_p)]


@functools.cache
def _core_services() -> ctypes.CDLL:
    lib = ctypes.CDLL("/System/Library/Frameworks/CoreServices.framework/CoreServices")
    lib.AECreateDesc.argtypes = [
        ctypes.c_uint32, ctypes.c_void_p, ctypes.c_long, ctypes.POINTER(_AEDesc)
    ]
    lib.AECreateDesc.restype = ctypes.c_int16
    lib.AEDeterminePermissionToAutomateTarget.argtypes = [
        ctypes.POINTER(_AEDesc), ctypes.c_uint32, ctypes.c_uint32, ctypes.c_bool
    ]
    lib.AEDeterminePermissionToAutomateTarget.restype = ctypes.c_int32
    lib.AEDisposeDesc.argtypes = [ctypes.POINTER(_AEDesc)]
    lib.AEDisposeDesc.restype = ctypes.c_int16
    return lib


def _automation_status(status: int) -> bool | None:
    """Map ``AEDeterminePermissionToAutomateTarget``'s OSStatus to a verdict.

    Only ``noErr`` and ``errAEEventNotPermitted`` are answers. Not asked
    yet (-1744) isn't a denial: the first System Events call will prompt.
    System Events not running (-600) and anything else mean "can't tell".
    """
    if status == _AE_NO_ERR:
        return True
    if status == _AE_EVENT_NOT_PERMITTED:
        return False
    return None


def _automation_permission() -> bool | None:
    """May this process send Apple events to System Events?

    Asks TCC without showing the consent prompt (``askUserIfNeeded`` is
    false). Plain ctypes against CoreServices: PyObjC doesn't wrap the
    ``AEAddressDesc`` the call needs. ``None`` off macOS or on any error.
    The call can block briefly, so the health poller runs it off the
    event loop.
    """
    if sys.platform != "darwin":
        return None
    try:
        lib = _core_services()
        target = _SYSTEM_EVENTS_BUNDLE_ID.encode("ascii")
        desc = _AEDesc()
        if lib.AECreateDesc(_fourcc("bund"), target, len(target), ctypes.byref(desc)) != 0:
            return None
        try:
            status = lib.AEDeterminePermissionToAutomateTarget(
                ctypes.byref(desc), _fourcc("****"), _fourcc("****"), False
            )
        finally:
            lib.AEDisposeDesc(ctypes.byref(desc))
    except Exception as exc:  # a broken probe means "unknown", never a crash
        log.debug("Automation probe failed: %s", exc)
        return None
    return _automation_status(status)


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

    def __init__(
        self,
        *,
        ledger: PermissionLedger | None = None,
        keystroke_probe: Callable[[], tuple[int, str]] | None = None,
    ) -> None:
        self._ledger = ledger if ledger is not None else PERMISSIONS
        self._keystroke_probe = keystroke_probe or _probe_keystroke

    async def get_active_app(self) -> AppInfo:
        try:
            out = await _run("osascript", "-e", _FOCUS_SCRIPT)
        except RuntimeError as exc:
            # A -1743 here is the focus half of a missing Automation grant
            # (#196): the deck stops following the front app.
            self._ledger.observe(1, str(exc), keystroke=False)
            raise
        self._ledger.observe(0, "", keystroke=False)
        proc_name, _, title = out.partition("|||")
        return AppInfo(
            app_id=proc_name.strip() or None,
            wm_class=None,
            title=title.strip() or None,
        )

    # Resolved once: ``_terminal_name`` shells out to ``ps`` and the
    # health poller asks every few seconds.
    _app_name: str | None = None

    def capabilities(self) -> frozenset[str]:
        return frozenset({"watch_active_app", "watch_windows", "raise_window"})

    def health_issues(self) -> list[HealthIssue]:
        """Report missing Accessibility (#195) and Automation (#196) grants.

        Each grant is missing when its proactive check says so
        (``AXIsProcessTrusted`` / ``AEDeterminePermissionToAutomateTarget``,
        re-read on every call so a grant made while the daemon runs clears
        the issue on the next poll) *or* when an osascript call was refused
        for it. A refusal held in the ledger is re-checked with an empty
        keystroke each poll, so it clears on its own too. ``None`` from a
        proactive check (no way to tell) reports nothing by itself.
        """
        if self._ledger.denied():
            returncode, stderr = self._keystroke_probe()
            self._ledger.observe(returncode, stderr, keystroke=True)
        held = self._ledger.denied()
        accessibility = ACCESSIBILITY_MISSING in held or _ax_trusted() is False
        automation = AUTOMATION_MISSING in held or _automation_permission() is False
        if not (accessibility or automation):
            return []
        if self._app_name is None:
            self._app_name = _responsible_app_name()
        bundle_id = BUNDLE_ID if getattr(sys, "frozen", False) else None
        issues: list[HealthIssue] = []
        if accessibility:
            issues.append(_accessibility_missing_issue(self._app_name, bundle_id))
        if automation:
            issues.append(_automation_missing_issue(self._app_name, bundle_id))
        return issues

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


def _ax_trusted() -> bool | None:
    """Is this process tree trusted for Accessibility?

    ``None`` when the API isn't importable (non-macOS, or PyObjC not
    installed) — "unknown", not "untrusted".
    """
    try:
        import ApplicationServices  # type: ignore[import-not-found]
    except ImportError:
        return None
    # PyObjC's stubs don't declare the AX namespace, but the symbol is
    # there at runtime (same story as the kAX* constants used by
    # raise_window).
    return bool(ApplicationServices.AXIsProcessTrusted())  # pyright: ignore[reportAttributeAccessIssue]


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

    def __init__(self, *, ledger: PermissionLedger | None = None) -> None:
        self._ledger = ledger if ledger is not None else PERMISSIONS
        self._Q, self._has_quartz = _load_quartz()
        if not self._has_quartz:
            log.warning(
                "[mac key] PyObjC Quartz not available; "
                "trackpad pointer / clicks will log only "
                "(install with: pip install pyobjc-framework-Quartz)"
            )
        else:
            _log_input_monitoring_hint("[mac key]")
        # Track the held-button state so emit_pointer emits
        # ``LeftMouseDragged`` (not ``MouseMoved``) while the user is
        # mid-drag. The server drives this via pad_drag start/end.
        self._dragging_left = False
        self._check_accessibility(self._ledger)
        self._check_ax_trust()

    # -- key -----------------------------------------------------------------

    @staticmethod
    def _check_accessibility(ledger: PermissionLedger) -> None:
        """Check that osascript can send keystrokes via System Events.

        macOS 14+ may silently deny keystroke injection even when the
        terminal is listed in Accessibility preferences (a re-add often
        fixes it). This probe warns the user at startup with actionable
        instructions instead of failing silently on the first button
        press, and records the result in ``ledger`` so the client's
        banner is up before any button is pressed (#196).
        """
        try:
            proc = subprocess.run(
                ["osascript", "-e", _KEYSTROKE_PROBE],
                capture_output=True, text=True, timeout=10,
            )
            issue = ledger.observe(proc.returncode, proc.stderr or "", keystroke=True)
            if proc.returncode != 0:
                reason = (proc.stderr or "").strip() or f"exit code {proc.returncode}"
                grant = (
                    "Automation > System Events"
                    if issue == AUTOMATION_MISSING
                    else "Accessibility"
                )
                log.warning(
                    "[mac key] osascript keystroke probe failed: %s\n"
                    "  Grant %s to %s in System Settings > Privacy & Security.\n"
                    "  If already listed, remove it, re-add it, then restart the app.",
                    reason,
                    grant,
                    _responsible_app_name(),
                )
        except FileNotFoundError:
            log.warning("[mac key] osascript not found; key injection unavailable")
        except subprocess.TimeoutExpired:
            log.warning("[mac key] osascript keystroke probe timed out")

    @staticmethod
    def _check_ax_trust() -> None:
        """Warn when Accessibility is missing — the *silent* failure.

        The osascript probe above covers the System Events grant, which is
        separate: keystrokes and focus can work perfectly while every
        Quartz event is dropped without an error and ``raise_window``
        fails at ``AXRaise``. Both grants follow the responsible process
        (the terminal / launchd agent), so this is worth saying at
        startup rather than leaving the user to wonder why the trackpad
        does nothing.
        """
        if _ax_trusted() is not False:
            return
        log.warning(
            "[mac key] Accessibility is not granted to %s — Quartz pointer / "
            "click / drag / scroll events will be silently dropped and "
            "raise_window will fail (kAXErrorAPIDisabled).\n"
            "  Grant it in System Settings > Privacy & Security > "
            "Accessibility, then restart that app.",
            _responsible_app_name(),
        )

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
        err = err or ""
        issue = self._ledger.observe(proc.returncode or 0, err, keystroke=True)
        if issue is not None:
            # Refused for want of a grant (#196): raise so the server can
            # toast the requesting client instead of the press vanishing.
            log.warning("[mac key] osascript refused (%s): %s", issue, err.strip())
            raise PermissionDenied(issue, _blocked_message(issue))
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
            _log_input_monitoring_hint("[mac scroll]")
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
        # Truncate toward zero, not floor. ``-4 // 120`` is ``-1``, so
        # floor division fired a full detent on the first downward tick
        # of a gesture and then set the remainder to +116 — which ate the
        # next 120 units. Downward scrolling over-fired, upward scrolling
        # under-fired, and momentum (small decaying deltas either side of
        # zero) mostly emitted nothing at all.
        detents = int(self._wheel_remainder / self.DETENT)
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
