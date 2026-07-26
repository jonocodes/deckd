"""Schema and integration tests for the mediabrowser widget (issue #50).

Three concerns, one ticket:

1. The ``MediaBrowser`` Pydantic model (schema for the new widget kind).
2. The matching ``mpris.yaml`` shipping layout + ``Layout`` / ``Widget``
   models accepting a ``mediabrowser``-kind widget with the new optional
   fields.
3. The server's view-resolution hook: ``select_view`` / ``clear_view``
   client -> daemon messages resolve the synthetic ``mpris`` view to
   the ``mpris.yaml`` layout, with the ``view`` field set on the
   ``LayoutMessage`` so the client can tell focus-driven layouts from
   client-requested ones. An unknown view produces a ``LayoutMessage``
   with ``view`` set to the request and ``error`` set to a
   ``"view not found"`` code.

The integration tests live here (rather than in ``test_mpris_websocket.py``)
because the seam they exercise — view resolution in ``Server._dispatch`` —
is a server concern, not a per-row media-pump concern.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import websockets
from aiohttp.test_utils import TestServer
from pydantic import ValidationError

from conftest import FakeFocusBackend, make_test_server
from deckd.layouts import Layout, Widget, load_layouts
from deckd.mpris import MediaBrowser
from deckd.platform import AppInfo


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_media_browser_defaults() -> None:
    """The model's required fields are ``id`` and ``grid``; the two optional
    knobs default to ``playing_first`` and ``show`` respectively."""
    widget = MediaBrowser.model_validate({"id": "browser", "grid": [0, 0, 4, 2]})

    assert widget.id == "browser"
    assert widget.grid == [0, 0, 4, 2]
    assert widget.ordering == "playing_first"
    assert widget.empty_state == "show"


def test_media_browser_accepts_explicit_knobs() -> None:
    """Both knobs accept every documented value."""
    stable = MediaBrowser.model_validate(
        {"id": "browser", "grid": [0, 0, 4, 2], "ordering": "stable", "empty_state": "hide"}
    )
    assert stable.ordering == "stable"
    assert stable.empty_state == "hide"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ordering", "alphabetical"),
        ("ordering", ""),
        ("empty_state", "auto"),
        ("empty_state", ""),
    ],
)
def test_media_browser_rejects_unknown_knobs(field: str, value: str) -> None:
    """Invalid knob values are a schema violation, surfaced as ``ValidationError``."""
    with pytest.raises(ValidationError):
        MediaBrowser.model_validate({"id": "browser", "grid": [0, 0, 4, 2], field: value})


def test_media_browser_rejects_bad_grid() -> None:
    """The grid field reuses the existing 4-int tuple invariant."""
    with pytest.raises(ValidationError):
        MediaBrowser.model_validate({"id": "browser", "grid": [0, 0, 1]})
    with pytest.raises(ValidationError):
        MediaBrowser.model_validate({"id": "browser", "grid": [0, 0, 1, 1, 1]})


def test_media_browser_rejects_extra_fields() -> None:
    """Unknown fields are rejected so a typo in ``mpris.yaml`` is loud."""
    with pytest.raises(ValidationError):
        MediaBrowser.model_validate(
            {"id": "browser", "grid": [0, 0, 4, 2], "ordring": "stable"}
        )


def test_widget_accepts_mediabrowser_kind_with_optional_knobs() -> None:
    """The daemon's ``Widget`` model (the one YAML flows through) accepts a
    ``mediabrowser`` kind and round-trips the two new optional fields the
    client needs to know about (``ordering`` / ``empty_state``)."""
    widget = Widget.model_validate(
        {
            "id": "browser",
            "kind": "mediabrowser",
            "grid": [0, 0, 4, 2],
            "ordering": "stable",
            "empty_state": "hide",
        }
    )
    assert widget.kind == "mediabrowser"
    assert widget.ordering == "stable"
    assert widget.empty_state == "hide"
    dumped = widget.model_dump()
    assert dumped["ordering"] == "stable"
    assert dumped["empty_state"] == "hide"


def test_widget_defaults_mediabrowser_knobs() -> None:
    widget = Widget.model_validate(
        {"id": "browser", "kind": "mediabrowser", "grid": [0, 0, 4, 2]}
    )
    assert widget.ordering == "playing_first"
    assert widget.empty_state == "show"


def test_widget_rejects_mediabrowser_knobs_on_other_kinds() -> None:
    """Mirrors the existing media-only-fields rule: ``ordering`` and
    ``empty_state`` are only valid on ``kind: mediabrowser``."""
    for field, value in [("ordering", "stable"), ("empty_state", "hide")]:
        with pytest.raises(ValueError, match="mediabrowser-only"):
            Widget.model_validate(
                {"id": "back", "kind": "button", "grid": [0, 0, 1, 1], field: value}
            )


def test_widget_rejects_unknown_ordering_value() -> None:
    with pytest.raises(ValidationError):
        Widget.model_validate(
            {
                "id": "browser",
                "kind": "mediabrowser",
                "grid": [0, 0, 4, 2],
                "ordering": "alphabetical",
            }
        )


def test_widget_mediabrowser_round_trips_through_json_wire_shape() -> None:
    """The TS ``Widget`` type (issue #50 acceptance bullet) declares
    ``ordering`` / ``empty_state`` as optional ``null``-able fields.
    This is the wire-shape contract: a ``Widget`` serialised on the
    Python side must parse back into the same shape with the documented
    defaults populated (so a TS client can rely on receiving both keys
    even when the YAML omits them)."""
    widget = Widget.model_validate(
        {"id": "browser", "kind": "mediabrowser", "grid": [0, 0, 4, 2]}
    )
    # The on-the-wire shape is ``model_dump_json()`` parsed by the TS
    # client — every key the TS union declares must be present so a
    # client with a stale types file can still destructure it.
    dumped = json.loads(widget.model_dump_json())
    assert dumped["kind"] == "mediabrowser"
    assert dumped["ordering"] == "playing_first"
    assert dumped["empty_state"] == "show"
    # And a wire shape with both knobs explicit survives the round-trip.
    explicit = Widget.model_validate(
        {
            "id": "browser",
            "kind": "mediabrowser",
            "grid": [0, 0, 4, 2],
            "ordering": "stable",
            "empty_state": "hide",
        }
    )
    explicit_dumped = json.loads(explicit.model_dump_json())
    assert explicit_dumped["ordering"] == "stable"
    assert explicit_dumped["empty_state"] == "hide"


# ---------------------------------------------------------------------------
# mpris.yaml: the shipping layout
# ---------------------------------------------------------------------------


REPO_LAYOUTS_DIR = Path(__file__).parent.parent / "layouts"


def test_shipping_mpris_layout_loads_and_has_mediabrowser_widget() -> None:
    """The new ``mpris.yaml`` shipping layout declares one ``mediabrowser``
    widget and loads through the regular layout loader."""
    store = load_layouts(REPO_LAYOUTS_DIR)
    # Match-by-token id is "mpris"; the layout id is the first match token.
    assert "mpris" in store
    layout = store["mpris"]
    assert len(layout.widgets) == 1
    widget = layout.widgets[0]
    assert widget.kind == "mediabrowser"
    assert widget.id  # non-empty
    # Defaults survive the round-trip even when the YAML omits them.
    assert widget.ordering == "playing_first"
    assert widget.empty_state == "show"


def test_shipping_layouts_round_trip_through_layout_dump() -> None:
    """Every shipping layout must survive ``Layout.model_dump`` losslessly
    so the daemon can serialise it to the client."""
    store = load_layouts(REPO_LAYOUTS_DIR)
    for original in store.layouts:
        rebuilt = Layout.model_validate(original.model_dump())
        assert rebuilt.id == original.id


# ---------------------------------------------------------------------------
# View resolution: server end-to-end
# ---------------------------------------------------------------------------


MPRIS_LAYOUT = """
match: [mpris]
display_name: MPRIS
widgets:
  - id: browser
    kind: mediabrowser
    grid: [0, 0, 4, 2]
"""

DEFAULT_LAYOUT = """
match: [default]
display_name: Home
widgets:
  - id: home
    kind: button
    label: Home
    grid: [0, 0, 1, 1]
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


async def _drain(ws) -> list[dict]:
    messages: list[dict] = []
    try:
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 0.5))
            messages.append(msg)
    except asyncio.TimeoutError:
        return messages


async def _drive_session(tmp_path: Path, payloads: list[dict]) -> list[dict]:
    """Drive a single websocket session end-to-end and return every message
    it received, in arrival order. Each ``payload`` is sent in sequence
    between drains."""
    (tmp_path / "default.yaml").write_text(DEFAULT_LAYOUT)
    _write(tmp_path, "mpris.yaml", MPRIS_LAYOUT)
    server, *_ = make_test_server(layouts_dir=tmp_path)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            messages = await _drain(ws)
            for payload in payloads:
                await ws.send(json.dumps(payload))
                messages.extend(await _drain(ws))
        return messages
    finally:
        await server.stop()
        await test_server.close()


async def test_select_view_pushes_mpris_layout_with_view_set(tmp_path: Path) -> None:
    """Sending ``select_view: "mpris"`` after connect causes the server to
    push a ``LayoutMessage`` with ``view: "mpris"`` and the ``mpris.yaml``
    widgets in its ``widgets`` array."""
    messages = await _drive_session(tmp_path, [{"type": "select_view", "view": "mpris"}])
    layouts = [m for m in messages if m.get("type") == "layout"]
    assert len(layouts) == 2, f"expected initial + view-pushed layouts, got {layouts}"
    initial, switched = layouts
    assert initial["view"] is None
    assert initial["app"] == "default"
    assert switched["view"] == "mpris"
    assert switched["app"] == "mpris"
    assert [w["kind"] for w in switched["widgets"]] == ["mediabrowser"]


async def test_clear_view_reverts_to_focused_app_layout(tmp_path: Path) -> None:
    """``clear_view`` undoes a previous ``select_view``: the next push is
    the focused-app layout with ``view: null``."""
    messages = await _drive_session(
        tmp_path,
        [
            {"type": "select_view", "view": "mpris"},
            {"type": "clear_view"},
        ],
    )
    layouts = [m for m in messages if m.get("type") == "layout"]
    # initial + select_view pushed + clear_view pushed = 3
    assert len(layouts) == 3
    assert layouts[-1]["view"] is None
    assert layouts[-1]["app"] == "default"


async def test_unknown_view_returns_error(tmp_path: Path) -> None:
    """A ``select_view`` with an unknown view name produces a
    ``LayoutMessage`` with the requested ``view`` echoed back,
    ``error: "view not found"``, and the focused-app widgets intact so
    the chrome stays usable while the failure is surfaced."""
    messages = await _drive_session(tmp_path, [{"type": "select_view", "view": "nope"}])
    layouts = [m for m in messages if m.get("type") == "layout"]
    assert len(layouts) == 2
    errored = layouts[-1]
    assert errored["view"] == "nope"
    assert errored["error"] == "view not found"
    # The focused-app widgets still ride along so the chrome doesn't
    # blank out — only a real layout error (bad YAML) collapses the grid.
    assert [w["kind"] for w in errored["widgets"]] == ["button"]


async def test_view_resolution_holds_across_focus_changes(tmp_path: Path) -> None:
    """A selected view survives the next genuine focus change — the user
    selected the chrome view intentionally, so it sticks until
    ``clear_view`` (or the session ends). This is the carve-out from
    ADR-0003: focus re-resolves the *layout*, but a selected view isn't a
    layout, it's a chrome view the daemon re-pushes on every focus change
    until the client explicitly clears it."""
    (tmp_path / "default.yaml").write_text(DEFAULT_LAYOUT)
    _write(
        tmp_path,
        "firefox.yaml",
        """
match: [firefox]
widgets:
  - id: back
    kind: button
    label: Back
    grid: [0, 0, 1, 1]
""",
    )
    _write(tmp_path, "mpris.yaml", MPRIS_LAYOUT)
    focus_backend = FakeFocusBackend()
    server, *_ = make_test_server(layouts_dir=tmp_path, focus_backend=focus_backend)
    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    server.start_focus_watcher()
    try:
        async with websockets.connect(f"ws://127.0.0.1:{test_server.port}/ws") as ws:
            messages = await _drain(ws)
            await ws.send(json.dumps({"type": "select_view", "view": "mpris"}))
            messages.extend(await _drain(ws))
            await focus_backend.push(AppInfo(app_id="firefox", wm_class="firefox"))
            # Give the daemon a moment to react to the focus change.
            await asyncio.sleep(0.2)
            messages.extend(await _drain(ws))
    finally:
        await server.stop()
        await test_server.close()

    layouts = [m for m in messages if m.get("type") == "layout"]
    assert layouts, "no layout frames received"
    # Every push after the initial one keeps ``view == "mpris"``.
    for layout in layouts[1:]:
        assert layout["view"] == "mpris"
