"""Deterministic tests for the actuation policy (audit issue 31).

Covers: 0, 1, fractional, tiny-positive, NaN, +inf, -inf, out-of-range,
empty schedules, failed (NaN) schedules, plan execution order, and the
independent maximum-on watchdog.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from strom.control import (
    MIN_PULSE_SECONDS,
    MaxOnWatchdog,
    execute_plan,
    plan_from_schedule,
    resolve_actuation,
)
from strom.errors import InvalidScheduleError

from .conftest import make_schedule

INTERVAL = 3600.0


class TestResolveActuation:
    def test_zero_is_never_on(self):
        plan = resolve_actuation(0.0, INTERVAL)
        assert plan.total_on_seconds == 0.0
        assert all(not s.on for s in plan.segments)

    def test_one_is_full_interval(self):
        plan = resolve_actuation(1.0, INTERVAL)
        assert plan.total_on_seconds == INTERVAL
        assert [s.on for s in plan.segments] == [True]

    def test_fractional_is_exact_portion_of_interval(self):
        plan = resolve_actuation(0.25, INTERVAL)
        assert plan.total_on_seconds == pytest.approx(900.0)
        assert plan.total_seconds == pytest.approx(INTERVAL)
        assert [s.on for s in plan.segments] == [True, False]

    def test_tiny_positive_is_bounded_not_full_on(self):
        plan = resolve_actuation(1e-9, INTERVAL)
        assert plan.total_on_seconds == pytest.approx(MIN_PULSE_SECONDS)
        assert plan.total_on_seconds < INTERVAL

    def test_segments_cover_interval_exactly(self):
        for duty in (0.1, 0.4, 0.9):
            plan = resolve_actuation(duty, INTERVAL)
            assert plan.total_seconds == pytest.approx(INTERVAL)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_rejected(self, bad):
        with pytest.raises(InvalidScheduleError):
            resolve_actuation(bad, INTERVAL)

    @pytest.mark.parametrize("bad", [-0.1, 1.5, -1.0])
    def test_out_of_range_rejected(self, bad):
        with pytest.raises(InvalidScheduleError):
            resolve_actuation(bad, INTERVAL)

    def test_invalid_interval_rejected(self):
        with pytest.raises(InvalidScheduleError):
            resolve_actuation(0.5, 0.0)


class TestPlanFromSchedule:
    def test_valid_schedule(self):
        plan = plan_from_schedule(make_schedule([0.0, 0.5]), INTERVAL, index=1)
        assert plan.total_on_seconds == pytest.approx(1800.0)

    def test_empty_schedule_rejected(self):
        with pytest.raises(InvalidScheduleError):
            plan_from_schedule(make_schedule([]), INTERVAL)

    def test_missing_column_rejected(self):
        df = make_schedule([0.5]).drop(columns=["HeaterOutput"])
        with pytest.raises(InvalidScheduleError):
            plan_from_schedule(df, INTERVAL)

    def test_nan_schedule_rejected(self):
        with pytest.raises(InvalidScheduleError):
            plan_from_schedule(make_schedule([np.nan]), INTERVAL)

    def test_none_schedule_rejected(self):
        with pytest.raises(InvalidScheduleError):
            plan_from_schedule(None, INTERVAL)

    def test_index_out_of_range_rejected(self):
        with pytest.raises(InvalidScheduleError):
            plan_from_schedule(make_schedule([0.5]), INTERVAL, index=5)


class TestExecutePlan:
    async def test_commands_follow_plan_order(self, plug, clock):
        plan = resolve_actuation(0.5, INTERVAL)
        await execute_plan(plug, plan, clock)
        assert plug.calls == ["turn_on", "turn_off"]
        assert plug.is_on is False
        assert clock.sleeps == [1800.0, 1800.0]

    async def test_zero_plan_only_switches_off(self, plug, clock):
        plan = resolve_actuation(0.0, INTERVAL)
        await execute_plan(plug, plan, clock)
        assert plug.calls == ["turn_off"]
        assert clock.sleeps == [INTERVAL]

    async def test_executor_is_time_exact(self, plug, clock):
        await execute_plan(plug, resolve_actuation(0.25, INTERVAL), clock)
        assert clock.now == pytest.approx(INTERVAL)


class TestMaxOnWatchdog:
    @staticmethod
    async def _poll(clock, times: int) -> None:
        """Give the watchdog loop ``times`` poll cycles.

        ManualClock.sleep advances time instantly, so each yield of control
        lets the watchdog complete one poll interval.
        """
        for _ in range(times):
            await asyncio.sleep(0)

    async def test_forces_off_after_max_on(self, plug, clock):
        watchdog = MaxOnWatchdog(plug, max_on_seconds=100.0, clock=clock,
                                 poll_seconds=10.0)
        watchdog.start()
        try:
            watchdog.notify_on()
            await self._poll(clock, 15)
            assert "turn_off" in plug.calls
            assert plug.is_on is False
            assert watchdog.on_seconds_elapsed == 0.0
        finally:
            await watchdog.stop()

    async def test_no_force_off_below_limit(self, plug, clock):
        watchdog = MaxOnWatchdog(plug, max_on_seconds=100.0, clock=clock,
                                 poll_seconds=10.0)
        watchdog.start()
        try:
            watchdog.notify_on()
            await self._poll(clock, 5)
            assert "turn_off" not in plug.calls
            assert watchdog.on_seconds_elapsed == pytest.approx(50.0)
        finally:
            await watchdog.stop()

    async def test_notify_off_resets_timer(self, plug, clock):
        watchdog = MaxOnWatchdog(plug, max_on_seconds=100.0, clock=clock,
                                 poll_seconds=10.0)
        watchdog.start()
        try:
            watchdog.notify_on()
            await self._poll(clock, 5)
            watchdog.notify_off()
            await self._poll(clock, 8)
            assert "turn_off" not in plug.calls
        finally:
            await watchdog.stop()

    async def test_force_off_when_controller_silent(self, plug, clock):
        """The watchdog never consults the optimizer: ON state times out."""
        watchdog = MaxOnWatchdog(plug, max_on_seconds=100.0, clock=clock,
                                 poll_seconds=10.0)
        watchdog.start()
        try:
            watchdog.notify_on()  # controller crashed right after switching on
            await self._poll(clock, 15)
            assert plug.is_on is False
        finally:
            await watchdog.stop()

    async def test_stop_cancels_cleanly(self, plug, clock):
        watchdog = MaxOnWatchdog(plug, max_on_seconds=10.0, clock=clock,
                                 poll_seconds=1.0)
        watchdog.start()
        await watchdog.stop()
        assert not watchdog.is_running
