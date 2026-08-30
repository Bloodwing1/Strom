"""Deterministic controller tests (audit issues 31 and 32).

Failure injection covers every stage: discovery, data fetch, optimization,
plan construction, plug commands and state update. Cleanup is asserted to
happen exactly once after every successful discovery.
"""

from __future__ import annotations

import numpy as np
import pytest

from strom.controller import ControllerDeps, run_control_cycle
from strom.errors import (
    DeviceError,
    InvalidScheduleError,
    OptimizationError,
    ProviderError,
    SolverError,
)

from .conftest import FakePlug, ManualClock, make_schedule


def make_deps(plug, clock, *, discover=None, fetch=None, optimize=None,
              max_on=3 * 3600.0):
    return ControllerDeps(
        discover=discover or (lambda ip, email, pw: _return(plug)),
        fetch_data=fetch or (lambda: make_schedule([0.5])),
        optimize=optimize or (lambda df, house, mode: df),
        clock=clock,
        max_on_seconds=max_on,
        interval_seconds=3600.0,
    )


async def _return(value):
    return value


class TestHappyPath:
    async def test_full_cycle(self, plug, clock):
        deps = make_deps(plug, clock)
        await run_control_cycle(deps, "e", "p", "1.2.3.4", house=None)
        assert plug.calls[:3] == ["turn_on", "turn_off", "update"]
        assert plug.calls.count("async_close") == 1

    async def test_zero_duty_never_turns_on(self, plug, clock):
        deps = make_deps(plug, clock, fetch=lambda: make_schedule([0.0]))
        await run_control_cycle(deps, "e", "p", "1.2.3.4", house=None)
        assert "turn_on" not in plug.calls


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
            discover=lambda ip, e, p: _return(None),
            fetch=fetch,
            optimize=optimize,
        )
        with pytest.raises(DeviceError):
            await run_control_cycle(deps, "e", "p", "1.2.3.4", house=None)
        assert calls == {"fetch": 0, "optimize": 0}
        assert plug.calls == []

    async def test_failed_discovery_raises_device_error(self, clock):
        async def boom(ip, e, p):
            raise RuntimeError("kasa exploded")

        deps = make_deps(None, clock, discover=boom)
        with pytest.raises(DeviceError):
            await run_control_cycle(deps, "e", "p", "1.2.3.4", house=None)

    async def test_missing_device_ip(self, plug, clock):
        deps = make_deps(plug, clock)
        with pytest.raises(DeviceError):
            await run_control_cycle(deps, "e", "p", "", house=None)
        assert plug.calls == []


class TestFailureInjection:
    async def test_data_fetch_failure_closes_exactly_once(self, plug, clock):
        def fetch():
            raise ProviderError("weather provider down")

        deps = make_deps(plug, clock, fetch=fetch)
        with pytest.raises(ProviderError):
            await run_control_cycle(deps, "e", "p", "1.2.3.4", house=None)
        assert plug.calls.count("async_close") == 1
        assert "turn_on" not in plug.calls

    async def test_optimization_failure_closes_exactly_once(self, plug, clock):
        def optimize(df, house, mode):
            raise SolverError("CLARABEL failed")

        deps = make_deps(plug, clock, optimize=optimize)
        with pytest.raises(OptimizationError):
            await run_control_cycle(deps, "e", "p", "1.2.3.4", house=None)
        assert plug.calls.count("async_close") == 1
        assert "turn_on" not in plug.calls

    async def test_failed_schedule_never_actuates(self, plug, clock):
        deps = make_deps(plug, clock,
                         fetch=lambda: make_schedule([np.nan]))
        with pytest.raises(InvalidScheduleError):
            await run_control_cycle(deps, "e", "p", "1.2.3.4", house=None)
        assert plug.calls.count("async_close") == 1
        assert "turn_on" not in plug.calls
        assert "turn_off" not in plug.calls

    async def test_command_failure_closes_exactly_once(self, plug, clock):
        plug.fail_on = lambda op: DeviceError("plug refused") if op == "turn_on" else None
        deps = make_deps(plug, clock, fetch=lambda: make_schedule([1.0]))
        with pytest.raises(DeviceError):
            await run_control_cycle(deps, "e", "p", "1.2.3.4", house=None)
        assert plug.calls.count("async_close") == 1

    async def test_state_update_failure_closes_exactly_once(self, plug, clock):
        plug.fail_on = lambda op: RuntimeError("update blew up") if op == "update" else None
        deps = make_deps(plug, clock)
        with pytest.raises(DeviceError):
            await run_control_cycle(deps, "e", "p", "1.2.3.4", house=None)
        assert plug.calls.count("async_close") == 1

    async def test_unexpected_error_still_closes_and_propagates(self, plug, clock):
        def fetch():
            raise KeyError("programming bug")

        deps = make_deps(plug, clock, fetch=fetch)
        with pytest.raises(KeyError):
            await run_control_cycle(deps, "e", "p", "1.2.3.4", house=None)
        assert plug.calls.count("async_close") == 1

    async def test_close_failure_does_not_mask_result(self, plug, clock):
        async def broken_close():
            raise RuntimeError("close failed")

        plug.async_close = broken_close
        deps = make_deps(plug, clock)
        await run_control_cycle(deps, "e", "p", "1.2.3.4", house=None)


class TestExitCodes:
    @staticmethod
    def _patch_cli(monkeypatch, cycle):
        from strom import cli

        monkeypatch.setattr(
            cli, "setup_env_config", lambda: ("e", "p", "1.2.3.4", None)
        )
        monkeypatch.setattr(cli, "main", cycle)

    def test_strom_error_maps_to_exit_one(self, monkeypatch, caplog):
        from strom import cli

        def failing_cycle(email, password, device_ip, house,
                          deps=None, clock=None):
            raise ProviderError("rate limited")

        self._patch_cli(monkeypatch, failing_cycle)
        with caplog.at_level("ERROR"):
            assert cli.run() == 1
        assert "rate limited" in caplog.text

    def test_unexpected_error_propagates(self, monkeypatch):
        from strom import cli

        def failing_cycle(email, password, device_ip, house,
                          deps=None, clock=None):
            raise ZeroDivisionError("bug")

        self._patch_cli(monkeypatch, failing_cycle)
        with pytest.raises(ZeroDivisionError):
            cli.run()
