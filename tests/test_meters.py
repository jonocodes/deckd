"""Tests for the meter widget schema (issue #40), the
``widget_update`` protocol message, and the server-side sensor pump."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import pytest
import websockets
from aiohttp.test_utils import TestServer
from pydantic import ValidationError

from conftest import LAYOUTS_DIR, ServerHandle, make_test_server
from deckd.platform import SensorManager, SensorReading, SensorSource
from deckd.protocol import WidgetUpdateMessage


class _CpuSource(SensorSource):
    """Test sensor: returns the value the test set.

    Models ``cpu_percent`` — the daemon's primary live-stat source
    after we dropped ``cpu_temp`` because Apple Silicon has no
    stable unprivileged temperature API. The unit is ``%`` rather
    than ``°C``; tests that don't care about the unit just assert
    on the value.
    """

    name = "cpu_percent"
    unit = "%"
    interval_s = 0.01

    def __init__(self, initial: float = 42.0) -> None:
        self.value = initial

    def read(self) -> SensorReading:
        return SensorReading(source=self.name, value=self.value, unit=self.unit)


# ---------------------------------------------------------------------------
# Protocol message shape
# ---------------------------------------------------------------------------


def test_widget_update_message_roundtrips() -> None:
    msg = WidgetUpdateMessage(
        type="widget_update", id="cpu", source="cpu_percent", value=58.4, unit="%"
    )
    data = json.loads(json.dumps(msg.model_dump()))
    assert data["type"] == "widget_update"
    assert data["id"] == "cpu"
    assert data["source"] == "cpu_percent"
    assert data["value"] == 58.4
    assert data["unit"] == "%"
    assert data["stale"] is False


def test_widget_update_message_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        WidgetUpdateMessage(type="nope", id="x", source="s", value=0, unit="")  # type: ignore[arg-type]


def test_widget_update_message_default_stale_false() -> None:
    msg = WidgetUpdateMessage(type="widget_update", id="x", source="s", value=0, unit="")
    assert msg.stale is False


# ---------------------------------------------------------------------------
# Layout schema: meter widget
# ---------------------------------------------------------------------------


def test_meter_widget_loads_with_source() -> None:
    from deckd.layouts import load_layout

    yaml = """
match:
  - default
widgets:
  - id: cpu
    kind: meter
    source: cpu_percent
    min: 0
    max: 100
    grid: [0, 0, 1, 1]
"""
    p = Path("/tmp/_meter_layout.yaml")
    p.write_text(yaml)
    try:
        layout = load_layout(p)
        w = layout.widgets[0]
        assert w.kind == "meter"
        assert w.source == "cpu_percent"
        assert w.min == 0
        assert w.max == 100
    finally:
        p.unlink()


def test_meter_widget_without_source_is_rejected() -> None:
    from deckd.layouts import load_layout

    yaml = """
match:
  - default
widgets:
  - id: cpu
    kind: meter
    grid: [0, 0, 1, 1]
"""
    p = Path("/tmp/_meter_layout_bad.yaml")
    p.write_text(yaml)
    try:
        with pytest.raises(SystemExit):
            load_layout(p)
    finally:
        p.unlink()


def test_meter_widget_with_inverted_range_is_rejected() -> None:
    from deckd.layouts import load_layout

    yaml = """
match:
  - default
widgets:
  - id: cpu
    kind: meter
    source: cpu_percent
    min: 100
    max: 50
    grid: [0, 0, 1, 1]
"""
    p = Path("/tmp/_meter_layout_bad2.yaml")
    p.write_text(yaml)
    try:
        with pytest.raises(SystemExit):
            load_layout(p)
    finally:
        p.unlink()


# ---------------------------------------------------------------------------
# Server pump: subscribe/unsubscribe + push
# ---------------------------------------------------------------------------


@asynccontextmanager
async def ws_connected_no_auth(port: int) -> AsyncIterator[websockets.WebSocketClientProtocol]:
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
        yield ws


@pytest.fixture
def meter_layout(tmp_path: Path) -> Path:
    """A default layout with a meter bound to cpu_percent."""
    p = tmp_path / "default.yaml"
    p.write_text(
        """
match:
  - default
widgets:
  - id: cpu
    kind: meter
    source: cpu_percent
    min: 0
    max: 100
    grid: [0, 0, 1, 1]
"""
    )
    return tmp_path


async def test_server_pumps_widget_update_to_session(meter_layout: Path) -> None:
    src = _CpuSource(initial=42.0)
    mgr = SensorManager([src])
    server, _, _, _ = make_test_server(layouts_dir=meter_layout, password=None)
    server.sensors = mgr
    # Re-sync now that the manager is installed (make_test_server
    # builds the Server before we swap sensors in).
    server._sync_sensor_subscriptions()  # type: ignore[attr-defined]
    server.start_sensor_pump()

    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        # Connect a client; the server's initial layout push should
        # include the meter widget, and the sensor pump should send a
        # widget_update frame shortly after.
        async with ws_connected_no_auth(test_server.port) as ws:
            initial = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            assert initial["type"] == "layout"
            assert any(
                w["kind"] == "meter" and w.get("source") == "cpu_percent"
                for w in initial["widgets"]
            )
            # Wait for the pump to push at least one update.
            update = None
            for _ in range(50):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw)
                if msg.get("type") == "widget_update":
                    update = msg
                    break
            assert update is not None, "no widget_update frame received"
            assert update["id"] == "cpu"
            assert update["source"] == "cpu_percent"
            assert update["unit"] == "%"
            assert update["value"] == pytest.approx(42.0)
    finally:
        await server.stop()
        await test_server.close()


async def test_server_pump_skips_unknown_sources(meter_layout: Path) -> None:
    """A meter bound to an unregistered source must not crash the pump."""
    src = _CpuSource(initial=10.0)
    mgr = SensorManager([src])
    server, _, _, _ = make_test_server(layouts_dir=meter_layout, password=None)
    server.sensors = mgr
    # Build a manager that does NOT have cpu_percent — the meter in the
    # layout references it but the manager only carries an unrelated
    # source. Subscriptions get filtered out by _active_sources; the
    # pump should run idle.
    unrelated = SensorSource()
    unrelated.name = "not_cpu"
    unrelated.unit = ""
    mgr2 = SensorManager([unrelated])
    server.sensors = mgr2
    server._sync_sensor_subscriptions()  # type: ignore[attr-defined]
    server.start_sensor_pump()

    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        async with ws_connected_no_auth(test_server.port) as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)  # initial layout
            # The pump polls at 100ms; wait three intervals then
            # confirm the test is still alive (no exception in the
            # pump loop) and no spam frames are pushed.
            await asyncio.sleep(0.4)
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.1)
            except asyncio.TimeoutError:
                raw = None
            assert raw is None or json.loads(raw).get("type") != "widget_update"
    finally:
        await server.stop()
        await test_server.close()


# ---------------------------------------------------------------------------
# stats widget (multi-source, bar-less)
# ---------------------------------------------------------------------------


class _MemSource(SensorSource):
    """Test sensor modelling ``mem_percent``."""

    name = "mem_percent"
    unit = "%"
    interval_s = 0.01

    def __init__(self, initial: float = 41.0) -> None:
        self.value = initial

    def read(self) -> SensorReading:
        return SensorReading(source=self.name, value=self.value, unit=self.unit)


def test_stats_widget_loads_with_metrics(tmp_path: Path) -> None:
    from deckd.layouts import load_layouts

    (tmp_path / "default.yaml").write_text(
        """
match:
  - default
widgets:
  - id: system
    kind: stats
    label: System
    grid: [0, 0, 1, 1]
    metrics:
      - source: cpu_percent
        label: CPU
      - source: mem_percent
"""
    )
    w = next(w for w in load_layouts(tmp_path)["default"].widgets if w.kind == "stats")
    assert [m.source for m in w.metrics] == ["cpu_percent", "mem_percent"]
    assert w.metrics[0].label == "CPU"
    assert w.metrics[1].label is None  # client derives it


def test_stats_widget_without_metrics_is_rejected(tmp_path: Path) -> None:
    from deckd.layouts import load_layouts

    (tmp_path / "default.yaml").write_text(
        """
match:
  - default
widgets:
  - id: system
    kind: stats
    grid: [0, 0, 1, 1]
"""
    )
    with pytest.raises(SystemExit):
        load_layouts(tmp_path)


@pytest.fixture
def stats_layout(tmp_path: Path) -> Path:
    """A default layout with a stats widget bound to two sources."""
    (tmp_path / "default.yaml").write_text(
        """
match:
  - default
widgets:
  - id: system
    kind: stats
    label: System
    grid: [0, 0, 1, 1]
    metrics:
      - source: cpu_percent
        label: CPU
      - source: mem_percent
        label: MEM
"""
    )
    return tmp_path


async def test_stats_widget_pumps_all_its_sources(stats_layout: Path) -> None:
    """The pump subscribes to every source a stats widget references and
    pushes a widget_update (carrying the source) for each."""
    mgr = SensorManager([_CpuSource(initial=58.0), _MemSource(initial=41.0)])
    server, _, _, _ = make_test_server(layouts_dir=stats_layout, password=None)
    server.sensors = mgr
    server._sync_sensor_subscriptions()  # type: ignore[attr-defined]
    server.start_sensor_pump()

    test_server = TestServer(server.app, host="127.0.0.1")
    await test_server.start_server()
    try:
        async with ws_connected_no_auth(test_server.port) as ws:
            initial = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            assert initial["type"] == "layout"
            by_source: dict[str, float] = {}
            for _ in range(80):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw)
                if msg.get("type") == "widget_update":
                    # Frame carries the stats widget id + the specific source.
                    assert msg["id"] == "system"
                    by_source[msg["source"]] = msg["value"]
                if {"cpu_percent", "mem_percent"} <= by_source.keys():
                    break
            assert by_source.get("cpu_percent") == pytest.approx(58.0)
            assert by_source.get("mem_percent") == pytest.approx(41.0)
    finally:
        await server.stop()
        await test_server.close()
