"""Tests for the confirmation-handshake wire messages (issues #69 / #107).

Round-trips through JSON so the ``extra=forbid`` schema and the
discriminated-union membership both surface as test failures, not just
Pydantic init-time errors.
"""
from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from deckd.protocol import (
    ClientMessage,
    ConfirmResponseMessage,
    ConfirmRequestMessage,
    ServerMessage,
)


def test_confirm_request_round_trips() -> None:
    msg = ConfirmRequestMessage(type="confirm_request", confirm_id="abc", widget_id="rm-all")
    encoded = msg.model_dump_json()
    decoded = ConfirmRequestMessage.model_validate_json(encoded)
    assert decoded == msg


def test_confirm_response_round_trips_confirm() -> None:
    msg = ConfirmResponseMessage(type="confirm_response", confirm_id="abc", decision="confirm")
    encoded = msg.model_dump_json()
    decoded = ConfirmResponseMessage.model_validate_json(encoded)
    assert decoded == msg


def test_confirm_response_round_trips_cancel() -> None:
    msg = ConfirmResponseMessage(type="confirm_response", confirm_id="abc", decision="cancel")
    assert msg.decision == "cancel"


def test_confirm_response_rejects_unknown_decision() -> None:
    with pytest.raises(ValidationError):
        ConfirmResponseMessage(type="confirm_response", confirm_id="abc", decision="yes")


def test_confirm_request_rejects_empty_confirm_id() -> None:
    with pytest.raises(ValidationError):
        ConfirmRequestMessage(type="confirm_request", confirm_id="", widget_id="w")


def test_confirm_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ConfirmRequestMessage.model_validate(
            {"type": "confirm_request", "confirm_id": "abc", "widget_id": "w", "extra": 1}
        )


def test_confirm_response_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ConfirmResponseMessage.model_validate(
            {"type": "confirm_response", "confirm_id": "abc", "decision": "confirm", "extra": 1}
        )


def test_confirm_request_in_server_message_union() -> None:
    """Discriminated union must accept a ConfirmRequestMessage as a ServerMessage."""
    adapter = TypeAdapter(ServerMessage)
    msg = adapter.validate_python(
        {"type": "confirm_request", "confirm_id": "abc", "widget_id": "w"}
    )
    assert isinstance(msg, ConfirmRequestMessage)


def test_confirm_response_in_client_message_union() -> None:
    """Discriminated union must accept a ConfirmResponseMessage as a ClientMessage."""
    adapter = TypeAdapter(ClientMessage)
    msg = adapter.validate_python(
        {"type": "confirm_response", "confirm_id": "abc", "decision": "confirm"}
    )
    assert isinstance(msg, ConfirmResponseMessage)
