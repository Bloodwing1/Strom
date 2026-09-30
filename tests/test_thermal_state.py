from __future__ import annotations

import pandas as pd
import pytest

from strom.errors import ConfigurationError, InvalidScheduleError
from strom.optimization_utils import House, find_heating_output
from strom.thermal_state import (
    advance_temperature, plan_temperature, restore_state, save_state, temperature_plan,
)

NOW = pd.Timestamp("2025-01-01 12:00", tz="UTC")


def test_next_process_restores_estimates_and_models_idle_cooling(tmp_path):
    path = tmp_path / "thermal_state.json"
    configured = House()
    save_state(path, configured, "1.2.3.4", (19.0, 18.0), now=NOW)
    restored = restore_state(path, configured, "1.2.3.4", 5.0, now=NOW)
    assert restored is not configured
    assert restored.T_interior_init == 19.0
    assert configured.T_interior_init == 18.5
    later = restore_state(path, configured, "1.2.3.4", 5.0, now=NOW + pd.Timedelta(hours=1))
    assert (later.T_interior_init, later.T_wall_init) == pytest.approx(
        advance_temperature(restored, 5.0, 3600)
    )


def test_a_different_plug_or_changed_configuration_does_not_reuse_state(tmp_path):
    path = tmp_path / "thermal_state.json"
    save_state(path, House(), "1.2.3.4", (21., 20.), now=NOW)
    for house, address in ((House(), "1.2.3.5"), (House(Q_heater=3), "1.2.3.4")):
        assert restore_state(path, house, address, 10., now=NOW) is house


def test_corrupt_state_fails_instead_of_guessing(tmp_path):
    path = tmp_path / "thermal_state.json"
    path.write_text("invalid json")
    with pytest.raises(ConfigurationError):
        restore_state(path, House(), "1.2.3.4", 10., now=NOW)


def test_repeated_cycles_use_the_previous_physical_temperature(tmp_path):
    configured = House()
    path = tmp_path / "thermal_state.json"
    first_output = None
    later_outputs = []
    for cycle in range(12):
        now = NOW + pd.Timedelta(hours=cycle)
        house = restore_state(path, configured, "1.2.3.4", 10., now=now)
        frame = pd.DataFrame(
            {"ExteriorTemperature": 10., "Price": .1},
            index=pd.date_range(now, periods=24, freq="h"),
        )
        schedule = find_heating_output(frame, house, "optimal")
        output = schedule.HeaterOutput.iloc[0]
        if first_output is None:
            first_output = output
        else:
            later_outputs.append(output)
        plan = temperature_plan(house, 10., schedule.InteriorTemperature.iloc[1], 3600)
        temperatures = plan_temperature(house, 10., plan)
        save_state(path, configured, "1.2.3.4", temperatures, now=now + pd.Timedelta(hours=1))
    assert max(later_outputs) > first_output + .1
    assert temperatures[0] >= 18.0 - .001


@pytest.mark.parametrize("upper", [24., 18.2])
def test_real_relay_pulses_keep_comfort_and_match_the_next_temperature(upper):
    import copy
    import numpy as np

    house = House(T_interior_init=18., T_wall_init=18., T_max=upper)
    plan = temperature_plan(house, 5., 18., 3600)
    assert plan_temperature(house, 5., plan)[0] == pytest.approx(18., abs=.001)
    if upper == 18.2:
        assert len(plan.segments) > 2
    state = copy.copy(house)
    for segment in plan.segments:
        assert not segment.on or segment.seconds >= 60
        for elapsed in np.linspace(0, segment.seconds, 31):
            interior, _ = advance_temperature(state, 5., elapsed, float(segment.on))
            assert 17.999 <= interior <= upper + .001
        state.T_interior_init, state.T_wall_init = advance_temperature(
            state, 5., segment.seconds, float(segment.on)
        )


def test_unachievable_comfort_with_minimum_relay_pulse_is_rejected():
    house = House(T_interior_init=18., T_wall_init=18., T_max=18.02)
    with pytest.raises(InvalidScheduleError, match="No relay plan"):
        temperature_plan(house, 5., 18., 3600)
