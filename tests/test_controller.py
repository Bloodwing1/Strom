"""Deterministic controller tests (audit issues 31 and 32).

Failure injection covers every stage: discovery, data fetch, optimization,
plan construction, plug commands and state update. Cleanup is asserted to
happen exactly once after every successful discovery.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from strom.controller import ControllerDeps, run_control_cycle
from strom.plug import PlugCredentials
from strom.errors import (
    DeviceError,
    InvalidScheduleError,
    OptimizationError,
    ProviderError,
    SolverError,
)

from .conftest import ManualClock, make_schedule


@pytest.fixture(autouse=True)
def passive_manual_clock_watchdog(monkeypatch):
    import strom.controller as controller

    real_factory = controller._make_watchdog

    def make_watchdog(deps, plug):
        watchdog = real_factory(deps, plug)
        # ManualClock.sleep advances shared time, unlike a real concurrent sleep.
        # Test its polling independently in test_actuation, not as a second clock driver.
        if isinstance(deps.clock, ManualClock):
            monkeypatch.setattr(watchdog, "start", lambda: None)
        return watchdog

    monkeypatch.setattr(controller, "_make_watchdog", make_watchdog)


def _creds(device_ip="1.2.3.4", email="e", password="p"):
    return PlugCredentials(device_ip=device_ip, email=email, password=password)


def make_deps(plug, clock, *, discover=None, fetch=None, optimize=None,
              max_on=3 * 3600.0):
    return ControllerDeps(
        discover=discover or (lambda credentials: _return(plug)),
        fetch_data=fetch or (lambda: make_schedule([0.5])),
        optimize=optimize or (lambda df, house, mode: df),
        clock=clock,
        max_on_seconds=max_on,
        interval_seconds=3600.0,
    )


async def _return(value):
    return value


class TestHappyPath:
    async def test_maximum_on_time_applies_to_each_continuous_pulse(
        self, plug, clock, monkeypatch,
    ):
        import strom.controller as controller
        from strom.optimization_utils import House

        house = House(T_interior_init=18., T_wall_init=18., T_max=18.2)
        frame = make_schedule([.17, 0.], ExteriorTemperature=[5., 5.],
                              InteriorTemperature=[18., 18.])
        deps = make_deps(plug, clock, fetch=lambda: frame, max_on=100)
        watchdog = controller._make_watchdog(deps, plug)
        monkeypatch.setattr(watchdog, "start", lambda: None)
        monkeypatch.setattr(controller, "_make_watchdog", lambda deps, plug: watchdog)
        report = await run_control_cycle(deps, _creds(), house)
        assert report.on_seconds > deps.max_on_seconds
        assert plug.is_on is False
        assert watchdog.on_seconds_elapsed == 0

    async def test_executes_physical_pulses_and_reports_their_market_cost(
        self, plug, clock, monkeypatch,
    ):
        import pandas as pd
        import strom.controller as controller
        from strom.optimization_utils import House, find_heating_output
        from strom.thermal_state import plan_temperature

        house = House(T_interior_init=18., T_wall_init=18.)
        index = pd.date_range("2025-01-01", periods=24, freq="h", tz="UTC")
        data = pd.DataFrame({"ExteriorTemperature": 5., "Price": .1}, index=index)
        market = pd.Series([.1, .2, .3, .4],
                           index=pd.date_range(index[0], periods=4, freq="15min"))
        data.attrs["market_prices"] = market
        executed = []
        real_execute = controller.execute_plan

        async def record(plug, plan, clock, watchdog):
            executed.append(plan)
            return await real_execute(plug, plan, clock, watchdog)

        monkeypatch.setattr(controller, "execute_plan", record)
        deps = make_deps(plug, clock, fetch=lambda: data,
                         optimize=lambda df, house, mode: find_heating_output(df, house, mode))
        report = await run_control_cycle(deps, _creds(), house)
        plan = executed[0]
        assert plan_temperature(house, 5., plan)[0] == pytest.approx(18., abs=.001)
        assert 900 < report.on_seconds < 1800
        expected = house.Q_heater * (
            900 * .11 + (report.on_seconds - 900) * .21
        ) / 3600
        assert report.estimated_cost_eur == pytest.approx(expected)
        assert plug.is_on is False

    async def test_subsequent_cycle_restores_the_saved_model_state(self, plug, clock, tmp_path):
        import json
        from strom.optimization_utils import House

        starts = []

        def optimize(frame, house, mode):
            starts.append(house.T_interior_init)
            return frame

        deps = make_deps(plug, clock, optimize=optimize)
        deps.state_path = tmp_path / "thermal_state.json"
        await run_control_cycle(deps, _creds(), House())
        saved = json.loads(deps.state_path.read_text())
        await run_control_cycle(deps, _creds(), House())
        assert starts[0] == 18.5
        assert starts[1] == pytest.approx(saved["interior"], abs=.001)

    async def test_full_cycle(self, plug, clock):
        deps = make_deps(plug, clock)
        await run_control_cycle(deps, _creds(), house=None)
        assert plug.calls[:3] == ["turn_on", "update", "turn_off"]
        assert plug.calls[-3:] == ["turn_off", "update", "async_close"]
        assert plug.calls.count("async_close") == 1

    async def test_cycle_returns_a_report(self, plug, clock):
        deps = make_deps(plug, clock)
        report = await run_control_cycle(deps, _creds(), house=None)
        assert report.on_seconds == pytest.approx(1800.0)
        assert report.interval_seconds == pytest.approx(3600.0)
        assert report.estimated_cost_eur == pytest.approx(0.0)

    async def test_zero_duty_never_turns_on(self, plug, clock):
        deps = make_deps(plug, clock, fetch=lambda: make_schedule([0.0]))
        await run_control_cycle(deps, _creds(), house=None)
        assert "turn_on" not in plug.calls

    @pytest.mark.parametrize("duty, expected_on, expected_elapsed", [
        (.5, 1825., 3625.), (1., 3625., 3625.), (0., 25., 3625.),
    ])
    async def test_measured_durations_feed_report_cost_and_persistence(
        self, plug, clock, tmp_path, monkeypatch, duty, expected_on, expected_elapsed,
    ):
        import json
        import strom.controller as controller
        from strom.control import ActuationPlan, ActuationSegment
        from strom.optimization_utils import House
        from strom.thermal_state import plan_temperature

        house = House()
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
        deps = make_deps(plug, clock, fetch=lambda: make_schedule([duty]))
        deps.state_path = tmp_path / "state.json"
        captured = []
        original_temperature = controller.plan_temperature

        def capture(house, exterior, plan):
            captured.append(plan)
            return original_temperature(house, exterior, plan)

        monkeypatch.setattr(controller, "plan_temperature", capture)
        report = await run_control_cycle(deps, _creds(), house)
        expected = ActuationPlan((
            ActuationSegment(True, expected_on),
            ActuationSegment(False, expected_elapsed - expected_on),
        ), expected_elapsed)
        assert report.on_seconds == pytest.approx(expected_on)
        assert report.interval_seconds == pytest.approx(expected_elapsed)
        assert report.estimated_cost_eur == pytest.approx(.1 * house.Q_heater * expected_on / 3600)
        assert captured[0].interval_seconds == pytest.approx(expected_elapsed)
        saved = json.loads(deps.state_path.read_text())
        assert (saved["interior"], saved["wall"]) == pytest.approx(
            plan_temperature(house, 10., expected)
        )


class TestDiscovery:
    async def test_none_discovery_blocks_everything(self, plug, clock):
        calls = {"fetch": 0, "optimize": 0}

        def fetch():
            calls["fetch"] += 1
            return make_schedule([1.0])

        def optimize(df, house, mode):
            calls["optimize"] += 1
            return df

        deps = make_deps(
            plug, clock,
            discover=lambda credentials: _return(None),
            fetch=fetch,
            optimize=optimize,
        )
        with pytest.raises(DeviceError):
            await run_control_cycle(deps, _creds(), house=None)
        assert calls == {"fetch": 0, "optimize": 0}
        assert plug.calls == []

    async def test_failed_discovery_raises_device_error(self, clock):
        async def boom(credentials):
            raise RuntimeError("kasa exploded")

        deps = make_deps(None, clock, discover=boom)
        with pytest.raises(DeviceError):
            await run_control_cycle(deps, _creds(), house=None)

    async def test_missing_device_ip(self, plug, clock):
        deps = make_deps(plug, clock)
        with pytest.raises(DeviceError):
            await run_control_cycle(deps, PlugCredentials(device_ip=""), house=None)
        assert plug.calls == []


class TestFailureInjection:
    async def test_data_fetch_failure_closes_exactly_once(self, plug, clock):
        def fetch():
            raise ProviderError("weather provider down")

        deps = make_deps(plug, clock, fetch=fetch)
        with pytest.raises(ProviderError):
            await run_control_cycle(deps, _creds(), house=None)
        assert plug.calls.count("async_close") == 1
        assert "turn_on" not in plug.calls

    async def test_optimization_failure_closes_exactly_once(self, plug, clock):
        def optimize(df, house, mode):
            raise SolverError("CLARABEL failed")

        deps = make_deps(plug, clock, optimize=optimize)
        with pytest.raises(OptimizationError):
            await run_control_cycle(deps, _creds(), house=None)
        assert plug.calls.count("async_close") == 1
        assert "turn_on" not in plug.calls

    async def test_failed_schedule_never_actuates(self, plug, clock):
        deps = make_deps(plug, clock,
                         fetch=lambda: make_schedule([np.nan]))
        with pytest.raises(InvalidScheduleError):
            await run_control_cycle(deps, _creds(), house=None)
        assert plug.calls.count("async_close") == 1
        assert "turn_on" not in plug.calls
        assert "turn_off" in plug.calls

    async def test_command_failure_closes_exactly_once(self, plug, clock):
        plug.fail_on = lambda op: DeviceError("plug refused") if op == "turn_on" else None
        deps = make_deps(plug, clock, fetch=lambda: make_schedule([1.0]))
        with pytest.raises(DeviceError):
            await run_control_cycle(deps, _creds(), house=None)
        assert plug.calls.count("async_close") == 1

    async def test_state_update_failure_closes_exactly_once(self, plug, clock):
        plug.fail_on = lambda op: RuntimeError("update blew up") if op == "update" else None
        deps = make_deps(plug, clock)
        with pytest.raises(DeviceError):
            await run_control_cycle(deps, _creds(), house=None)
        assert plug.calls.count("async_close") == 1

    async def test_unexpected_error_still_closes_and_propagates(self, plug, clock):
        def fetch():
            raise KeyError("programming bug")

        deps = make_deps(plug, clock, fetch=fetch)
        with pytest.raises(KeyError):
            await run_control_cycle(deps, _creds(), house=None)
        assert plug.calls.count("async_close") == 1

    async def test_close_failure_does_not_mask_result(self, plug, clock):
        async def broken_close():
            raise RuntimeError("close failed")

        plug.async_close = broken_close
        deps = make_deps(plug, clock)
        await run_control_cycle(deps, _creds(), house=None)

    async def test_full_duty_finishes_with_verified_off(self, plug, clock):
        deps = make_deps(plug, clock, fetch=lambda: make_schedule([1.0]))
        await run_control_cycle(deps, _creds(), house=None)
        assert plug.is_on is False
        assert plug.calls[-3:] == ["turn_off", "update", "async_close"]

    async def test_cancellation_and_repeated_cancellation_complete_shutdown(
        self, plug, monkeypatch,
    ):
        from strom.control import SystemClock

        shutdown_started = asyncio.Event()
        allow_shutdown = asyncio.Event()
        original_off = plug.turn_off

        async def delayed_off():
            shutdown_started.set()
            await allow_shutdown.wait()
            await original_off()

        plug.turn_off = delayed_off
        deps = make_deps(plug, SystemClock(), fetch=lambda: make_schedule([1.0]))
        task = asyncio.create_task(run_control_cycle(deps, _creds(), house=None))
        while not plug.is_on:
            await asyncio.sleep(0)
        task.cancel()
        await shutdown_started.wait()
        task.cancel()
        await asyncio.sleep(0)
        allow_shutdown.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert plug.is_on is False
        assert plug.closed == 1

    async def test_unverified_execution_removes_state_instead_of_saving_nominal(
        self, plug, clock, tmp_path, monkeypatch,
    ):
        from strom.optimization_utils import House
        from strom.thermal_state import save_state

        deps = make_deps(plug, clock)
        deps.state_path = tmp_path / "state.json"
        save_state(deps.state_path, House(), _creds().device_ip, (18., 18.))
        original_off = plug.turn_off
        attempts = 0

        async def ignored_once():
            nonlocal attempts
            attempts += 1
            if attempts > 1:
                await original_off()

        plug.turn_off = ignored_once
        with pytest.raises(DeviceError, match="confirm.*OFF"):
            await run_control_cycle(deps, _creds(), House())
        assert not deps.state_path.exists()
        assert plug.is_on is False
        assert plug.closed == 1

    async def test_watchdog_intervention_during_shutdown_does_not_save_state(
        self, plug, clock, tmp_path, monkeypatch,
    ):
        import strom.controller as controller
        from strom.optimization_utils import House

        deps = make_deps(plug, clock, fetch=lambda: make_schedule([1.]))
        deps.state_path = tmp_path / "state.json"
        watchdog = controller._make_watchdog(deps, plug)
        monkeypatch.setattr(controller, "_make_watchdog", lambda deps, plug: watchdog)
        original_off = plug.turn_off

        async def off_after_trip():
            watchdog.tripped = True
            await original_off()

        plug.turn_off = off_after_trip
        with pytest.raises(DeviceError, match="watchdog interrupted"):
            await run_control_cycle(deps, _creds(), House())
        assert not deps.state_path.exists()
        assert plug.is_on is False

    async def test_shutdown_retries_a_transient_off_failure(self, plug, clock, monkeypatch):
        import strom.controller as controller

        monkeypatch.setattr(controller, "OFF_RETRY_SECONDS", 0)
        attempts = 0
        original_off = plug.turn_off

        async def flaky_off():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("temporary failure")
            await original_off()

        plug.turn_off = flaky_off
        await run_control_cycle(
            make_deps(plug, clock, fetch=lambda: make_schedule([1.0])),
            _creds(), house=None,
        )
        assert attempts == 2
        assert plug.is_on is False

    async def test_shutdown_fails_if_the_plug_still_reports_on(self, plug, clock, monkeypatch):
        import strom.controller as controller

        monkeypatch.setattr(controller, "OFF_RETRY_SECONDS", 0)

        async def ignored_off():
            plug.calls.append("turn_off")

        plug.turn_off = ignored_off
        with pytest.raises(DeviceError, match="Could not confirm"):
            await run_control_cycle(
                make_deps(plug, clock, fetch=lambda: make_schedule([1.0])),
                _creds(), house=None,
            )
        assert plug.calls.count("turn_off") == 3
        assert plug.closed == 1

    async def test_shutdown_commands_have_a_bounded_timeout(self, plug, monkeypatch):
        import strom.controller as controller
        from strom.control import SystemClock

        monkeypatch.setattr(controller, "OFF_TIMEOUT_SECONDS", .01)
        monkeypatch.setattr(controller, "OFF_RETRY_SECONDS", 0)
        attempts = []

        async def hung_off():
            attempts.append(True)
            await asyncio.Event().wait()

        plug.turn_off = hung_off
        deps = make_deps(plug, SystemClock(), fetch=lambda: make_schedule([1.]))
        deps.interval_seconds = .001
        with pytest.raises(DeviceError, match="Could not confirm"):
            await asyncio.wait_for(run_control_cycle(deps, _creds(), house=None), timeout=1.)
        assert len(attempts) == 3
        assert plug.closed == 1


class TestExitCodes:
    def test_strom_error_maps_to_exit_one(self, tmp_path, monkeypatch, caplog):
        from strom import cli
        from .conftest import make_config_dir

        config = make_config_dir(tmp_path)

        async def failing_cycle(cfg, deps):
            raise ProviderError("rate limited")

        monkeypatch.setattr(cli, "run_cycle", failing_cycle)
        with caplog.at_level("ERROR"):
            assert cli.run(["--config-dir", str(config)]) == 1
        assert "rate limited" in caplog.text

    def test_report_file_written_after_a_successful_run(self, tmp_path, monkeypatch):
        import json

        from strom import cli
        from strom.controller import ControlReport
        from .conftest import make_config_dir

        config = make_config_dir(tmp_path)

        async def ok_cycle(cfg, deps):
            return ControlReport(
                on_seconds=1920.0,
                interval_seconds=3600.0,
                estimated_cost_eur=0.123,
            )

        monkeypatch.setattr(cli, "run_cycle", ok_cycle)
        report_path = tmp_path / "report.json"
        code = cli.run([
            "--config-dir", str(config), "--report-file", str(report_path),
        ])
        assert code == 0
        assert json.loads(report_path.read_text()) == {
            "on_seconds": 1920.0,
            "interval_seconds": 3600.0,
            "estimated_cost_eur": 0.123,
        }

    def test_unexpected_error_propagates(self, tmp_path, monkeypatch):
        from strom import cli
        from .conftest import make_config_dir

        config = make_config_dir(tmp_path)

        async def failing_cycle(cfg, deps):
            raise ZeroDivisionError("bug")

        monkeypatch.setattr(cli, "run_cycle", failing_cycle)
        with pytest.raises(ZeroDivisionError):
            cli.run(["--config-dir", str(config)])
