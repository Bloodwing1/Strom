"""Thermal model and heating-schedule optimizer.

Numerical safety (audit issue 33)
---------------------------------
* All :class:`House` parameters and optimizer inputs are validated before a
  CVXPY problem is constructed (finite, positive where physical, ordered
  comfort bounds, unique monotonic timezone-aware index, finite values,
  minimum horizon).
* Dynamics use **exact zero-order-hold (ZOH) discretization**
  (``expm`` of the augmented system matrix), so there is no forward-Euler
  stability limit to violate; the discretization is exact for the piecewise
  constant inputs the optimizer produces.
* Solver failure never returns a numeric-looking schedule: non-optimal
  statuses raise :class:`SolverError` / :class:`InfeasibleProblemError`, and
  even optimal solutions are re-checked for control, temperature and dynamic
  residuals before being returned.
* The reported ``Cost`` column uses exactly the same definition as the
  objective's cost term (``Price * dt * (Q_heater*u + Q_cooling*c)``), so it
  is independently recomputable from the returned outputs.
"""

from __future__ import annotations

import logging
from typing import Tuple

import cvxpy as cp
import numpy as np
import pandas as pd
from scipy.linalg import expm

from .errors import (
    ConfigurationError,
    InfeasibleProblemError,
    InvalidInputError,
    SolverError,
)

logger = logging.getLogger(__name__)

#: Tolerances used when re-checking a returned solver solution.
CONTROL_TOL = 1e-6
TEMPERATURE_TOL = 1e-3
DYNAMICS_TOL = 1e-4

REQUIRED_COLUMNS = ("ExteriorTemperature", "Price")


def _as_finite(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"{name} must be a finite number, got {value!r}."
        ) from exc
    if not np.isfinite(number):
        raise ConfigurationError(
            f"{name} must be a finite number, got {value!r}."
        )
    return number


class House:
    """Thermal properties and comfort constraints of a house.

    All parameters are validated on construction; invalid physical values
    raise :class:`~strom.errors.ConfigurationError` with an actionable
    message instead of failing later inside the solver.

    Attributes:
        C_air: Heat capacity of air [kWh/°C], > 0.
        C_wall: Heat capacity of walls [kWh/°C], > 0.
        R_interior: Thermal resistance between air and walls [°C/kW], > 0.
        R_exterior: Thermal resistance between walls and exterior [°C/kW], > 0.
        Q_heater: Maximum heating power [kW], >= 0.
        Q_cooling: Maximum cooling power [kW], >= 0.
        freq: Control interval as a pandas-parseable offset (e.g. '1h').
        T_min: Minimum allowed interior temperature [°C].
        T_max: Maximum allowed interior temperature [°C].
        T_interior_init: Initial interior temperature [°C], within comfort.
        T_wall_init: Initial wall temperature [°C].
        P_base: Fixed grid tariff added to prices [€/kWh], >= 0.
    """

    def __init__(self,
                 C_air: float = 0.56,
                 C_wall: float = 3.5,
                 R_interior: float = 1.0,
                 R_exterior: float = 6.06,
                 Q_heater: float = 2.0,
                 Q_cooling: float = 0.0,
                 T_min: float = 18.0,
                 T_max: float = 24.0,
                 T_interior_init: float = 18.5,
                 T_wall_init: float = 18.5,
                 P_base: float = 0.01,
                 freq: str = '1h') -> None:
        self.C_air = _as_finite(C_air, "C_air")
        self.C_wall = _as_finite(C_wall, "C_wall")
        self.R_interior = _as_finite(R_interior, "R_interior")
        self.R_exterior = _as_finite(R_exterior, "R_exterior")
        for name in ("C_air", "C_wall", "R_interior", "R_exterior"):
            if getattr(self, name) <= 0.0:
                raise ConfigurationError(
                    f"{name} must be > 0 (zero would divide by zero in the "
                    f"thermal model), got {getattr(self, name)!r}."
                )

        self.Q_heater = _as_finite(Q_heater, "Q_heater")
        self.Q_cooling = _as_finite(Q_cooling, "Q_cooling")
        self.P_base = _as_finite(P_base, "P_base")
        for name in ("Q_heater", "Q_cooling", "P_base"):
            if getattr(self, name) < 0.0:
                raise ConfigurationError(
                    f"{name} must be >= 0, got {getattr(self, name)!r}."
                )

        self.T_min = _as_finite(T_min, "T_min")
        self.T_max = _as_finite(T_max, "T_max")
        self.T_interior_init = _as_finite(T_interior_init, "T_interior_init")
        self.T_wall_init = _as_finite(T_wall_init, "T_wall_init")
        if self.T_min >= self.T_max:
            raise ConfigurationError(
                f"T_min ({self.T_min}) must be below T_max ({self.T_max})."
            )
        if not self.T_min <= self.T_interior_init <= self.T_max:
            raise ConfigurationError(
                f"T_interior_init ({self.T_interior_init}) must be inside the "
                f"comfort bounds [{self.T_min}, {self.T_max}], otherwise the "
                "initial condition is infeasible."
            )

        try:
            dt = pd.to_timedelta(freq)
        except ValueError as exc:
            raise ConfigurationError(
                f"freq must be a pandas-parseable offset like '1h' or "
                f"'15min', got {freq!r}."
            ) from exc
        if pd.isna(dt) or dt <= pd.Timedelta(0):
            raise ConfigurationError(
                f"freq must be a positive interval, got {freq!r}."
            )
        self.freq = freq
        self._dt_hours = dt.total_seconds() / 3600.0

    @property
    def dt_hours(self) -> float:
        """Control interval length in hours."""
        return self._dt_hours


def smooth_temperature(data: pd.Series,
                       window_hours: float,
                       dt: float) -> np.ndarray:
    """Smooth temperature data using a centered rolling mean.

    Args:
        data: Temperature values.
        window_hours: Smoothing window in hours.
        dt: Time step in hours.

    Returns:
        Smoothed temperature array of the same length as ``data``.
    """
    if not np.isfinite(window_hours) or window_hours <= 0:
        raise InvalidInputError(
            f"window_hours must be positive, got {window_hours!r}."
        )
    if not np.isfinite(dt) or dt <= 0:
        raise InvalidInputError(f"dt must be positive, got {dt!r}.")
    window_size = max(1, round(window_hours / dt))
    data_series = pd.Series(data)
    smoothed = data_series.rolling(
        window=window_size, min_periods=1, center=True).mean()
    return smoothed.to_numpy()


def calculate_baseline_target(ext_temp_series: pd.Series,
                              T_min: float,
                              T_max: float,
                              resolution_hours: float) -> np.ndarray:
    """Target temperature profile: 24h-smoothed exterior temperature clipped
    to the comfort band."""
    smoothed_ext = smooth_temperature(ext_temp_series, 24, resolution_hours)
    return np.clip(smoothed_ext, T_min, T_max)


def _validate_input_df(temp_price_df: pd.DataFrame) -> pd.DataFrame:
    """Validate optimizer input and return a normalized copy.

    Rejects empty data, missing columns, duplicated or naive indexes,
    non-finite values and horizons that are too short to optimize. The input
    is never mutated.
    """
    if not isinstance(temp_price_df, pd.DataFrame):
        raise InvalidInputError(
            "Optimizer input must be a pandas DataFrame with columns "
            f"{list(REQUIRED_COLUMNS)}, got {type(temp_price_df).__name__}."
        )
    missing = [c for c in REQUIRED_COLUMNS if c not in temp_price_df.columns]
    if missing:
        raise InvalidInputError(
            f"Optimizer input is missing required column(s) {missing}; "
            f"present columns: {list(temp_price_df.columns)}."
        )
    if len(temp_price_df) < 2:
        raise InvalidInputError(
            "Need at least two input rows to build a heating schedule; got "
            f"{len(temp_price_df)}."
        )
    index = temp_price_df.index
    if not isinstance(index, pd.DatetimeIndex):
        raise InvalidInputError(
            "Optimizer input must be indexed by timestamps "
            "(pd.DatetimeIndex)."
        )
    if index.tz is None:
        raise InvalidInputError(
            "Optimizer input timestamps must be timezone-aware; localize "
            "them (e.g. to UTC) before optimizing."
        )
    if index.has_duplicates:
        n = int(index.duplicated().sum())
        raise InvalidInputError(
            f"Optimizer input contains {n} duplicated timestamp(s); "
            "aggregate or drop duplicates first."
        )

    df = temp_price_df.copy()
    if not index.is_monotonic_increasing:
        df = df.sort_index()

    values = df.loc[:, REQUIRED_COLUMNS].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        bad = df.loc[~np.isfinite(df.loc[:, REQUIRED_COLUMNS]).all(axis=1)]
        first = bad.index.min()
        raise InvalidInputError(
            f"Optimizer input contains non-finite values "
            f"(first at index {first!r}); clean the data first."
        )
    return df


def _resample_to_freq(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Align input to the control frequency without inventing market data.

    * Upsampling (control interval shorter than the source step, e.g. the
      case studies' ``15min`` grids): exterior temperature is time-
      interpolated and prices are forward-filled, i.e. treated as the step
      function market intervals actually are.
    * Otherwise no filling happens: missing values are source gaps and are
      rejected with an actionable error. Rows before the first / after the
      last observation (bucket-alignment artifacts) are trimmed.
    """
    src_step = df.index.to_series().diff().dropna().median()
    upsampling = src_step > pd.to_timedelta(freq)
    out = df.resample(freq).asfreq()

    valid = out[list(REQUIRED_COLUMNS)].notna().any(axis=1)
    out = out.loc[valid.idxmax():valid.iloc[::-1].idxmax()]

    if upsampling:
        out["ExteriorTemperature"] = out["ExteriorTemperature"].interpolate(
            method="time", limit_area="inside")
        out["Price"] = out["Price"].ffill()
    return out


def zero_order_hold_matrices(A: np.ndarray, B: np.ndarray,
                             dt: float) -> Tuple[np.ndarray, np.ndarray]:
    """Exact ZOH discretization: ``(Ad, Bd)`` for ``x[k+1] = Ad x[k] + Bd u[k]``
    with inputs held constant over a step of ``dt`` hours."""
    n, m = A.shape[0], B.shape[1]
    M = np.zeros((n + m, n + m))
    M[:n, :n] = A
    M[:n, n:] = B
    E = expm(M * dt)
    return E[:n, :n], E[:n, n:]


def _build_dynamics_matrices(house: House) -> Tuple[np.ndarray, np.ndarray]:
    """Continuous-time system and input matrices.

    State: ``x = [T_interior, T_wall]``.
    Inputs: ``[heater_power_fraction, cooling_power_fraction, T_exterior]``.
    """
    A = np.array([
        [-1.0 / (house.R_interior * house.C_air),
         1.0 / (house.R_interior * house.C_air)],
        [1.0 / (house.R_interior * house.C_wall),
         -((1.0 / house.R_interior) + (1.0 / house.R_exterior)) / house.C_wall],
    ])
    B = np.array([
        [house.Q_heater / house.C_air, -house.Q_cooling / house.C_air, 0.0],
        [0.0, 0.0, 1.0 / (house.R_exterior * house.C_wall)],
    ])
    return A, B


def _check_solution(values: dict, house: House, Ad: np.ndarray,
                    Bd: np.ndarray, T_exterior: np.ndarray) -> None:
    """Re-check a solver solution; raise :class:`SolverError` on violation."""
    u = np.asarray(values["HeaterOutput"], dtype=float)
    c = np.asarray(values["CoolingOutput"], dtype=float)
    X = np.asarray(values["_T"], dtype=float)
    if not (np.isfinite(u).all() and np.isfinite(c).all()
            and np.isfinite(X).all()):
        raise SolverError(
            "Solver returned non-finite values; refusing to use the schedule."
        )
    if u.min() < -CONTROL_TOL or u.max() > 1.0 + CONTROL_TOL:
        raise SolverError(
            f"Heater output violates [0, 1] bounds: range "
            f"[{u.min():.6f}, {u.max():.6f}]."
        )
    if c.min() < -CONTROL_TOL or c.max() > 1.0 + CONTROL_TOL:
        raise SolverError(
            f"Cooling output violates [0, 1] bounds: range "
            f"[{c.min():.6f}, {c.max():.6f}]."
        )
    interior = X[0, :]
    if (interior < house.T_min - TEMPERATURE_TOL).any() or (
            interior > house.T_max + TEMPERATURE_TOL).any():
        raise SolverError(
            "Interior temperature violates comfort bounds "
            f"[{house.T_min}, {house.T_max}] "
            f"(range [{interior.min():.3f}, {interior.max():.3f}])."
        )
    # Dynamic residual: x[k+1] must equal the ZOH prediction.
    predicted = (Ad @ X[:, :-1]
                 + np.outer(Bd[:, 0], u[:-1])
                 + np.outer(Bd[:, 1], c[:-1])
                 + np.outer(Bd[:, 2], T_exterior[:-1]))
    residual = np.abs(predicted - X[:, 1:])
    scale = np.maximum(1.0, np.abs(X[:, :-1]))
    if (residual / scale > DYNAMICS_TOL).any():
        raise SolverError(
            f"Dynamic residual up to {residual.max():.6f} exceeds tolerance "
            f"{DYNAMICS_TOL}; the returned schedule is not self-consistent."
        )


def find_heating_output(temp_price_df: pd.DataFrame,
                        house: House,
                        heating_mode: str,
                        verbose: bool = False) -> pd.DataFrame:
    """Optimize heating/cooling output based on prices and exterior temperature.

    Args:
        temp_price_df: DataFrame with columns 'ExteriorTemperature' and
            'Price', timezone-aware unique monotonic DatetimeIndex, finite
            values.
        house: Validated :class:`House`.
        heating_mode: 'optimal' minimizes electricity cost; 'baseline'
            tracks a comfort target with a small cost term.
        verbose: Pass through to the solver (default off).

    Returns:
        DataFrame with the schedule: 'HeaterOutput', 'CoolingOutput',
        'InteriorTemperature', 'WallTemperature' and a 'Cost' column equal to
        ``Price * dt * (Q_heater * u + Q_cooling * c)``.

    Raises:
        InvalidInputError: malformed or non-finite input.
        InfeasibleProblemError: comfort/initial conditions cannot be met.
        SolverError: solver failure or a solution that fails validation.
    """
    state_df = _validate_input_df(temp_price_df)

    dt = house.dt_hours
    state_df = _resample_to_freq(state_df, house.freq)
    if state_df.loc[:, list(REQUIRED_COLUMNS)].isna().values.any():
        gaps = state_df.loc[
            state_df[REQUIRED_COLUMNS[0]].isna()
            | state_df[REQUIRED_COLUMNS[1]].isna()].index[:5]
        raise InvalidInputError(
            "Optimizer input has missing values that cannot be filled "
            f"(first gap at {gaps.min()}); provide a complete horizon "
            "instead of relying on interpolation."
        )

    state_df['Price'] = state_df['Price'] + house.P_base

    time_steps = len(state_df)
    T_exterior = state_df["ExteriorTemperature"].to_numpy(dtype=float)
    T_target = calculate_baseline_target(state_df["ExteriorTemperature"],
                                         house.T_min, house.T_max, dt)
    T_differential = 0.2

    heater_output = cp.Variable(time_steps, name="HeaterOutput")
    cooling_output = cp.Variable(time_steps, name="CoolingOutput")
    T = cp.Variable((2, time_steps), name="T")

    constraints = [
        heater_output >= 0.0, heater_output <= 1.0,
        cooling_output >= 0.0, cooling_output <= 1.0,
        T[0, 0] == house.T_interior_init,
        T[1, 0] == house.T_wall_init,
    ]

    A, B = _build_dynamics_matrices(house)
    Ad, Bd = zero_order_hold_matrices(A, B, dt)
    for t in range(time_steps - 1):
        constraints.append(
            T[:, t + 1] == Ad @ T[:, t]
            + Bd[:, 0] * heater_output[t]
            + Bd[:, 1] * cooling_output[t]
            + Bd[:, 2] * T_exterior[t]
        )

    constraints.append(T[0, :] >= house.T_min)
    constraints.append(T[0, :] <= house.T_max)

    # Cost definition shared by the objective and the returned 'Cost' column.
    obj_cost = cp.sum(cp.multiply(
        state_df["Price"].to_numpy(),
        dt * (house.Q_heater * heater_output
              + house.Q_cooling * cooling_output)))
    obj_temp = cp.sum(
        cp.abs(T[0, :] - (T_target - T_differential))
        + cp.abs(T[0, :] - (T_target + T_differential)))

    tau = 0.01
    if heating_mode == "optimal":
        objective = cp.Minimize(obj_cost)
    elif heating_mode == "baseline":
        objective = cp.Minimize((1 - tau) * obj_temp + tau * obj_cost)
    else:
        raise InvalidInputError(
            f"Invalid heating mode {heating_mode!r}; use 'optimal' or "
            "'baseline'."
        )

    problem = cp.Problem(objective, constraints)
    try:
        problem.solve(solver=cp.CLARABEL, verbose=verbose)
    except Exception as exc:  # solver-level crash (numerics, licensing, ...)
        raise SolverError(f"Solver raised {type(exc).__name__}: {exc}") from exc

    if problem.status in (cp.INFEASIBLE, cp.INFEASIBLE_INACCURATE):
        raise InfeasibleProblemError(
            "The heating problem is infeasible: comfort bounds cannot be "
            "met with this heater, insulation and initial temperature."
        )
    if problem.status not in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE):
        raise SolverError(
            f"Solver did not find an optimal solution (status: "
            f"{problem.status!r}); no schedule is returned."
        )
    if problem.status == cp.OPTIMAL_INACCURATE:
        logger.warning(
            "Solver reported only an inexact solution; validating strictly."
        )

    values = {
        "HeaterOutput": heater_output.value,
        "CoolingOutput": cooling_output.value,
        "_T": T.value,
    }
    _check_solution(values, house, Ad, Bd, T_exterior)

    state_df['HeaterOutput'] = np.clip(values["HeaterOutput"], 0.0, 1.0)
    state_df['CoolingOutput'] = np.clip(values["CoolingOutput"], 0.0, 1.0)
    state_df['InteriorTemperature'] = values["_T"][0, :]
    state_df['WallTemperature'] = values["_T"][1, :]
    state_df['Cost'] = (
        state_df['Price'] * dt
        * (state_df['HeaterOutput'] * house.Q_heater
           + state_df['CoolingOutput'] * house.Q_cooling)
    )
    return state_df


def compare_output_costs(temp_price_df: pd.DataFrame,
                         house: House) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Compare optimal and baseline heating strategies.

    Raises typed optimization errors if either strategy fails; it never
    returns NaN-filled schedules.
    """
    optimal_state_df = find_heating_output(temp_price_df, house, "optimal")
    baseline_state_df = find_heating_output(temp_price_df, house, "baseline")
    return optimal_state_df, baseline_state_df
