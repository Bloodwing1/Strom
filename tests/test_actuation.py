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
    ActuationPlan,
    ActuationSegment,
    MaxOnWatchdog,
    execute_plan,
    plan_from_schedule,
    resolve_actuation,
)
from strom.errors import DeviceError, InvalidScheduleError

from .conftest import make_schedule

INTERVAL = 3600.0


class TestResolveActuation:
    def test_zero_is_never_on(self):
        plan = resolve_actuation(0.0, INTERVAL)
        assert plan.total_on_seconds == 0.0
        assert all(s.on is False for s in plan.segments)

    def test_one_is_full_interval(self):
        plan = resolve_actuation(1.0, INTERVAL)
        assert plan.total_on_seconds == INTERVAL
        assert [s.on for s in plan.segments] == [True]

    def test_fractional_is_exact_portion_of_interval(self):
        plan = resolve_actuation(0.25, INTERVAL)
        assert plan.total_on_seconds == pytest.approx(900.0)
        assert sum(s.seconds for s in plan.segments) == pytest.approx(INTERVAL)
        assert [s.on for s in plan.segments] == [True, False]

    def test_tiny_positive_is_bounded_not_full_on(self):
        plan = resolve_actuation(1e-9, INTERVAL)
        assert plan.total_on_seconds == pytest.approx(MIN_PULSE_SECONDS)
        assert plan.total_on_seconds < INTERVAL

    def test_segments_cover_interval_exactly(self):
        for duty in (0.1, 0.4, 0.9):
            plan = resolve_actuation(duty, INTERVAL)
            assert sum(s.seconds for s in plan.segments) == pytest.approx(INTERVAL)

    def test_sub_second_off_segment_still_covers_interval(self):
        # Duty just below 1.0: the remainder is under one second but the
        # plan must still cover the whole interval and end with OFF.
        plan = resolve_actuation(3599.5 / INTERVAL, INTERVAL)
        assert sum(s.seconds for s in plan.segments) == pytest.approx(INTERVAL)
        assert plan.segments[-1].on is False
        assert plan.segments[-1].seconds == pytest.approx(0.5)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_rejected(self, bad):
        with pytest.raises(InvalidScheduleError):
            resolve_actuation(bad, INTERVAL)

    @pytest.mark.parametrize("bad", [-0.1, 1.5, -1.0])
    def test_out_of_range_rejected(self, bad):
        with pytest.raises(InvalidScheduleError):
            resolve_actuation(bad, INTERVAL)

    @pytest.mark.parametrize("seconds", [0., -1., float("nan"), float("inf")])
    def test_invalid_interval_rejected(self, seconds):
        with pytest.raises(InvalidScheduleError):
            resolve_actuation(0.5, seconds)

    @pytest.mark.parametrize("seconds", [0., -1., float("nan"), float("inf")])
    def test_invalid_minimum_pulse_rejected(self, seconds):
        with pytest.raises(InvalidScheduleError):
            resolve_actuation(0.5, INTERVAL, seconds)


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

    def test_index_equal_to_length_rejected(self):
        with pytest.raises(InvalidScheduleError):
            plan_from_schedule(make_schedule([0.5]), INTERVAL, index=1)


class TestExecutePlan:
    async def test_commands_follow_plan_order(self, plug, clock):
        plan = resolve_actuation(0.5, INTERVAL)
        await execute_plan(plug, plan, clock)
        assert plug.calls == ["turn_on", "update", "turn_off", "update"]
        assert plug.is_on is False
        assert clock.sleeps == [1800.0, 1800.0]

    async def test_zero_plan_only_switches_off(self, plug, clock):
        plan = resolve_actuation(0.0, INTERVAL)
        await execute_plan(plug, plan, clock)
        assert plug.calls == ["turn_off", "update"]
        assert clock.sleeps == [INTERVAL]

    async def test_executor_is_time_exact(self, plug, clock):
        await execute_plan(plug, resolve_actuation(0.25, INTERVAL), clock)
        assert clock.now == pytest.approx(INTERVAL)

    async def test_command_delays_use_deadlines_and_measured_on_time(self, plug, clock):
        original_on, original_off, original_update = plug.turn_on, plug.turn_off, plug.update

        async def delayed_on():
            clock.advance(10)
            await original_on()

        async def delayed_off():
            clock.advance(20)
            await original_off()

        async def delayed_update():
            clock.advance(5)
            await original_update()

        plug.turn_on, plug.turn_off, plug.update = delayed_on, delayed_off, delayed_update
        actual = await execute_plan(plug, resolve_actuation(.5, 120), clock)
        assert clock.sleeps == [45, 35]
        assert actual.interval_seconds == 120
        assert actual.total_on_seconds == 85  # ON request through confirmed OFF
        assert sum(s.seconds for s in actual.segments) == 120

    async def test_expired_pulse_is_not_started(self, plug, clock):
        original_off = plug.turn_off

        async def delayed_off():
            clock.advance(25)
            await original_off()

        plug.turn_off = delayed_off
        actual = await execute_plan(plug, ActuationPlan((
            ActuationSegment(False, 10), ActuationSegment(True, 10),
            ActuationSegment(False, 10),
        ), 30), clock)
        assert "turn_on" not in plug.calls
        assert actual.interval_seconds == 50
        assert actual.total_on_seconds == 25  # initial state was unknown

    @pytest.mark.parametrize("reported", [True, None])
    async def test_unverified_off_retains_timer(self, plug, clock, reported):
        async def ignored_off():
            plug.is_on = reported

        plug.turn_off = ignored_off
        watchdog = MaxOnWatchdog(plug, clock=clock)
        with pytest.raises(DeviceError, match="confirm.*OFF"):
            await execute_plan(plug, resolve_actuation(.5, 120), clock, watchdog)
        assert watchdog.on_seconds_elapsed == 60
        clock.advance(10)
        assert watchdog.on_seconds_elapsed == 70

    async def test_failed_off_update_retains_timer(self, plug, clock):
        watchdog = MaxOnWatchdog(plug, clock=clock)
        watchdog.notify_on()
        clock.advance(10)
        plug.fail_on = lambda op: RuntimeError("offline") if op == "update" else None
        with pytest.raises(RuntimeError):
            await execute_plan(plug, resolve_actuation(0., 120), clock, watchdog)
        assert watchdog.on_seconds_elapsed == 10

    async def test_ignored_on_does_not_return_a_nominal_estimate(self, plug, clock):
        plug.is_on = False

        async def ignored_on():
            pass

        plug.turn_on = ignored_on
        with pytest.raises(DeviceError, match="confirm.*ON"):
            await execute_plan(plug, resolve_actuation(.5, 120), clock)
        assert clock.sleeps == []

    async def test_watchdog_intervention_discards_execution_estimate(self, plug, clock):
        original_sleep = clock.sleep
        watchdog = MaxOnWatchdog(plug, max_on_seconds=10, clock=clock, poll_seconds=10)

        async def sleep_with_intervention(seconds):
            await original_sleep(seconds)
            watchdog.tripped = True
            await plug.turn_off()
            await plug.update()
            watchdog.notify_off()

        clock.sleep = sleep_with_intervention
        with pytest.raises(DeviceError, match="watchdog interrupted"):
            await execute_plan(plug, resolve_actuation(.5, 120), clock, watchdog)

    async def test_hung_command_times_out_without_clearing_timer(self, plug, monkeypatch):
        from strom.control import SystemClock
        import strom.control as control

        monkeypatch.setattr(control, "COMMAND_TIMEOUT_SECONDS", .01)
        clock = SystemClock()
        watchdog = MaxOnWatchdog(plug, clock=clock)

        async def hung_on():
            await asyncio.Event().wait()

        plug.turn_on = hung_on
        with pytest.raises(TimeoutError):
            await execute_plan(plug, resolve_actuation(1., 60), clock, watchdog)
        assert watchdog.on_seconds_elapsed > 0


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

    @pytest.mark.parametrize("reported", [True, None])
    async def test_ignored_off_is_retried_without_resetting_timer(self, plug, clock, reported):
        attempts = 0
        original_off = plug.turn_off

        async def ignored_once():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                plug.is_on = reported
            else:
                await original_off()

        plug.turn_off = ignored_once
        watchdog = MaxOnWatchdog(plug, max_on_seconds=10, clock=clock, poll_seconds=10)
        watchdog.notify_on()
        watchdog.start()
        try:
            await self._poll(clock, 2)
            assert attempts == 1
            assert watchdog.on_seconds_elapsed >= 10
            await self._poll(clock, 4)
            assert attempts == 2
            assert plug.is_on is False
            assert watchdog.on_seconds_elapsed == 0
        finally:
            await watchdog.stop()

    async def test_failed_update_is_retried_without_resetting_timer(self, plug, clock):
        updates = 0
        original_update = plug.update

        async def flaky_update():
            nonlocal updates
            updates += 1
            if updates == 1:
                raise ConnectionError("unverified")
            await original_update()

        plug.update = flaky_update
        watchdog = MaxOnWatchdog(plug, max_on_seconds=10, clock=clock, poll_seconds=10)
        watchdog.notify_on()
        watchdog.start()
        try:
            await self._poll(clock, 2)
            assert updates == 1
            assert watchdog.on_seconds_elapsed >= 10
            await self._poll(clock, 4)
            assert updates == 2
            assert watchdog.on_seconds_elapsed == 0
        finally:
            await watchdog.stop()

    async def test_stop_cancels_cleanly(self, plug, clock):
        watchdog = MaxOnWatchdog(plug, max_on_seconds=10.0, clock=clock,
                                 poll_seconds=1.0)
        watchdog.start()
        await watchdog.stop()
        assert watchdog._task is None

    async def test_failed_off_is_retried_on_the_next_poll(self, plug, clock):
        attempts = 0
        original_off = plug.turn_off

        async def flaky_off():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("temporary outage")
            await original_off()

        plug.turn_off = flaky_off
        plug.is_on = True
        watchdog = MaxOnWatchdog(plug, max_on_seconds=10, clock=clock, poll_seconds=10)
        watchdog.notify_on()
        watchdog.start()
        try:
            await self._poll(clock, 6)
            assert attempts == 2
            assert plug.is_on is False
        finally:
            await watchdog.stop()
