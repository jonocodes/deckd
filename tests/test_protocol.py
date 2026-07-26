from __future__ import annotations

import pytest
from pydantic import ValidationError

from deckd.protocol import LayoutMessage, MediaCommandMessage


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






