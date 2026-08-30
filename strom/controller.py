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

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
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
from .data_utils import get_temp_price_df
from .errors import DeviceError, StromError
from .optimization_utils import House, find_heating_output

logger = logging.getLogger(__name__)


async def _default_discover(device_ip, email, password):
    from kasa import Discover

    return await Discover.discover_single(device_ip, username=email,
                                          password=password)


@dataclass
class ControllerDeps:
    """Injection points for the control cycle.

    Attributes:
        discover: async callable ``(device_ip, email, password) -> plug|None``.
        fetch_data: callable ``() -> DataFrame`` with weather and prices.
        optimize: callable ``(df, house, mode) -> schedule DataFrame``.
        clock: deterministic-injectable time source for actuation.
        max_on_seconds: independent watchdog limit.
    """

    discover: Callable[[str, str, str], Awaitable] = _default_discover
    fetch_data: Callable[[], pd.DataFrame] = field(
        default_factory=lambda: get_temp_price_df,
    )
    optimize: Callable[[pd.DataFrame, House, str], pd.DataFrame] = (
        lambda df, house, mode: find_heating_output(df, house, mode)
    )
    clock: Clock = field(default_factory=SystemClock)
    max_on_seconds: float = MAX_ON_SECONDS_DEFAULT
    interval_seconds: float = 3600.0
    horizon_hours: int = 24


@asynccontextmanager
async def managed_plug(dev):
    """Close the device connection exactly once, on every exit path."""
    closed = False
    try:
        yield dev
    finally:
        if not closed:
            closed = True
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


async def run_control_cycle(
    deps: ControllerDeps,
    email: str,
    password: str,
    device_ip: str,
    house: House,
) -> None:
    """Run one full control cycle with strict cleanup semantics."""
    if not device_ip:
        raise DeviceError("No device IP configured; cannot discover the plug.")

    # Discovery first, validated immediately: nothing else may run unless the
    # device is actually reachable.
    try:
        dev = await deps.discover(device_ip, email, password)
    except StromError:
        raise
    except Exception as exc:
        raise DeviceError(f"Failed to discover device at {device_ip!r}.") from exc

    if dev is None:
        raise DeviceError(
            "Device discovery returned no device; check DEVICEIP, email and "
            "password. No data was fetched and nothing was actuated."
        )

    async with managed_plug(dev):
        # --- data -------------------------------------------------------
        data = deps.fetch_data()
        # --- optimization ------------------------------------------------
        schedule = deps.optimize(data, house, "optimal")
        # --- control policy ----------------------------------------------
        plan = plan_from_schedule(schedule, deps.interval_seconds)
        logger.info(
            "Actuation plan: %.0fs ON / %.0fs OFF over %.0fs.",
            plan.total_on_seconds,
            plan.interval_seconds - plan.total_on_seconds,
            plan.interval_seconds,
        )
        # --- actuation ----------------------------------------------------
        watchdog = _make_watchdog(deps, dev)
        watchdog.start()
        try:
            if plan.total_on_seconds > 0:
                watchdog.notify_on()
            await _execute(deps, dev, plan)
            await _device_command(dev, "update")
        finally:
            watchdog.notify_off()
            await watchdog.stop()
        logger.info(
            "Device state after cycle: %s",
            "ON" if getattr(dev, "is_on", False) else "OFF",
        )


def _make_watchdog(deps: ControllerDeps, dev) -> MaxOnWatchdog:
    return MaxOnWatchdog(dev, max_on_seconds=deps.max_on_seconds,
                         clock=deps.clock)


async def _execute(deps: ControllerDeps, dev, plan) -> None:
    try:
        await execute_plan(dev, plan, deps.clock)
    except StromError:
        raise
    except Exception as exc:
        raise DeviceError("Failed to execute the actuation plan.") from exc
