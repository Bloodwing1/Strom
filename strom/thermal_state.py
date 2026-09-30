"""Carry model estimates between CLI processes using the same plug and settings."""

from __future__ import annotations

import copy
import inspect
import json
import math
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .control import MIN_PULSE_SECONDS, ActuationPlan, ActuationSegment
from .errors import ConfigurationError, InvalidScheduleError
from .optimization_utils import (
    TEMPERATURE_TOL, House, _build_dynamics_matrices, zero_order_hold_matrices,
)

STATE_FILE = "thermal_state.json"


def _settings(house: House) -> dict:
    return {key: getattr(house, key) for key in inspect.signature(House).parameters}


def advance_temperature(
    house: House, exterior: float, seconds: float, output: float = 0.0,
) -> tuple[float, float]:
    A, B = _build_dynamics_matrices(house)
    Ad, Bd = zero_order_hold_matrices(A, B, seconds / 3600.0)
    state = Ad @ np.array([house.T_interior_init, house.T_wall_init])
    state += Bd @ np.array([output, 0.0, exterior])
    return float(state[0]), float(state[1])


def plan_temperature(house: House, exterior: float, plan: ActuationPlan) -> tuple[float, float]:
    estimate = copy.copy(house)
    for segment in plan.segments:
        estimate.T_interior_init, estimate.T_wall_init = advance_temperature(
            estimate, exterior, segment.seconds, float(segment.on)
        )
    return estimate.T_interior_init, estimate.T_wall_init


def _pulse_plan(duty: float, seconds: float, pulses: int) -> ActuationPlan:
    if duty == 0:
        return ActuationPlan((ActuationSegment(False, seconds),), seconds)
    period = seconds / pulses
    on_seconds = min(period, max(MIN_PULSE_SECONDS, duty * period))
    if on_seconds == period:
        return ActuationPlan((ActuationSegment(True, seconds),), seconds)
    segments = []
    for _ in range(pulses):
        segments.append(ActuationSegment(True, on_seconds))
        if on_seconds < period:
            segments.append(ActuationSegment(False, period - on_seconds))
    return ActuationPlan(tuple(segments), seconds)


def _within_comfort(house: House, exterior: float, plan: ActuationPlan) -> bool:
    estimate = copy.copy(house)
    lower = min(house.T_min, house.T_interior_init) - TEMPERATURE_TOL
    upper = max(house.T_max, house.T_interior_init) + TEMPERATURE_TOL

    def rate(state: tuple[float, float], output: float) -> float:
        return ((state[1] - state[0]) / house.R_interior + house.Q_heater * output) / (
            house.C_air
        )

    for segment in plan.segments:
        initial = (estimate.T_interior_init, estimate.T_wall_init)
        output = float(segment.on)
        final = advance_temperature(estimate, exterior, segment.seconds, output)
        temperatures = [initial[0], final[0]]
        # The two-state model has at most one interior extremum per constant input.
        if rate(initial, output) * rate(final, output) < 0:
            peak_time = brentq(
                lambda seconds: rate(
                    advance_temperature(estimate, exterior, seconds, output), output
                ), 0, segment.seconds,
            )
            temperatures.append(advance_temperature(estimate, exterior, peak_time, output)[0])
        if min(temperatures) < lower or max(temperatures) > upper:
            return False
        estimate.T_interior_init, estimate.T_wall_init = final
    return True


def temperature_plan(
    house: House, exterior: float, target: float, seconds: float,
) -> ActuationPlan:
    """Match the next temperature to real relay pulses and check every extremum."""
    target = min(house.T_max, max(house.T_min, target))
    if advance_temperature(house, exterior, seconds)[0] >= target - TEMPERATURE_TOL:
        off = _pulse_plan(0, seconds, 1)
        if _within_comfort(house, exterior, off):
            return off
    maximum_pulses = max(1, int(seconds / MIN_PULSE_SECONDS))
    pulses = 1
    while True:
        low, high = 0.0, 1.0
        if (plan_temperature(house, exterior, _pulse_plan(high, seconds, pulses))[0]
                < target - TEMPERATURE_TOL):
            break
        for _ in range(32):
            duty = (low + high) / 2
            plan = _pulse_plan(duty, seconds, pulses)
            if plan_temperature(house, exterior, plan)[0] >= target:
                high = duty
            else:
                low = duty
        plan = _pulse_plan(high, seconds, pulses)
        if _within_comfort(house, exterior, plan):
            return plan
        if pulses == maximum_pulses:
            break
        pulses = min(pulses * 2, maximum_pulses)
    raise InvalidScheduleError(
        "No relay plan can meet the temperature bounds with the minimum "
        "pulse duration; shorten the control interval or check the house parameters."
    )


def restore_state(
    path: Path, house: House, device_ip: str, exterior: float,
    *, now: pd.Timestamp | None = None,
) -> House:
    if not path.exists():
        return house
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["device_ip"] != device_ip or payload["settings"] != _settings(house):
            return house
        saved_at = pd.Timestamp(payload["saved_at"])
        interior, wall = float(payload["interior"]), float(payload["wall"])
        now = now if now is not None else pd.Timestamp.now(tz="UTC")
        if saved_at.tz is None or saved_at > now or not all(
            math.isfinite(value) for value in (interior, wall)
        ):
            raise ValueError("invalid temperatures or timestamp")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"Could not read the temperature estimate in {path}; remove it "
            "and set the starting temperatures in house_config.json."
        ) from exc
    estimate = copy.copy(house)
    estimate.T_interior_init, estimate.T_wall_init = interior, wall
    estimate.T_interior_init, estimate.T_wall_init = advance_temperature(
        estimate, exterior, (now - saved_at).total_seconds()
    )
    return estimate


def save_state(
    path: Path, house: House, device_ip: str, temperatures: tuple[float, float],
    *, now: pd.Timestamp | None = None,
) -> None:
    payload = {
        "device_ip": device_ip,
        "settings": _settings(house),
        "saved_at": str(now if now is not None else pd.Timestamp.now(tz="UTC")),
        "interior": temperatures[0],
        "wall": temperatures[1],
    }
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(raw, path)
    finally:
        Path(raw).unlink(missing_ok=True)
