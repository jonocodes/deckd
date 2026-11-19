"""macOS Automation + action-time permission failures (issue #196).

Key buttons on macOS go through ``osascript`` -> System Events, which needs
two grants: Automation (System Events) and Accessibility. Either one
missing used to fail silently. These tests pin:

* osascript stderr -> health-issue classification (no false positives),
* the ledger that remembers what an action saw, and clears on success,
* the proactive Automation check's status mapping,
* the backend folding both into ``health_issues()``,
* the key sink raising :class:`PermissionDenied` so the server can toast.
"""
from __future__ import annotations

import sys

import pytest

import deckd.platform_macos as mac
from deckd.input import PermissionDenied

AUTOMATION = "automation_system_events_missing"
ACCESSIBILITY = "accessibility_missing"

# Real stderr lines, as osascript prints them.
STDERR_1743 = (
    "36:61: execution error: Not authorized to send Apple events to "
    "System Events. (-1743)"
)
STDERR_1002 = (
    "36:61: execution error: System Events got an error: osascript is not "
    "allowed to send keystrokes. (1002)"
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """Trusted for Accessibility and named like the packaged app. (conftest
    already stubs the Automation probe and gives each test a fresh ledger.)"""
    monkeypatch.setattr(mac, "_ax_trusted", lambda: True)
    monkeypatch.setattr(mac, "_responsible_app_name", lambda: "deckd.app")


# ---------------------------------------------------------------------------
# stderr classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (STDERR_1743, AUTOMATION),
        (STDERR_1002, ACCESSIBILITY),
        # Trailing whitespace / newline as read from a pipe.
        (STDERR_1743 + "\n", AUTOMATION),
        # Localised message text: the code is what counts.
        ("0:44: execution error: Keine Berechtigung. (-1743)", AUTOMATION),
    ],
)
def test_classifies_permission_errors(stderr: str, expected: str) -> None:
    assert mac.classify_osascript_error(stderr) == expected


@pytest.mark.parametrize(
    "stderr",
    [
        "",
        # Unrelated AppleScript errors.
        "0:12: syntax error: Expected end of line but found identifier. (-2741)",
        "1:80: execution error: System Events got an error: Can't get "
        "window 1 of process \"Finder\". Invalid index. (-1719)",
        # The digits appear, but not as the error code.
        "1:80: execution error: Can't get window 1002 of process \"X\". (-1728)",
        "1:80: execution error: Can't get item (-1743) of list. (-1728)",
        "osascript: no such file",
    ],
)
def test_unrelated_errors_are_not_permission_errors(stderr: str) -> None:
    assert mac.classify_osascript_error(stderr) is None


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def test_ledger_records_a_denial() -> None:
    ledger = mac.PermissionLedger()
    assert ledger.observe(1, STDERR_1743, keystroke=True) == AUTOMATION
    assert ledger.denied() == {AUTOMATION}


def test_ledger_ignores_unrelated_failures() -> None:
    ledger = mac.PermissionLedger()
    ledger.observe(1, STDERR_1743, keystroke=False)
    assert ledger.observe(1, "0:1: execution error: boom (-1719)", keystroke=True) is None
    # An unrelated failure says nothing about the grant either way.
    assert ledger.denied() == {AUTOMATION}


def test_ledger_accessibility_denial_proves_automation() -> None:
    """``(1002)`` comes back *from* System Events, so the Apple event got
    through: Automation is granted even if an earlier call said otherwise."""
    ledger = mac.PermissionLedger()
    ledger.observe(1, STDERR_1743, keystroke=True)
    ledger.observe(1, STDERR_1002, keystroke=True)
    assert ledger.denied() == {ACCESSIBILITY}


def test_ledger_focus_success_clears_automation_only() -> None:
    """A focus query only proves Automation; it sends no keystrokes."""
    ledger = mac.PermissionLedger()
    ledger.observe(1, STDERR_1002, keystroke=True)
    ledger.observe(1, STDERR_1743, keystroke=False)
    ledger.observe(0, "", keystroke=False)
    assert ledger.denied() == {ACCESSIBILITY}


def test_ledger_keystroke_success_clears_both() -> None:
    ledger = mac.PermissionLedger()
    ledger.observe(1, STDERR_1002, keystroke=True)
    ledger.observe(0, "", keystroke=True)
    assert ledger.denied() == frozenset()


# ---------------------------------------------------------------------------
# Proactive Automation check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (0, True),  # noErr: granted
        (-1743, False),  # errAEEventNotPermitted: denied
        (-1744, None),  # errAEEventWouldRequireUserConsent: not asked yet
        (-600, None),  # procNotFound: System Events isn't running
        (-50, None),  # anything else: can't tell
    ],
)
def test_automation_status_mapping(status: int, expected: bool | None) -> None:
    assert mac._automation_status(status) is expected


@pytest.mark.skipif(sys.platform != "darwin", reason="needs CoreServices")
def test_automation_probe_runs_on_macos(monkeypatch) -> None:
    """The real ctypes call answers without prompting or raising."""
    monkeypatch.undo()  # drop the autouse stub for this one
    assert mac._automation_permission() in (True, False, None)


def test_automation_probe_is_unknown_off_macos(monkeypatch) -> None:
    monkeypatch.undo()
    monkeypatch.setattr(sys, "platform", "linux")
    assert mac._automation_permission() is None


# ---------------------------------------------------------------------------
# Backend -> health issues
# ---------------------------------------------------------------------------


def _ids(backend: mac.MacFocusBackend) -> list[str]:
    return [i.id for i in backend.health_issues()]


def test_proactive_automation_denial_raises_the_issue(monkeypatch) -> None:
    monkeypatch.setattr(mac, "_automation_permission", lambda: False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    issues = mac.MacFocusBackend().health_issues()

    assert [i.id for i in issues] == [AUTOMATION]
    issue = issues[0]
    assert issue.severity == "error"
    text = " ".join([issue.title, issue.detail, *issue.fix_steps])
    assert "deckd.app" in text
    assert "Privacy & Security → Automation" in text
    assert "System Events" in text
    assert any("tccutil reset AppleEvents com.deckd.daemon" in s for s in issue.fix_steps)
    assert set(issue.affects) == {"key", "focus"}


def test_automation_issue_from_a_checkout_offers_no_tccutil(monkeypatch) -> None:
    monkeypatch.setattr(mac, "_automation_permission", lambda: False)
    monkeypatch.setattr(mac, "_responsible_app_name", lambda: "iTerm.app")
    monkeypatch.delattr(sys, "frozen", raising=False)

    (issue,) = mac.MacFocusBackend().health_issues()
    text = " ".join(issue.fix_steps)
    assert "iTerm.app" in text
    assert "tccutil" not in text


@pytest.mark.parametrize("answer", [True, None])
def test_no_automation_issue_when_granted_or_unknown(monkeypatch, answer) -> None:
    monkeypatch.setattr(mac, "_automation_permission", lambda: answer)
    assert _ids(mac.MacFocusBackend()) == []


def test_both_grants_missing_lists_both(monkeypatch) -> None:
    monkeypatch.setattr(mac, "_ax_trusted", lambda: False)
    monkeypatch.setattr(mac, "_automation_permission", lambda: False)
    assert _ids(mac.MacFocusBackend()) == [ACCESSIBILITY, AUTOMATION]


def test_reactive_denial_raises_the_issue_while_the_probe_still_fails() -> None:
    """The proactive check says nothing (or is wrong), but an action saw
    -1743: the issue stands as long as a re-probe still fails."""
    ledger = mac.PermissionLedger()
    ledger.observe(1, STDERR_1743, keystroke=True)
    probes: list[int] = []

    def probe() -> tuple[int, str]:
        probes.append(1)
        return 1, STDERR_1743

    backend = mac.MacFocusBackend(ledger=ledger, keystroke_probe=probe)
    assert _ids(backend) == [AUTOMATION]
    assert probes, "a held reactive issue is re-checked, not assumed"


def test_reactive_issue_clears_once_the_probe_succeeds() -> None:
    ledger = mac.PermissionLedger()
    ledger.observe(1, STDERR_1002, keystroke=True)
    result = {"value": (1, STDERR_1002)}
    backend = mac.MacFocusBackend(ledger=ledger, keystroke_probe=lambda: result["value"])

    assert _ids(backend) == [ACCESSIBILITY]
    result["value"] = (0, "")
    assert _ids(backend) == []


def test_no_probe_while_nothing_is_held() -> None:
    def probe() -> tuple[int, str]:
        raise AssertionError("healthy hosts must not run osascript every poll")

    assert _ids(mac.MacFocusBackend(keystroke_probe=probe)) == []


def test_reactive_accessibility_is_not_listed_twice(monkeypatch) -> None:
    monkeypatch.setattr(mac, "_ax_trusted", lambda: False)
    ledger = mac.PermissionLedger()
    ledger.observe(1, STDERR_1002, keystroke=True)
    backend = mac.MacFocusBackend(ledger=ledger, keystroke_probe=lambda: (1, STDERR_1002))
    assert _ids(backend) == [ACCESSIBILITY]


# ---------------------------------------------------------------------------
# Focus query feeds the ledger
# ---------------------------------------------------------------------------


async def test_focus_query_denial_is_recorded(monkeypatch) -> None:
    async def denied(*_args: str) -> str:
        raise RuntimeError(f"osascript -e ... failed: {STDERR_1743}")

    monkeypatch.setattr(mac, "_run", denied)
    ledger = mac.PermissionLedger()
    with pytest.raises(RuntimeError):
        await mac.MacFocusBackend(ledger=ledger).get_active_app()
    assert ledger.denied() == {AUTOMATION}


async def test_focus_query_success_clears_automation(monkeypatch) -> None:
    async def ok(*_args: str) -> str:
        return "Firefox|||New Tab"

    monkeypatch.setattr(mac, "_run", ok)
    ledger = mac.PermissionLedger()
    ledger.observe(1, STDERR_1743, keystroke=False)
    app = await mac.MacFocusBackend(ledger=ledger).get_active_app()
    assert app.app_id == "Firefox"
    assert ledger.denied() == frozenset()


# ---------------------------------------------------------------------------
# Key sink -> PermissionDenied
# ---------------------------------------------------------------------------


class _FakePopen:
    """Stands in for ``subprocess.Popen`` in ``MacKeySink.emit_key``."""

    def __init__(self, returncode: int, stderr: str) -> None:
        self.returncode = returncode
        self._stderr = stderr

    def __call__(self, *_args, **_kwargs) -> "_FakePopen":
        return self

    def communicate(self) -> tuple[str, str]:
        return "", self._stderr


def _sink(ledger: mac.PermissionLedger) -> mac.MacKeySink:
    # Skip __init__: it runs real osascript / Quartz probes.
    sink = mac.MacKeySink.__new__(mac.MacKeySink)
    sink._ledger = ledger
    return sink


CMD_N = [125, 49]  # super+n


@pytest.mark.parametrize(
    ("stderr", "issue_id", "named"),
    [
        (STDERR_1743, AUTOMATION, "System Events"),
        (STDERR_1002, ACCESSIBILITY, "Accessibility"),
    ],
)
def test_key_sink_raises_permission_denied(monkeypatch, stderr, issue_id, named) -> None:
    monkeypatch.setattr(mac.subprocess, "Popen", _FakePopen(1, stderr))
    ledger = mac.PermissionLedger()

    with pytest.raises(PermissionDenied) as info:
        _sink(ledger).emit_key(CMD_N)

    assert info.value.issue_id == issue_id
    assert info.value.message.startswith("Key press blocked:")
    assert "deckd.app" in info.value.message
    assert named in info.value.message
    assert issue_id in ledger.denied()


def test_key_sink_unrelated_error_does_not_raise(monkeypatch) -> None:
    monkeypatch.setattr(
        mac.subprocess, "Popen", _FakePopen(1, "0:1: execution error: boom (-1719)")
    )
    ledger = mac.PermissionLedger()
    _sink(ledger).emit_key(CMD_N)  # logged, not raised
    assert ledger.denied() == frozenset()


def test_key_sink_success_clears_the_ledger(monkeypatch) -> None:
    monkeypatch.setattr(mac.subprocess, "Popen", _FakePopen(0, ""))
    ledger = mac.PermissionLedger()
    ledger.observe(1, STDERR_1002, keystroke=True)
    _sink(ledger).emit_key(CMD_N)
    assert ledger.denied() == frozenset()


def test_startup_probe_feeds_the_ledger(monkeypatch) -> None:
    """The keysink's startup probe records a denial, so the banner is up
    before the first button press even when the proactive check can't tell."""

    class _Done:
        returncode = 1
        stderr = STDERR_1743

    monkeypatch.setattr(mac.subprocess, "run", lambda *a, **k: _Done())
    ledger = mac.PermissionLedger()
    _sink(ledger)._check_system_events()
    assert ledger.denied() == {AUTOMATION}
