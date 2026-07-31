"""Unit tests for the diagnostics module (issue #70/71/72/73).

Covers the wire-format renderers, ring-buffer semantics, the
``build_*_snapshot`` helpers, and the JSON-logging formatter. Server-
integration tests live in ``test_diag_endpoints.py`` /
``test_event_stream.py``.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging

import pytest

from deckd.diagnostics import (
    ActionRecord,
    Metrics,
    MprisEventRecord,
    MprisEvents,
    RecentActions,
    build_diag_snapshot,
    build_layouts_snapshot,
    build_mpris_players_snapshot,
)
from deckd.logging_setup import JsonFormatter, setup_logging
from deckd.media import MediaState


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_metrics_render_minimal() -> None:
    m = Metrics()
    out = m.render()
    # Sanity-check the format shape: every metric has a # HELP /
    # # TYPE preamble and at least one sample line.
    assert "# HELP deckd_up" in out
    assert "# TYPE deckd_up gauge" in out
    assert "deckd_up 1" in out
    assert "# TYPE deckd_sessions_active gauge" in out
    assert "deckd_sessions_active 0" in out
    # Counters that haven't fired are still rendered (zero value).
    assert "deckd_layout_reload_total{status=\"ok\"} 0" in out
    assert "deckd_layout_reload_total{status=\"error\"} 0" in out


def test_metrics_record_action_increments_counters() -> None:
    m = Metrics()
    m.record_action("shell", "ok")
    m.record_action("shell", "ok")
    m.record_action("key", "guard_dropped")
    out = m.render()
    assert "deckd_action_total{primitive=\"shell\"} 2" in out
    assert "deckd_action_total{primitive=\"key\"} 1" in out
    assert 'deckd_action_outcome_total{primitive="shell",outcome="ok"} 2' in out
    assert (
        'deckd_action_outcome_total{primitive="key",outcome="guard_dropped"} 1'
        in out
    )


def test_metrics_record_mpris_command_tracks_errors() -> None:
    m = Metrics()
    m.record_mpris_command("play-pause", ok=True)
    m.record_mpris_command("play-pause", ok=False)
    out = m.render()
    assert 'deckd_mpris_command_total{command="play-pause"} 2' in out
    assert 'deckd_mpris_command_error_total{command="play-pause"} 1' in out


def test_metrics_dbcall_histogram_buckets() -> None:
    m = Metrics()
    for s in (0.001, 0.02, 0.07, 0.3, 0.7):
        m.record_dbcall(s)
    out = m.render()
    # All five samples plus the +Inf bucket line.
    assert "deckd_dbcall_seconds_count 5" in out
    # Cumulative-bucket histogram semantics: at least one sample in
    # every bucket up to 1s.
    for le in ("0.005", "0.01", "0.025", "0.05", "0.1", "0.25", "0.5", "1.0"):
        assert f'deckd_dbcall_seconds_bucket{{le="{le}"}}' in out
    assert 'deckd_dbcall_seconds_bucket{le="+Inf"} 5' in out


def test_metrics_label_value_escaping() -> None:
    """Quotes / backslashes in label values are escaped per the text-format spec."""
    m = Metrics()
    m.record_action('weird"action\\name', "ok")
    out = m.render()
    assert 'primitive="weird\\"action\\\\name"' in out


# ---------------------------------------------------------------------------
# Ring buffers
# ---------------------------------------------------------------------------


def test_recent_actions_ring_overflow_drops_oldest() -> None:
    buf = RecentActions(cap=3)
    for i in range(5):
        buf.add(
            ActionRecord(
                ts=float(i),
                layout_id="default",
                widget_id=f"w{i}",
                primitive="shell",
                outcome="ok",
                command_text=f"cmd-{i}",
                error=None,
            )
        )
    snap = buf.snapshot()
    assert len(snap) == 3
    assert [r.widget_id for r in snap] == ["w2", "w3", "w4"]
    # Limit shrinks without breaking the cap.
    snap = buf.snapshot(limit=2)
    assert [r.widget_id for r in snap] == ["w3", "w4"]


def test_action_record_to_wire_redacts_command_text() -> None:
    rec = ActionRecord(
        ts=0.0,
        layout_id="default",
        widget_id="open-url",
        primitive="shell",
        outcome="ok",
        command_text='echo "secret"',
        error="boom",
    )
    wire = rec.to_wire()
    assert set(wire.keys()) == {"ts", "layout_id", "widget_id", "primitive", "outcome"}
    assert "command_text" not in wire
    assert "error" not in wire


def test_mpris_events_ring_overflow() -> None:
    buf = MprisEvents(cap=2)
    buf.add(MprisEventRecord(ts=0.0, kind="player_added", row_id="vlc", data={}))
    buf.add(MprisEventRecord(ts=1.0, kind="player_added", row_id="firefox", data={}))
    buf.add(MprisEventRecord(ts=2.0, kind="player_removed", row_id="vlc", data={}))
    snap = buf.snapshot()
    assert [r.row_id for r in snap] == ["firefox", "vlc"]
    assert [r.kind for r in snap] == ["player_added", "player_removed"]


# ---------------------------------------------------------------------------
# Snapshot builders
# ---------------------------------------------------------------------------


def test_build_layouts_snapshot_hides_action_bodies() -> None:
    """``/layouts`` widgets report ``has_action`` but never the action payload."""
    from deckd.layouts import Action, Layout, Widget

    layout = Layout(
        id="test",
        match=["test"],
        widgets=[
            Widget(
                id="button-1",
                kind="button",
                action=Action(shell="xdg-open https://secret.example"),
            ),
            Widget(
                id="meter-1",
                kind="meter",
                source="cpu_percent",
            ),
        ],
    )

    class _Store:
        def __init__(self, layouts: list[Layout]) -> None:
            self._layouts = layouts

        @property
        def layouts(self) -> list[Layout]:
            return list(self._layouts)

    snap = build_layouts_snapshot(_Store([layout]))
    widgets = snap["layouts"][0]["widgets"]
    assert widgets[0]["id"] == "button-1"
    assert widgets[0]["has_action"] is True
    # Crucially no "action" / "shell" / "dbus" / "key" field.
    assert "action" not in widgets[0]
    assert "shell" not in widgets[0]
    assert widgets[1]["kind_specific"]["source"] == "cpu_percent"


def test_build_mpris_players_snapshot_handles_no_backend() -> None:
    snap = asyncio.run(build_mpris_players_snapshot(None))
    assert snap == {"ok": True, "available": False, "players": []}


def test_build_mpris_players_snapshot_redacts_art_url() -> None:
    from deckd.media import MediaState

    class FakeBackend:
        def __init__(self) -> None:
            self._rows = ["vlc", "spotify"]
            self._urls = {"vlc": "file:///secret/path.jpg", "spotify": None}

        def row_ids(self) -> list[str]:
            return list(self._rows)

        def art_url(self, row_id: str) -> str | None:
            return self._urls.get(row_id)

        async def read_state(self, row_id: str) -> MediaState | None:
            url = self._urls.get(row_id)
            return MediaState(
                available=True,
                stale=False,
                playing=(row_id == "vlc"),
                app_name=row_id,
                desktop_entry=f"{row_id}.desktop",
                art_url=url,
                can_go_next=True,
                can_go_previous=False,
            )

    snap = asyncio.run(build_mpris_players_snapshot(FakeBackend()))
    assert snap["available"] is True
    assert {p["row_id"] for p in snap["players"]} == {"vlc", "spotify"}
    # Per-row capability / playback / identity fields populated.
    by_row = {p["row_id"]: p for p in snap["players"]}
    assert by_row["vlc"]["has_art"] is True
    assert by_row["vlc"]["can_go_next"] is True
    assert by_row["vlc"]["can_go_previous"] is False
    assert by_row["vlc"]["playing"] is True
    assert by_row["vlc"]["app_name"] == "vlc"
    assert by_row["vlc"]["desktop_entry"] == "vlc.desktop"
    assert by_row["spotify"]["has_art"] is False
    # The raw URL must never appear in the snapshot — clients
    # resolve art through ``/mpris/{row}/art`` instead.
    raw = json.dumps(snap)
    assert "secret/path.jpg" not in raw
    assert "art_url" not in snap["players"][0]


def test_build_diag_snapshot_omits_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """The snapshot must never echo the shared password even by accident."""

    class _FakeServer:
        host = "127.0.0.1"
        port = 8765
        layouts_dir = type("P", (), {"__str__": lambda self: "/layouts"})()
        overlay_dir = None
        password = "topsecret"
        layouts = type(
            "S",
            (),
            {"layouts": []},
        )()
        _current_app_id = "default"
        _current_layout = type("L", (), {"id": "default"})()
        _current_error = None
        _sessions: set = set()
        _subscribed_sources: set = set()
        sensors = None
        focus_backend = None
        scroll = type(
            "SC",
            (),
            {"_momentum_friction": 0.9, "_momentum_cutoff": 20, "_momentum_tasks": {}},
        )()
        mpris = None
        _focus_task = None
        _layouts_task = None
        _sensor_task = None
        _media_task = None
        _focus_platform = None
        _last_focus = None
        _focus_started_ok = None
        key_sink = type("KS", (), {})()  # has no _device → fallback

    snap = asyncio.run(build_diag_snapshot(server=_FakeServer(), started_at=0.0))
    raw = json.dumps(snap)
    assert "topsecret" not in raw
    assert "auth" in snap
    assert snap["auth"]["enabled"] is True
    assert "password" not in snap["auth"]


# ---------------------------------------------------------------------------
# JSON logging formatter
# ---------------------------------------------------------------------------


def test_json_formatter_emits_one_object_per_record() -> None:
    fmt = JsonFormatter()
    record = logging.LogRecord(
        "deckd.test",
        logging.INFO,
        "fn",
        10,
        "hello %s",
        ("world",),
        None,
    )
    out = fmt.format(record)
    payload = json.loads(out)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "deckd.test"
    assert payload["msg"] == "hello world"
    assert isinstance(payload["ts"], float)


def test_json_formatter_includes_exception() -> None:
    fmt = JsonFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = logging.LogRecord(
            "deckd.test",
            logging.ERROR,
            "fn",
            10,
            "explosion",
            None,
            exc_info=sys.exc_info(),
        )
        out = fmt.format(record)
    payload = json.loads(out)
    assert "exc" in payload
    assert "RuntimeError: boom" in payload["exc"]


def test_setup_logging_installs_json_formatter() -> None:
    stream = io.StringIO()
    setup_logging(level=logging.INFO, fmt="json", stream=stream)
    logging.getLogger("deckd.demo").info("payload=%d", 42)
    line = stream.getvalue().strip()
    payload = json.loads(line)
    assert payload["msg"] == "payload=42"
    # Switch back to text and confirm we re-render the human form.
    stream = io.StringIO()
    setup_logging(level=logging.INFO, fmt="text", stream=stream)
    logging.getLogger("deckd.demo").info("payload=%d", 42)
    line = stream.getvalue().strip()
    assert "payload=42" in line
    assert "INFO" in line


def test_setup_logging_does_not_leak_old_handlers() -> None:
    """Calling ``setup_logging`` twice replaces (not duplicates) handlers."""
    setup_logging(level=logging.INFO, fmt="text")
    after_first = len(logging.getLogger().handlers)
    setup_logging(level=logging.INFO, fmt="text")
    after_second = len(logging.getLogger().handlers)
    assert after_second == after_first


# ---------------------------------------------------------------------------
# Event bus + correlation scope
# ---------------------------------------------------------------------------


def test_event_bus_dispatches_to_subscribers() -> None:
    from deckd.events import DiagnosticEvent, EventBus

    async def scenario() -> list[DiagnosticEvent]:
        bus: EventBus = EventBus()
        seen: list[DiagnosticEvent] = []

        async def collect(ev: DiagnosticEvent) -> None:
            seen.append(ev)

        bus.subscribe(collect)
        event = DiagnosticEvent(name="focus_change", ts=0.0, data={"a": 1})
        await bus.emit(event)
        return seen

    seen = asyncio.run(scenario())
    assert len(seen) == 1
    assert seen[0].name == "focus_change"


def test_event_bus_subscriber_failure_does_not_kill_bus() -> None:
    from deckd.events import DiagnosticEvent, EventBus

    async def scenario() -> int:
        bus: EventBus = EventBus()
        second_calls = 0

        async def broken(_: DiagnosticEvent) -> None:
            raise RuntimeError("subscriber broken")

        async def working(_: DiagnosticEvent) -> None:
            nonlocal second_calls
            second_calls += 1

        bus.subscribe(broken)
        bus.subscribe(working)
        await bus.emit(DiagnosticEvent(name="x", ts=0.0, data={}))
        await bus.emit(DiagnosticEvent(name="x", ts=0.0, data={}))
        # Subscribers run as their own tasks now (fire-and-forget);
        # yield to the loop until both emits have run before we
        # count.
        for _ in range(20):
            if second_calls >= 2:
                break
            await asyncio.sleep(0)
        return second_calls

    assert asyncio.run(scenario()) == 2


def test_correlation_scope_is_task_local() -> None:
    from deckd.events import (
        correlation_id_var,
        correlation_scope,
        current_correlation_id,
    )

    async def child() -> str | None:
        with correlation_scope("inner"):
            await asyncio.sleep(0)
            return current_correlation_id()

    async def scenario() -> tuple[str | None, str | None]:
        with correlation_scope("outer"):
            outer_id = current_correlation_id()
            child_id = await asyncio.create_task(child())
            return outer_id, child_id

    outer, inner = asyncio.run(scenario())
    assert outer == "outer"
    assert inner == "inner"
    assert correlation_id_var.get() is None