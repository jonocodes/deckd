"""Schema and integration tests for the nowplaying widget (issue #50).

Three concerns, one ticket:

1. The ``NowPlaying`` Pydantic model (schema for the new widget kind).
2. The matching ``mpris.yaml`` shipping layout + ``Layout`` / ``Widget``
   models accepting a ``nowplaying``-kind widget with the
   ``empty_state`` knob (issue #58 removed the ``ordering`` knob).
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
from deckd.mpris import NowPlaying
from deckd.platform import AppInfo


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_nowplaying_defaults() -> None:
    """The model's only required field is ``id``; ``size`` is an optional
    reflow extent (ADR-0010) and ``empty_state`` defaults to ``show``
    (issue #58 removed the ``ordering`` knob)."""
    widget = NowPlaying.model_validate({"id": "browser", "size": [4, 2]})

    assert widget.id == "browser"
    assert widget.size == [4, 2]
    assert widget.empty_state == "show"


def test_nowplaying_accepts_explicit_knobs() -> None:
    """The ``empty_state`` knob accepts both documented values."""
    hidden = NowPlaying.model_validate(
        {"id": "browser", "size": [4, 2], "empty_state": "hide"}
    )
    assert hidden.empty_state == "hide"


@pytest.mark.parametrize(
    "field,value",
    [
        ("empty_state", "auto"),
        ("empty_state", ""),
    ],
)
def test_nowplaying_rejects_unknown_knobs(field: str, value: str) -> None:
    """Invalid knob values are a schema violation, surfaced as ``ValidationError``."""
    with pytest.raises(ValidationError):
        NowPlaying.model_validate({"id": "browser", "size": [4, 2], field: value})


def test_nowplaying_defaults_size_to_none() -> None:
    """``size`` is optional (ADR-0010): a nowplaying is typically a
    full-surface view rendered outside the flow, so it needs no span."""
    widget = NowPlaying.model_validate({"id": "browser"})
    assert widget.size is None


def test_nowplaying_rejects_extra_fields() -> None:
    """Unknown fields are rejected so a typo in ``mpris.yaml`` is loud
    (issue #58: the removed ``ordering`` knob is the most likely typo)."""
    with pytest.raises(ValidationError):
        NowPlaying.model_validate(
            {"id": "browser", "size": [4, 2], "ordring": "stable"}
        )


@pytest.mark.parametrize("model", [NowPlaying, Widget])
def test_rejects_removed_ordering_knob(model) -> None:
    """Issue #58 removed the ``ordering`` knob: a layout that still
    declares it must fail loud rather than silently ignore the intent.
    Both the dedicated ``NowPlaying`` model and the generic
    ``Widget`` model (the one YAML flows through) reject it via
    ``extra='forbid'``."""
    payload = {
        "id": "browser",
        "kind": "nowplaying",
        "size": [4, 2],
        "ordering": "playing_first",
    }
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_widget_accepts_nowplaying_kind_with_optional_knobs() -> None:
    """The daemon's ``Widget`` model (the one YAML flows through) accepts a
    ``nowplaying`` kind and round-trips the optional ``empty_state``
    field the client needs to know about (issue #58 removed the
    ``ordering`` knob)."""
    widget = Widget.model_validate(
        {
            "id": "browser",
            "kind": "nowplaying",
            "size": [4, 2],
            "empty_state": "hide",
        }
    )
    assert widget.kind == "nowplaying"
    assert widget.empty_state == "hide"
    dumped = widget.model_dump()
    assert dumped["empty_state"] == "hide"


def test_widget_defaults_nowplaying_knobs() -> None:
    widget = Widget.model_validate(
        {"id": "browser", "kind": "nowplaying", "size": [4, 2]}
    )
    assert widget.empty_state == "show"


def test_widget_rejects_nowplaying_knobs_on_other_kinds() -> None:
    """Mirrors the existing media-only-fields rule: ``empty_state``
    is only valid on ``kind: nowplaying``."""
    with pytest.raises(ValueError, match="nowplaying-only"):
        Widget.model_validate(
            {
                "id": "back",
                "kind": "button",
                "empty_state": "hide",
            }
        )


def test_widget_nowplaying_round_trips_through_json_wire_shape() -> None:
    """The TS ``Widget`` type declares ``empty_state`` as an optional
    ``null``-able field. This is the wire-shape contract: a ``Widget``
    serialised on the Python side must parse back into the same shape
    with the documented default populated (so a TS client can rely on
    receiving the key even when the YAML omits it — issue #58 dropped
    ``ordering``)."""
    widget = Widget.model_validate(
        {"id": "browser", "kind": "nowplaying", "size": [4, 2]}
    )
    # The on-the-wire shape is ``model_dump_json()`` parsed by the TS
    # client — every key the TS union declares must be present so a
    # client with a stale types file can still destructure it.
    dumped = json.loads(widget.model_dump_json())
    assert dumped["kind"] == "nowplaying"
    assert dumped["empty_state"] == "show"
    # And a wire shape with the knob explicit survives the round-trip.
    explicit = Widget.model_validate(
        {
            "id": "browser",
            "kind": "nowplaying",
            "size": [4, 2],
            "empty_state": "hide",
        }
    )
    explicit_dumped = json.loads(explicit.model_dump_json())
    assert explicit_dumped["empty_state"] == "hide"


# ---------------------------------------------------------------------------
# mpris.yaml: the shipping layout
# ---------------------------------------------------------------------------


REPO_LAYOUTS_DIR = Path(__file__).parent.parent / "layouts"


def test_shipping_mpris_layout_loads_and_has_nowplaying_widget() -> None:
    """The new ``mpris.yaml`` shipping layout declares one ``nowplaying``
    widget and loads through the regular layout loader."""
    store = load_layouts(REPO_LAYOUTS_DIR)
    # Match-by-token id is "mpris"; the layout id is the first match token.
    assert "mpris" in store
    layout = store["mpris"]
    assert len(layout.widgets) == 1
    widget = layout.widgets[0]
    assert widget.kind == "nowplaying"
    assert widget.id  # non-empty
    # Default survives the round-trip even when the YAML omits it.
    # (Issue #58 removed the ``ordering`` knob — no longer asserted.)
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
    kind: nowplaying
    size: [4, 2]
"""

DEFAULT_LAYOUT = """
match: [default]
display_name: Home
widgets:
  - id: home
    kind: button
    label: Home
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
    assert [w["kind"] for w in switched["widgets"]] == ["nowplaying"]


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
