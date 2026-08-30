"""Shared deterministic fixtures: fake plug, manual clock, synthetic data.

No fixture here touches the network, the filesystem outside ``tmp_path``,
secrets, or the wall clock.
"""

from __future__ import annotations

import asyncio
from typing import Callable

import numpy as np
import pandas as pd
import pytest

from strom.control import Clock


class ManualClock:
    """Deterministic clock: ``sleep`` advances instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)  # yield to the event loop, stays deterministic

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakePlug:
    """In-memory smart plug recording every command."""

    def __init__(self) -> None:
        self.is_on: bool | None = None
        self.calls: list[str] = []
        self.closed = 0
        self.fail_on: Callable[[str], Exception] | None = None

    async def turn_on(self) -> None:
        self.calls.append("turn_on")
        if self.fail_on and (exc := self.fail_on("turn_on")):
            raise exc
        self.is_on = True

    async def turn_off(self) -> None:
        self.calls.append("turn_off")
        if self.fail_on and (exc := self.fail_on("turn_off")):
            raise exc
        self.is_on = False

    async def update(self) -> None:
        self.calls.append("update")

    async def async_close(self) -> None:
        self.calls.append("async_close")
        self.closed += 1


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def plug() -> FakePlug:
    return FakePlug()


def make_schedule(
    heater: list[float] | np.ndarray,
    index: pd.DatetimeIndex | None = None,
    **extra_columns,
) -> pd.DataFrame:
    """Build a solver-shaped schedule DataFrame with a UTC hourly index."""
    n = len(heater)
    if index is None:
        index = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    data = {
        "ExteriorTemperature": np.full(n, 10.0),
        "Price": np.full(n, 0.1),
        "HeaterOutput": np.asarray(heater, dtype=float),
        "CoolingOutput": np.zeros(n),
        "InteriorTemperature": np.full(n, 20.0),
        "WallTemperature": np.full(n, 19.0),
        "Cost": np.zeros(n),
    }
    data.update(extra_columns)
    return pd.DataFrame(data, index=index)
