"""Tests for the psutil-backed sensor sources and the ``SensorManager``
abstraction.

These exercise the cross-platform sources the daemon ships by
default. The Linux-specific ``/sys/class/thermal`` reader and the
macOS shell-out readers (``osx-cpu-temp`` / ``istats``) have been
removed — Apple Silicon doesn't expose CPU temperature in any
unprivileged, documented way, so we standardise on metrics psutil
covers identically on every platform.
"""
from __future__ import annotations

import asyncio

import pytest

from deckd.platform import (
    PsutilCpuPercentSensorSource,
    PsutilMemoryPercentSensorSource,
    SensorManager,
    SensorReading,
    SensorSource,
)


class _FixedSource(SensorSource):
    """Deterministic sensor for tests — always returns the same reading."""

    name = "test_fixed"
    unit = "x"
    interval_s = 0.01

    def __init__(self, value: float, available: bool = True) -> None:
        self._value = value
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def read(self) -> SensorReading:
        return SensorReading(source=self.name, value=self._value, unit=self.unit)


class _FlappingSource(SensorSource):
    """Returns alternating values so we can see push-on-change filtering."""

    name = "test_flap"
    unit = "v"
    interval_s = 0.01

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._i = 0

    def read(self) -> SensorReading:
        v = self._values[self._i % len(self._values)]
        self._i += 1
        return SensorReading(source=self.name, value=v, unit=self.unit)


class _FailingSource(SensorSource):
    name = "test_fail"
    unit = "?"
    interval_s = 0.01

    def read(self) -> SensorReading | None:
        return None


# ---------------------------------------------------------------------------
# SensorManager behaviour (regression-tested from the original
# Linux-thermal-zone implementation; the manager itself didn't change)
# ---------------------------------------------------------------------------


async def test_manager_polls_subscribed_source() -> None:
    src = _FixedSource(42.0)
    mgr = SensorManager([src])
    mgr.subscribe("test_fixed")
    for _ in range(20):
        latest = mgr.latest("test_fixed")
        if latest is not None:
            break
        await asyncio.sleep(src.interval_s)
    assert latest is not None
    assert latest.value == 42.0
    assert latest.unit == "x"
    assert latest.stale is False
    mgr.unsubscribe("test_fixed")


async def test_manager_drops_subscriptions_on_zero_refcount() -> None:
    src = _FixedSource(1.0)
    mgr = SensorManager([src])
    mgr.subscribe("test_fixed")
    assert "test_fixed" in mgr._tasks  # type: ignore[attr-defined]
    mgr.unsubscribe("test_fixed")
    await asyncio.sleep(0)
    assert "test_fixed" not in mgr._tasks  # type: ignore[attr-defined]


async def test_manager_marks_reading_stale_when_source_returns_none() -> None:
    src = _FailingSource()
    mgr = SensorManager([src])
    mgr._last["test_fail"] = SensorReading(source="test_fail", value=10, unit="?")  # type: ignore[attr-defined]
    mgr.subscribe("test_fail")
    await asyncio.sleep(src.interval_s * 2)
    latest = mgr.latest("test_fail")
    assert latest is not None
    assert latest.value == 10
    assert latest.stale is True
    mgr.unsubscribe("test_fail")


async def test_manager_refcount_is_balanced() -> None:
    src = _FixedSource(7.0)
    mgr = SensorManager([src])
    mgr.subscribe("test_fixed")
    mgr.subscribe("test_fixed")
    mgr.subscribe("test_fixed")
    mgr.unsubscribe("test_fixed")
    mgr.unsubscribe("test_fixed")
    mgr.unsubscribe("test_fixed")
    assert mgr._subscribers["test_fixed"] == 0  # type: ignore[attr-defined]
    mgr.unsubscribe("test_fixed")
    assert mgr._subscribers["test_fixed"] == 0  # type: ignore[attr-defined]


async def test_manager_unknown_source_is_ignored() -> None:
    mgr = SensorManager([_FixedSource(1.0)])
    mgr.subscribe("does_not_exist")
    assert mgr._tasks == {}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# psutil-backed sources (the actual ship targets)
# ---------------------------------------------------------------------------


def test_psutil_cpu_percent_source_is_always_available() -> None:
    # psutil ships wheels for every platform we support, so the
    # source never reports unavailable on a working install.
    src = PsutilCpuPercentSensorSource()
    assert src.is_available() is True


def test_psutil_memory_percent_source_is_always_available() -> None:
    src = PsutilMemoryPercentSensorSource()
    assert src.is_available() is True


def test_psutil_cpu_percent_source_returns_reading_in_zero_to_hundred() -> None:
    # First ``cpu_percent(interval=None)`` returns 0.0 (no baseline);
    # we accept that as a valid reading rather than a None.
    src = PsutilCpuPercentSensorSource()
    reading = src.read()
    assert reading is not None
    assert reading.source == "cpu_percent"
    assert reading.unit == "%"
    assert reading.value == pytest.approx(0.0) or reading.value >= 0


def test_psutil_cpu_percent_source_returns_subsequent_reading() -> None:
    # After the first call the manager has a baseline; the second
    # call returns a delta. We don't assert it's nonzero — could be
    # 0.0 on an idle box — but it must be a valid number.
    src = PsutilCpuPercentSensorSource()
    src.read()  # establish baseline
    reading = src.read()
    assert reading is not None
    assert 0.0 <= reading.value <= 100.0


def test_psutil_memory_percent_source_returns_reading_in_zero_to_hundred() -> None:
    src = PsutilMemoryPercentSensorSource()
    reading = src.read()
    assert reading is not None
    assert reading.source == "mem_percent"
    assert reading.unit == "%"
    assert 0.0 <= reading.value <= 100.0


def test_psutil_sources_have_one_second_poll_interval() -> None:
    # The meter cell renders a smooth transition animation on every
    # push; faster than 1s looks jittery, slower than 1s feels
    # dead. Pinned here so a future refactor doesn't silently change
    # the cadence.
    assert PsutilCpuPercentSensorSource.interval_s == 1.0
    assert PsutilMemoryPercentSensorSource.interval_s == 1.0


def test_default_sensor_manager_registers_psutil_sources() -> None:
    # The default factory must produce the cross-platform set so a
    # fresh daemon on a fresh box has working meters without any
    # extra setup. Pinned: if anyone adds a Linux-only or macOS-only
    # source to the default list, this test forces them to update
    # the cross-platform contract too.
    from deckd.platform import default_sensor_manager

    mgr = default_sensor_manager()
    assert "cpu_percent" in mgr.sources
    assert "mem_percent" in mgr.sources


def test_default_sensor_manager_contains_no_legacy_temperature_sources() -> None:
    # Regression guard: the old ``cpu_temp`` source (Linux thermal
    # zone + macOS shell-out) used to ship by default. It's gone
    # now — Apple Silicon can't read it, the macOS shell-out
    # helpers are unmaintained, and psutil covers the metrics we
    # actually want. This test pins the removal so a future "let's
    # add cpu_temp back" PR has to think twice about it.
    from deckd.platform import default_sensor_manager

    mgr = default_sensor_manager()
    assert "cpu_temp" not in mgr.sources
