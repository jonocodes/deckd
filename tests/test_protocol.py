from __future__ import annotations

import pytest
from pydantic import ValidationError

from deckd.protocol import (
    LayoutMessage,
    MediaCommandMessage,
    RunningWindowsMessage,
    WindowListEntry,
)


@pytest.mark.parametrize("command", ["play-pause", "next", "previous"])
def test_media_command_without_value_round_trips(command: str) -> None:
    message = MediaCommandMessage(type="media_command", id="media", command=command)

    assert MediaCommandMessage.model_validate_json(message.model_dump_json()) == message
    assert message.value is None


@pytest.mark.parametrize("command", ["volume", "seek", "rate"])
def test_value_media_commands_round_trip(command: str) -> None:
    message = MediaCommandMessage(type="media_command", id="media", command=command, value=55)

    assert MediaCommandMessage.model_validate_json(message.model_dump_json()) == message


def test_layout_view_defaults_to_none_and_round_trips() -> None:
    normal = LayoutMessage(type="layout", widgets=[])
    chrome = LayoutMessage(type="layout", widgets=[], view="media")

    assert normal.view is None
    assert LayoutMessage.model_validate_json(normal.model_dump_json()).view is None
    assert LayoutMessage.model_validate_json(chrome.model_dump_json()).view == "media"


def test_media_command_rejects_value_for_value_less_commands() -> None:
    with pytest.raises(ValidationError):
        MediaCommandMessage.model_validate(
            {"type": "media_command", "id": "media", "command": "next", "value": 1}
        )


def test_media_command_rejects_missing_value_for_value_commands() -> None:
    with pytest.raises(ValidationError):
        MediaCommandMessage.model_validate(
            {"type": "media_command", "id": "media", "command": "volume"}
        )


# ---------------------------------------------------------------------------
# RunningWindowsMessage (issues #120 / #126)
# ---------------------------------------------------------------------------


def test_running_windows_round_trips_with_icon_and_null_icon() -> None:
    """Both icon-bearing rows and default-fallback rows (icon=None,
    decision 6 — honest absence, not decorative) round-trip through
    JSON unchanged. Same wire-shape rule as ``LayoutMessage.icon``.
    """
    entries = [
        WindowListEntry(
            window_id="w1",
            label="Firefox",
            icon={"source": "simple-icons", "name": "firefox"},
        ),
        WindowListEntry(window_id="w2", label="xterm", icon=None),
    ]
    msg = RunningWindowsMessage(type="running_windows", windows=entries)
    round_tripped = RunningWindowsMessage.model_validate_json(msg.model_dump_json())
    assert round_tripped == msg
    assert round_tripped.windows[1].icon is None


def test_running_windows_empty_list_round_trips() -> None:
    """An empty snapshot (a desktop with no open windows) round-trips
    as ``windows: []``. The chrome view's empty state never reads a
    missing field — it reads the absence of any entry."""
    msg = RunningWindowsMessage(type="running_windows", windows=[])
    round_tripped = RunningWindowsMessage.model_validate_json(msg.model_dump_json())
    assert round_tripped.windows == []


def test_running_windows_rejects_empty_window_id() -> None:
    """``window_id`` is the round-trip key from extension to daemon to
    client to tap (#119). Empty id would be a meaningless tap target —
    reject at validation so the wire-shape contract stays tight."""
    with pytest.raises(ValidationError):
        WindowListEntry(window_id="", label="xterm", icon=None)


def test_running_windows_rejects_empty_label() -> None:
    """A row with no label has nothing to render in the chrome list —
    reject at validation rather than allow a blank row that conveys
    no identity to the user."""
    with pytest.raises(ValidationError):
        WindowListEntry(window_id="w1", label="", icon=None)


def test_running_windows_rejects_unknown_fields() -> None:
    """Forward-compatibility rule (mirrors ``LayoutMessage.extra='forbid'``):
    a future field the daemon doesn't know about surfaces as a validation
    error so an older daemon doesn't silently drop structured data."""
    with pytest.raises(ValidationError):
        WindowListEntry.model_validate(
            {"window_id": "w1", "label": "x", "future_field": True}
        )


def test_running_windows_message_rejects_unknown_top_level_field() -> None:
    """Same rule at the message level — extra keys break the
    discriminator's invariants."""
    with pytest.raises(ValidationError):
        RunningWindowsMessage.model_validate(
            {"type": "running_windows", "windows": [], "future": True}
        )






