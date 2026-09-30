"""Controller orchestration: discovery -> data -> optimization -> actuation.

Lifecycle rules (audit issue 32):

* Discovery happens first and is validated immediately: a ``None`` result or
  a discovery failure prevents all data fetching, optimization and actuation.
* The device connection is closed **exactly once** after every *successful*
  discovery, on every path (success, expected operational failure, bug),
  via :func:`managed_plug`.
* Only :class:`~strom.errors.StromError` subclasses are treated as expected
  operational failures; the CLI turns them into a logged message and exit
  code 1. Any other exception propagates with its traceback and makes the
  process exit non-zero.
* All injected dependencies have production defaults so tests can fake any
  stage (discovery, data fetch, optimization, commands, state update).
"""

from __future__ import annotations

import asyncio
import logging
import math
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

import pandas as pd

from .control import (
    MAX_ON_SECONDS_DEFAULT,
    Clock,
    MaxOnWatchdog,
    SystemClock,
    execute_plan,
    plan_from_schedule,
)
from .data_utils import get_temp_price_df, interval_price
from .errors import ConfigurationError, DeviceError, StromError
from .optimization_utils import House, find_heating_output
from .plug import PlugCredentials, connect_plug
from .thermal_state import plan_temperature, restore_state, save_state, temperature_plan

logger = logging.getLogger(__name__)

OFF_ATTEMPTS = 3
OFF_TIMEOUT_SECONDS = 10.0
OFF_RETRY_SECONDS = 1.0


@dataclass(frozen=True)
class ControlReport:
    """Outcome of one control cycle, for user-facing run summaries."""

    on_seconds: float
    interval_seconds: float
    estimated_cost_eur: float | None


@dataclass
class ControllerDeps:
    """Injection points for the control cycle.

    Attributes:
        discover: async callable ``(PlugCredentials) -> plug|None``.
        fetch_data: callable ``() -> DataFrame`` with weather and prices.
        optimize: callable ``(df, house, mode) -> schedule DataFrame``.
        clock: deterministic-injectable time source for actuation.
        max_on_seconds: independent watchdog limit.
    """

    discover: Callable[[PlugCredentials], Awaitable] = connect_plug
    fetch_data: Callable[[], pd.DataFrame] = field(
        default_factory=lambda: get_temp_price_df,
    )
    optimize: Callable[[pd.DataFrame, House, str], pd.DataFrame] = (
        lambda df, house, mode: find_heating_output(df, house, mode)
    )
    clock: Clock = field(default_factory=SystemClock)
    max_on_seconds: float = MAX_ON_SECONDS_DEFAULT
    interval_seconds: float = 3600.0
    state_path: Path | None = None


@asynccontextmanager
async def managed_plug(dev):
    """Close the device connection exactly once, on every exit path."""
    try:
        yield dev
    finally:
        try:
            await dev.async_close()
        except Exception:
            logger.warning(
                "Failed to close the device connection cleanly.",
                exc_info=True,
            )


async def _device_command(dev, operation: str) -> None:
    """Run a plug command, mapping any failure to :class:`DeviceError`."""
    try:
        await getattr(dev, operation)()
    except StromError:
        raise
    except Exception as exc:
        raise DeviceError(f"Smart plug command {operation!r} failed.") from exc


async def _ensure_off(dev) -> None:
    for attempt in range(OFF_ATTEMPTS):
        try:
            async with asyncio.timeout(OFF_TIMEOUT_SECONDS):
                await _device_command(dev, "turn_off")
                await _device_command(dev, "update")
                if getattr(dev, "is_on", None) is not False:
                    raise DeviceError("The smart plug did not confirm that it is OFF.")
            return
        except (DeviceError, TimeoutError) as exc:
            if attempt + 1 == OFF_ATTEMPTS:
                raise DeviceError(
                    "Could not confirm the heater is OFF after three attempts."
                ) from exc
            logger.warning("Heater shutdown was not confirmed; retrying.")
            await asyncio.sleep(OFF_RETRY_SECONDS)


async def _finish_shutdown(dev, watchdog: MaxOnWatchdog | None) -> None:
    async def finish():
        try:
            await _ensure_off(dev)
            if watchdog is not None:
                watchdog.notify_off()
        finally:
            if watchdog is not None:
                await watchdog.stop()

    task = asyncio.create_task(finish())
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def run_control_cycle(
    deps: ControllerDeps,
    credentials: PlugCredentials,
    house: House,
) -> ControlReport:
    """Run one full control cycle with strict cleanup semantics."""
    if not credentials.device_ip:
        raise DeviceError("No device IP configured; cannot discover the plug.")

    # Discovery first, validated immediately: nothing else may run unless the
    # device is actually reachable.
    try:
        dev = await deps.discover(credentials)
    except StromError:
        raise
    except Exception as exc:
        raise DeviceError(
            f"Failed to discover device at {credentials.device_ip!r}."
        ) from exc

    if dev is None:
        raise DeviceError(
            "Device discovery returned no device; check DEVICEIP and, if the "
            "plug requires one, the Tapo account. No data was fetched and "
            "nothing was actuated."
        )

    async with managed_plug(dev):
        watchdog = None
        configured_house = house
        try:
            data = deps.fetch_data()
            if deps.state_path is not None:
                house = restore_state(
                    deps.state_path, house, credentials.device_ip,
                    float(data["ExteriorTemperature"].iloc[0]),
                )
            schedule = deps.optimize(data, house, "optimal")
            plan = plan_from_schedule(schedule, deps.interval_seconds)
            if house is not None and len(schedule) >= 2:
                plan = temperature_plan(
                    house, float(schedule["ExteriorTemperature"].iloc[0]),
                    float(schedule["InteriorTemperature"].iloc[1]), deps.interval_seconds,
                )
            if any(s.on and s.seconds > deps.max_on_seconds for s in plan.segments):
                raise DeviceError(
                    "The relay plan exceeds the maximum continuous ON time; "
                    "shorten the interval."
                )
            logger.info(
                "Actuation plan: %.0fs ON / %.0fs OFF over %.0fs.",
                plan.total_on_seconds,
                plan.interval_seconds - plan.total_on_seconds,
                plan.interval_seconds,
            )
            estimated_cost = _first_interval_cost(schedule)
            if house is not None:
                estimated_cost = _plan_cost(data, schedule, house, plan)
            watchdog = _make_watchdog(deps, dev)
            watchdog.start()
            if deps.state_path is not None:
                # An interrupted ON interval cannot leave a reusable estimate.
                deps.state_path.unlink(missing_ok=True)
            await _execute(deps, dev, plan, watchdog)
        finally:
            await _finish_shutdown(dev, watchdog)
        if deps.state_path is not None:
            try:
                save_state(
                    deps.state_path, configured_house, credentials.device_ip,
                    plan_temperature(
                        house, float(schedule["ExteriorTemperature"].iloc[0]), plan
                    ),
                )
            except OSError as exc:
                raise ConfigurationError(
                    "Could not save the temperature estimate for the next run."
                ) from exc
        logger.info(
            "Device state after cycle: %s",
            "ON" if getattr(dev, "is_on", False) else "OFF",
        )
        return ControlReport(
            on_seconds=plan.total_on_seconds,
            interval_seconds=plan.interval_seconds,
            estimated_cost_eur=estimated_cost,
        )


def _first_interval_cost(schedule: pd.DataFrame) -> float | None:
    """Estimated electricity cost of the actuated interval, when available."""
    if "Cost" not in getattr(schedule, "columns", ()):
        return None
    try:
        cost = float(schedule["Cost"].iloc[0])
    except (IndexError, TypeError, ValueError):
        return None
    return cost if math.isfinite(cost) else None


def _plan_cost(data: pd.DataFrame, schedule: pd.DataFrame, house: House, plan) -> float:
    market = data.attrs.get("market_prices")
    if market is None:
        return float(schedule["Price"].iloc[0]) * house.Q_heater * plan.total_on_seconds / 3600
    elapsed = 0.0
    cost = 0.0
    for segment in plan.segments:
        if segment.on:
            start = schedule.index[0] + pd.Timedelta(seconds=elapsed)
            price = interval_price(market, start, segment.seconds) + house.P_base
            cost += price * house.Q_heater * segment.seconds / 3600
        elapsed += segment.seconds
    return cost


def _make_watchdog(deps: ControllerDeps, dev) -> MaxOnWatchdog:
    return MaxOnWatchdog(dev, max_on_seconds=deps.max_on_seconds,
                         clock=deps.clock)


async def _execute(deps: ControllerDeps, dev, plan, watchdog: MaxOnWatchdog) -> None:
    try:
        await execute_plan(dev, plan, deps.clock, watchdog)
    except StromError:
        raise
    except Exception as exc:
        raise DeviceError("Failed to execute the actuation plan.") from exc
