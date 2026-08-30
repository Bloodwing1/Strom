"""Deterministic controller tests for the duty-cycle actuation path.

The optimizer and the smart plug are faked; no network, config files, or
wall clock are involved.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from strom.cli import main

from .conftest import FakePlug, ManualClock, make_schedule


@pytest.fixture
def house():
    from strom.optimization_utils import House

    return House()


async def _run_main(plug, schedule, house, clock):
    with patch("kasa.Discover.discover_single", return_value=plug), \
         patch("strom.cli.find_heating_output", return_value=schedule), \
         patch("strom.cli.get_temp_price_df", return_value=None):
        await main("email", "password", "1.2.3.4", house, clock=clock)


async def test_heater_schedule_switches_device_on(house, plug, clock):
    schedule = make_schedule([1.0, 0.0])
    await _run_main(plug, schedule, house, clock)
    assert plug.calls[0] == "turn_on"
    assert plug.is_on is True
    # Connection is closed on the happy path.
    assert "async_close" in plug.calls


async def test_zero_schedule_switches_device_off(house, plug, clock):
    schedule = make_schedule([0.0, 0.0])
    await _run_main(plug, schedule, house, clock)
    assert "turn_off" in plug.calls
    assert plug.is_on is False


async def test_fractional_schedule_runs_duty_cycle(house, plug, clock):
    schedule = make_schedule([0.5])
    await _run_main(plug, schedule, house, clock)
    assert plug.calls[:2] == ["turn_on", "turn_off"]
    # One control interval of 1h at 50% duty: on 1800s, off 1800s.
    assert clock.sleeps == [1800.0, 1800.0]


async def test_failed_schedule_never_touches_plug(house, plug, clock):
    import numpy as np

    schedule = make_schedule([np.nan])
    with patch("kasa.Discover.discover_single", return_value=plug), \
         patch("strom.cli.find_heating_output", return_value=schedule), \
         patch("strom.cli.get_temp_price_df", return_value=None):
        await main("email", "password", "1.2.3.4", house, clock=clock)
    # NaN must be rejected before any plug command.
    assert "turn_on" not in plug.calls
    assert "turn_off" not in plug.calls
