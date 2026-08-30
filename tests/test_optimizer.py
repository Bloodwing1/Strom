"""Deterministic optimizer tests (audit issue 33).

Covers parameter validation, malformed inputs, exact ZOH dynamics,
independent cost recomputation, and solver failure handling with synthetic
horizons only.
"""

from __future__ import annotations

import cvxpy as cp
import numpy as np
import pandas as pd
import pytest

from strom.errors import (
    ConfigurationError,
    InfeasibleProblemError,
    InvalidInputError,
    SolverError,
)
from strom.optimization_utils import (
    House,
    find_heating_output,
    zero_order_hold_matrices,
)


def make_input(hours=24, exterior=12.0, price=0.15, tz="UTC",
               start="2025-01-20") -> pd.DataFrame:
    index = pd.date_range(start, periods=hours, freq="h", tz=tz)
    return pd.DataFrame(
        {
            "ExteriorTemperature": np.full(hours, exterior),
            "Price": np.full(hours, price),
        },
        index=index,
    )


def default_house(**overrides) -> House:
    params = dict(Q_heater=2.0, Q_cooling=0.0, P_base=0.0,
                  T_interior_init=19.0)
    params.update(overrides)
    return House(**params)


class TestHouseValidation:
    @pytest.mark.parametrize("param", ["C_air", "C_wall", "R_interior",
                                       "R_exterior"])
    def test_zero_or_negative_physical_params_rejected(self, param):
        with pytest.raises(ConfigurationError, match=param):
            default_house(**{param: 0.0})

    def test_nan_parameter_rejected(self):
        with pytest.raises(ConfigurationError):
            default_house(C_air=float("nan"))

    def test_inverted_comfort_bounds_rejected(self):
        with pytest.raises(ConfigurationError):
            default_house(T_min=24.0, T_max=18.0)

    def test_initial_temperature_outside_bounds_rejected(self):
        with pytest.raises(ConfigurationError, match="T_interior_init"):
            default_house(T_interior_init=30.0)

    @pytest.mark.parametrize("bad", ["not-a-freq", "",  "0h"])
    def test_invalid_frequency_rejected(self, bad):
        with pytest.raises(ConfigurationError):
            default_house(freq=bad)

    def test_negative_price_rejected(self):
        with pytest.raises(ConfigurationError):
            default_house(P_base=-1.0)


class TestInputValidation:
    def test_empty_input_rejected(self):
        with pytest.raises(InvalidInputError, match="at least two"):
            find_heating_output(make_input(hours=0), default_house(),
                                "optimal")

    def test_one_row_rejected(self):
        with pytest.raises(InvalidInputError, match="at least two"):
            find_heating_output(make_input(hours=1), default_house(),
                                "optimal")

    def test_non_finite_values_rejected(self):
        df = make_input()
        df.iloc[3, 0] = np.nan
        with pytest.raises(InvalidInputError, match="non-finite"):
            find_heating_output(df, default_house(), "optimal")

    def test_duplicated_index_rejected(self):
        df = make_input()
        df = pd.concat([df, df.iloc[[0]]]).sort_index()
        with pytest.raises(InvalidInputError, match="duplicated"):
            find_heating_output(df, default_house(), "optimal")

    def test_naive_index_rejected(self):
        df = make_input()
        df.index = df.index.tz_localize(None)
        with pytest.raises(InvalidInputError, match="timezone-aware"):
            find_heating_output(df, default_house(), "optimal")

    def test_missing_column_rejected(self):
        df = make_input().drop(columns=["Price"])
        with pytest.raises(InvalidInputError, match="Price"):
            find_heating_output(df, default_house(), "optimal")

    def test_non_dataframe_rejected(self):
        with pytest.raises(InvalidInputError):
            find_heating_output("nope", default_house(), "optimal")

    def test_unsorted_input_is_sorted_not_mutated(self):
        df = make_input()
        shuffled = df.iloc[::-1]
        original = shuffled.copy()
        result = find_heating_output(shuffled, default_house(), "optimal")
        # Input untouched, output monotonic.
        pd.testing.assert_frame_equal(shuffled, original)
        assert result.index.is_monotonic_increasing

    def test_missing_price_interval_rejected_not_invented(self):
        df = make_input(hours=6)
        df = df.drop(df.index[3])  # one missing hour
        with pytest.raises(InvalidInputError, match="missing values"):
            find_heating_output(df, default_house(), "optimal")

    def test_upsampled_prices_are_forward_filled_not_interpolated(self):
        df = make_input(hours=4, price=0.10)
        house = default_house(freq="15min")
        result = find_heating_output(df, house, "optimal")
        prices = result["Price"]
        # Each market hour holds one exact price (step function).
        hour = prices.index.to_series().dt.floor("h")
        assert prices.groupby(hour).nunique().eq(1).all()
        assert (prices == 0.10).all()


@pytest.fixture(scope="module")
def solved_result():
    """One shared optimal solve for all invariant checks (pytest 9 no longer
    allows class-scoped fixtures as class members)."""
    df = make_input(exterior=10.0)
    house = default_house()
    return find_heating_output(df, house, "optimal"), house


class TestSuccessfulSolve:
    def test_outputs_are_finite(self, solved_result):
        state, _ = solved_result
        assert np.isfinite(state["HeaterOutput"]).all()
        assert np.isfinite(state["CoolingOutput"]).all()
        assert np.isfinite(state["InteriorTemperature"]).all()
        assert np.isfinite(state["Cost"]).all()

    def test_control_bounds_respected(self, solved_result):
        state, _ = solved_result
        assert ((state["HeaterOutput"] >= 0) &
                (state["HeaterOutput"] <= 1)).all()
        assert ((state["CoolingOutput"] >= 0) &
                (state["CoolingOutput"] <= 1)).all()

    def test_comfort_bounds_respected(self, solved_result):
        state, house = solved_result
        assert (state["InteriorTemperature"] >= house.T_min - 1e-3).all()
        assert (state["InteriorTemperature"] <= house.T_max + 1e-3).all()

    def test_cost_is_independently_recomputable(self, solved_result):
        state, house = solved_result
        dt = house.dt_hours
        recomputed = (state["Price"] * dt
                      * (house.Q_heater * state["HeaterOutput"]
                         + house.Q_cooling * state["CoolingOutput"]))
        assert np.allclose(state["Cost"], recomputed)

    def test_dynamics_residual_within_tolerance(self, solved_result):
        state, house = solved_result
        A = np.array([
            [-1.0 / (house.R_interior * house.C_air),
             1.0 / (house.R_interior * house.C_air)],
            [1.0 / (house.R_interior * house.C_wall),
             -((1.0 / house.R_interior) + (1.0 / house.R_exterior))
             / house.C_wall],
        ])
        B = np.array([
            [house.Q_heater / house.C_air, -house.Q_cooling / house.C_air,
             0.0],
            [0.0, 0.0, 1.0 / (house.R_exterior * house.C_wall)],
        ])
        Ad, Bd = zero_order_hold_matrices(A, B, house.dt_hours)
        X = state[["InteriorTemperature", "WallTemperature"]].to_numpy().T
        u = state["HeaterOutput"].to_numpy()
        Text = state["ExteriorTemperature"].to_numpy()
        predicted = (Ad @ X[:, :-1] + np.outer(Bd[:, 0], u[:-1])
                     + np.outer(Bd[:, 2], Text[:-1]))
        residual = np.abs(predicted - X[:, 1:])
        assert residual.max() < 1e-4

    def test_optimal_never_costs_more_than_baseline(self):
        df = make_input(exterior=10.0)
        house = default_house()
        optimal = find_heating_output(df, house, "optimal")
        baseline = find_heating_output(df, house, "baseline")
        assert optimal["Cost"].sum() <= baseline["Cost"].sum() + 1e-9


class TestInfeasibleAndSolverFailure:
    def test_physically_infeasible_problem_raises(self):
        # Weak heater, freezing exterior: comfort is unreachable.
        df = make_input(hours=12, exterior=-40.0)
        house = default_house(Q_heater=0.001, T_interior_init=21.0,
                              T_min=21.0)
        with pytest.raises(InfeasibleProblemError):
            find_heating_output(df, house, "optimal")

    def test_solver_crash_raises_typed_error(self, monkeypatch):
        def crash(self, *args, **kwargs):
            raise RuntimeError("CLARABEL crashed")

        monkeypatch.setattr(cp.Problem, "solve", crash)
        with pytest.raises(SolverError, match="CLARABEL"):
            find_heating_output(make_input(), default_house(), "optimal")

    def test_non_optimal_status_raises_no_schedule(self, monkeypatch):
        def fake_solve(self, *args, **kwargs):
            self._status = "user_limit"
            return None

        monkeypatch.setattr(cp.Problem, "solve", fake_solve)
        with pytest.raises(SolverError, match="user_limit"):
            find_heating_output(make_input(), default_house(), "optimal")

    def test_inaccurate_solution_failing_residuals_rejected(self, monkeypatch):
        def fake_solve(self, *args, **kwargs):
            self._status = cp.OPTIMAL_INACCURATE
            for var in self.variables():
                var.value = np.full(var.shape, 5.0)  # violates [0, 1]

        monkeypatch.setattr(cp.Problem, "solve", fake_solve)
        with pytest.raises(SolverError, match="bounds"):
            find_heating_output(make_input(), default_house(), "optimal")

    def test_non_finite_solver_values_rejected(self):
        """The finite-value guard must trigger on any non-finite output,
        whether it comes from the heater, cooling or state trajectory."""
        from strom.optimization_utils import _check_solution

        house = default_house()
        zeros = np.zeros(24)
        eye = np.eye(2)
        zero_b = np.zeros((2, 3))
        good = np.tile(np.array([[20.0], [19.0]]), (1, 24))

        _check_solution(  # fully finite passes
            {"HeaterOutput": np.full(24, 0.5), "CoolingOutput": zeros,
             "_T": good},
            house, eye, zero_b, zeros)
        with pytest.raises(SolverError, match="non-finite"):
            _check_solution(
                {"HeaterOutput": np.full(24, np.nan), "CoolingOutput": zeros,
                 "_T": good},
                house, eye, zero_b, zeros)
        with pytest.raises(SolverError, match="non-finite"):
            _check_solution(
                {"HeaterOutput": np.full(24, 0.5), "CoolingOutput": zeros,
                 "_T": np.full((2, 24), np.nan)},
                house, eye, zero_b, zeros)

    def test_invalid_mode_rejected(self):
        with pytest.raises(InvalidInputError, match="heating mode"):
            find_heating_output(make_input(), default_house(), "turbo")
