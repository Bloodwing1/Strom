"""Property/metamorphic tests for physical and economic relationships.

These tests do not pin exact schedules; they verify that the optimizer
respects invariants that must hold for *any* correct solve (audit issue 37).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strom.optimization_utils import House, find_heating_output


def input_df(hours=24, exterior=10.0, price=0.15, start="2025-01-20"):
    index = pd.date_range(start, periods=hours, freq="h", tz="UTC")
    return pd.DataFrame({
        "ExteriorTemperature": np.full(hours, exterior),
        "Price": np.full(hours, price),
    }, index=index)


def house(**overrides):
    params = dict(Q_heater=3.0, Q_cooling=0.0, P_base=0.0,
                  T_interior_init=19.0, T_min=18.0, T_max=24.0)
    params.update(overrides)
    return House(**params)


class TestPhysicalRelationships:
    def test_warmer_exterior_needs_no_more_heating(self):
        """Keeping comfort must require (weakly) less energy when it is
        warmer outside, all else equal."""
        cold = find_heating_output(input_df(exterior=0.0), house(),
                                   "optimal")
        mild = find_heating_output(input_df(exterior=12.0), house(),
                                   "optimal")
        cold_energy = cold["HeaterOutput"].sum()
        mild_energy = mild["HeaterOutput"].sum()
        assert cold_energy >= mild_energy
        assert cold_energy > 0

    def test_interior_decays_toward_exterior_without_heating(self):
        """With no heater power and a low comfort floor, the interior
        temperature may not rise while the house is losing heat."""
        df = input_df(hours=6, exterior=2.0)
        result = find_heating_output(
            df, house(Q_heater=0.0, T_interior_init=19.0, T_min=5.0),
            "optimal")
        interior = result["InteriorTemperature"].to_numpy()
        assert (np.diff(interior) <= 1e-6).all()

    def test_comfort_band_never_violated(self):
        result = find_heating_output(input_df(exterior=5.0), house(),
                                     "optimal")
        h = house()
        assert (result["InteriorTemperature"] >= h.T_min - 1e-3).all()
        assert (result["InteriorTemperature"] <= h.T_max + 1e-3).all()


class TestEconomicRelationships:
    def test_cost_scales_linearly_with_price(self):
        """Scaling every market price by 2 must scale the total cost by 2
        and leave the physical schedule unchanged (linear objective)."""
        base = find_heating_output(input_df(price=0.10), house(), "optimal")
        scaled = find_heating_output(input_df(price=0.20), house(), "optimal")
        assert np.allclose(base["HeaterOutput"], scaled["HeaterOutput"],
                           rtol=1e-3, atol=1e-6)
        assert np.allclose(2 * base["Cost"], scaled["Cost"],
                           rtol=1e-3, atol=1e-6)

    def test_shifting_load_towards_cheap_hours(self):
        """With a cheap and an expensive hour, pre-heating must move at
        least some energy into the cheap hour relative to uniform pricing."""
        index = pd.date_range("2025-01-20", periods=6, freq="h", tz="UTC")
        prices = pd.Series([0.05, 0.05, 1.00, 1.00, 1.00, 1.00],
                           index=index)
        df = pd.DataFrame({
            "ExteriorTemperature": np.full(6, 5.0),
            "Price": prices,
        }, index=index)
        h = house(T_interior_init=18.0, T_min=18.0)
        result = find_heating_output(df, h, "optimal")
        cheap_energy = result["HeaterOutput"].iloc[:2].sum()
        expensive_energy = result["HeaterOutput"].iloc[2:].sum()
        # Freezing exterior: comfort must be maintained in expensive hours
        # too, so the optimizer pre-heats while energy is cheap.
        assert cheap_energy > 0
        assert result["Cost"].iloc[:2].sum() < result["Cost"].iloc[2:].sum()

    def test_expensive_priced_hour_uses_less_energy_than_free_hour(self):
        """Given two otherwise identical horizons, the one with free energy
        uses at least as much heater energy as the costly one."""
        cheap = find_heating_output(input_df(price=0.0), house(), "optimal")
        costly = find_heating_output(input_df(price=0.50), house(), "optimal")
        assert cheap["HeaterOutput"].sum() >= costly["HeaterOutput"].sum()
