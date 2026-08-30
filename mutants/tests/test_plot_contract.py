"""Plot contract tests (audit issue 37).

Lightweight checks with the non-interactive Agg backend: figures are
created, have the expected axes, and never require a display server.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # must run before pyplot is imported anywhere

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from strom.plot_utils import (
    plot_combined_cases,
    plot_combined_cases_years,
    plot_factor_analysis,
)

from .conftest import make_schedule


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


@pytest.fixture
def state_pair():
    index = None
    opt = make_schedule(
        [0.5, 0.2, 0.8, 0.0, 0.3, 0.6], index=index,
        InteriorTemperature=np.linspace(19, 21, 6),
        WallTemperature=np.linspace(19, 20, 6),
        ExteriorTemperature=np.linspace(8, 12, 6),
        Price=np.linspace(0.1, 0.3, 6),
        Cost=np.linspace(0.0, 0.1, 6),
    )
    base = opt.copy()
    return opt, base


class TestPlotCombinedCases:
    def test_returns_figure_with_two_subplots(self, state_pair):
        opt, base = state_pair
        fig = plot_combined_cases(opt, base)
        # 2 subplots plus twin axes for price and heater output.
        assert len(fig.axes) >= 2
        assert fig.axes[0].get_ylabel() == "Temperature (°C)"

    @pytest.mark.parametrize("kwargs", [
        {"plot_heater_output": False},
        {"plot_cooling_output": True},
        {"plot_price": False},
        {"plot_T_exterior": False},
        {"plot_wall_temp": False},
    ])
    def test_optional_tracks_toggle(self, state_pair, kwargs):
        opt, base = state_pair
        fig = plot_combined_cases(opt, base, **kwargs)
        assert fig is not None

    def test_accepts_timezone_aware_index(self, state_pair):
        opt, base = state_pair
        assert str(opt.index.tz) == "UTC"
        plot_combined_cases(opt, base)


class TestYearlyPlot:
    def test_returns_figure(self):
        index = pd.date_range("2025-01-01", periods=24 * 10, freq="h",
                              tz="UTC")
        n = len(index)
        opt = make_schedule(np.full(n, 0.4), index=index,
                            Cost=np.linspace(0.0, 1.0, n))
        base = make_schedule(np.full(n, 0.9), index=index,
                             Cost=np.linspace(0.0, 2.0, n))
        fig = plot_combined_cases_years(opt, base)
        assert fig is not None


class TestFactorAnalysis:
    def test_relative_and_absolute(self):
        costs = np.array([1.0, 2.0, 3.0])
        baseline = np.array([4.0, 5.0, 6.0])
        walls = [2.0, 3.0]
        powers = [1.0, 2.0]
        r_values = [4.0, 5.0]
        for kind in ("Relative", "Absolute"):
            fig = plot_factor_analysis(costs, baseline, walls, powers,
                                       r_values, kind)
            assert fig is not None

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Relative"):
            plot_factor_analysis(np.array([1.0]), np.array([2.0]),
                                 [2.0], [1.0], [4.0], "bogus")
