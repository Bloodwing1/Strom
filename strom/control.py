"""Actuation policy: turning optimizer output into safe smart-plug commands.

Control policy (audit issue 31)
-------------------------------
The optimizer emits fractional heater power in ``[0, 1]``. A smart plug can
only be ON or OFF, so Strom uses **bounded duty-cycle control**: within each
control interval of length ``interval_seconds`` the plug is switched ON for
exactly ``duty_fraction * interval_seconds`` seconds and OFF for the rest.

The on-time is deliberately bounded:

* values that are not finite (``NaN``, ``inf``), are negative, or greater
  than 1 are **rejected** with :class:`ActuationError` before the plug is
  touched;
* a duty of exactly ``0`` never switches the plug on;
* a *tiny positive* duty (on-time below the minimum relay pulse width) is
  rounded up to ``min_pulse_seconds`` so the relay is not chattered;
* the on-time is capped at the interval length.

Schedules that are empty, missing the ``HeaterOutput`` column, or contain
non-finite / out-of-range values raise before any plan can be built, so a
failed solve can never actuate the plug.

The :class:`MaxOnWatchdog` is an independent safety net: it forces the plug
OFF when it has been continuously ON for longer than ``max_on_seconds``,
regardless of what the optimizer or controller believes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from .errors import InvalidScheduleError

logger = logging.getLogger(__name__)

#: Smallest on-pulse the relay is given. Avoids relay chatter for tiny duties.
MIN_PULSE_SECONDS = 60.0

#: Default independent maximum continuous on-time before forced shutdown.
MAX_ON_SECONDS_DEFAULT = 3 * 3600.0

REQUIRED_OUTPUT_COLUMN = "HeaterOutput"


class Clock(Protocol):
    """Time source used by the actuation code; injectable for tests."""

    def monotonic(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """Wall-clock implementation of :class:`Clock`."""

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass(frozen=True)
class ActuationSegment:
    """One plug state held for ``seconds``."""

    on: bool
    seconds: float


@dataclass(frozen=True)
class ActuationPlan:
    """An ordered, exact duty-cycle plan covering one control interval.

    The plan is the single representation of the control policy: the plug is
    only ever commanded from a validated plan, never directly from raw
    optimizer output.
    """

    segments: tuple[ActuationSegment, ...]
    interval_seconds: float

    @property
    def total_on_seconds(self) -> float:
        return sum(s.seconds for s in self.segments if s.on)

    @property
    def total_seconds(self) -> float:
        return sum(s.seconds for s in self.segments)


def resolve_actuation(
    output: float,
    interval_seconds: float,
    min_pulse_seconds: float = MIN_PULSE_SECONDS,
) -> ActuationPlan:
    """Convert one fractional heater output into a bounded duty-cycle plan.

    Raises:
        ActuationError: if ``output`` is not finite or outside ``[0, 1]``,
            or if the interval is not positive.
    """
    interval_seconds = float(interval_seconds)
    if not interval_seconds > 0.0 or not pd.api.types.is_scalar(interval_seconds):
        raise InvalidScheduleError(
            f"Control interval must be positive, got {interval_seconds!r}."
        )

    value = float(output)
    if value != value:  # NaN
        raise InvalidScheduleError(
            "Heater output is NaN; refusing to actuate. Re-run the optimizer."
        )
    if value in (float("inf"), float("-inf")):
        raise InvalidScheduleError(
            f"Heater output is non-finite ({value}); refusing to actuate."
        )
    if not 0.0 <= value <= 1.0:
        raise InvalidScheduleError(
            f"Heater output {value!r} outside [0, 1]; refusing to actuate."
        )

    if value == 0.0:
        return ActuationPlan(
            segments=(ActuationSegment(on=False, seconds=interval_seconds),),
            interval_seconds=interval_seconds,
        )

    on_seconds = value * interval_seconds
    # Bounded duty cycle: clamp into [min_pulse, interval].
    on_seconds = min(max(on_seconds, min_pulse_seconds), interval_seconds)

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def plan_from_schedule(
    schedule: pd.DataFrame,
    interval_seconds: float,
    min_pulse_seconds: float = MIN_PULSE_SECONDS,
    index: int = 0,
) -> ActuationPlan:
    """Build the actuation plan for interval ``index`` of a solver schedule.

    The schedule is only *read*; solver failures must raise before this
    function is called, and any unusable value here also raises, so the plug
    is never driven by ambiguous data.
    """
    if schedule is None or len(schedule) == 0:
        raise InvalidScheduleError(
            "Schedule is empty; refusing to actuate. Check the optimizer run."
        )
    if REQUIRED_OUTPUT_COLUMN not in schedule.columns:
        raise InvalidScheduleError(
            f"Schedule is missing the {REQUIRED_OUTPUT_COLUMN!r} column; "
            "refusing to actuate."
        )
    if not 0 <= index < len(schedule):
        raise InvalidScheduleError(
            f"Interval index {index} out of range for schedule of length "
            f"{len(schedule)}."
        )

    raw = schedule[REQUIRED_OUTPUT_COLUMN].iloc[index]
    if pd.isna(raw):
        raise InvalidScheduleError(
            "Heater output is NaN (solver failure?); refusing to actuate."
        )
    return resolve_actuation(float(raw), interval_seconds, min_pulse_seconds)


async def execute_plan(
    plug,
    plan: ActuationPlan,
    clock: Clock,
) -> None:
    """Execute a plan by switching the plug and sleeping between segments."""
    for segment in plan.segments:
        if segment.on:
            await plug.turn_on()
        else:
            await plug.turn_off()
        await clock.sleep(segment.seconds)


class MaxOnWatchdog:
    """Independent maximum-on safety timer.

    The watchdog keeps its own belief about whether the plug is ON (fed via
    :meth:`notify_on` / :meth:`notify_off`) and forces the plug OFF if that
    state persists for more than ``max_on_seconds``. It never consults the
    optimizer, so a stale or crashed controller cannot leave the heater on
    indefinitely.
    """

    def __init__(
        self,
        plug,
        max_on_seconds: float = MAX_ON_SECONDS_DEFAULT,
        clock: Clock | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        if not max_on_seconds > 0.0:
            raise ValueError("max_on_seconds must be positive.")
        self._plug = plug
        self._max_on_seconds = float(max_on_seconds)
        self._clock: Clock = clock or SystemClock()
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def on_seconds_elapsed(self) -> float:
        if self._on_since is None:
            return 0.0
        return self._clock.monotonic() - self._on_since

    def start(self) -> None:
        if self._task is None:
            self._stopped = False
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def notify_on(self) -> None:
        """Report that the plug was switched ON."""
        if self._on_since is None:
            self._on_since = self._clock.monotonic()

    def notify_off(self) -> None:
        """Report that the plug was switched OFF."""
        self._on_since = None

    async def _run(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is not None
                    and self.on_seconds_elapsed >= self._max_on_seconds
                ):
                    logger.warning(
                        "Max-on watchdog fired after %.0fs of continuous ON; "
                        "forcing plug OFF.",
                        self.on_seconds_elapsed,
                    )
                    await self._plug.turn_off()
                    self._on_since = None
            except asyncio.CancelledError:
                raise
            except Exception:  # defensive: the watchdog must never die silently
                logger.exception("Max-on watchdog iteration failed; continuing.")
                self._on_since = None
