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


from mutmut.mutation.trampoline import wrap_in_trampoline as _mutmut_mutated, MutantDict


class Clock(Protocol):
    """Time source used by the actuation code; injectable for tests."""

    def monotonic(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...
mutants_xǁSystemClockǁsleep__mutmut: MutantDict = {}  # type: ignore


class SystemClock:
    """Wall-clock implementation of :class:`Clock`."""

    def monotonic(self) -> float:
        return time.monotonic()

    @_mutmut_mutated(mutants_xǁSystemClockǁsleep__mutmut)
    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def xǁSystemClockǁsleep__mutmut_orig(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def xǁSystemClockǁsleep__mutmut_1(self, seconds: float) -> None:
        await asyncio.sleep(None)

mutants_xǁSystemClockǁsleep__mutmut['_mutmut_orig'] = SystemClock.xǁSystemClockǁsleep__mutmut_orig # type: ignore # mutmut generated
mutants_xǁSystemClockǁsleep__mutmut['xǁSystemClockǁsleep__mutmut_1'] = SystemClock.xǁSystemClockǁsleep__mutmut_1 # type: ignore # mutmut generated


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
mutants_x_resolve_actuation__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_resolve_actuation__mutmut)
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


def x_resolve_actuation__mutmut_orig(
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


def x_resolve_actuation__mutmut_1(
    output: float,
    interval_seconds: float,
    min_pulse_seconds: float = MIN_PULSE_SECONDS,
) -> ActuationPlan:
    """Convert one fractional heater output into a bounded duty-cycle plan.

    Raises:
        ActuationError: if ``output`` is not finite or outside ``[0, 1]``,
            or if the interval is not positive.
    """
    interval_seconds = None
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


def x_resolve_actuation__mutmut_2(
    output: float,
    interval_seconds: float,
    min_pulse_seconds: float = MIN_PULSE_SECONDS,
) -> ActuationPlan:
    """Convert one fractional heater output into a bounded duty-cycle plan.

    Raises:
        ActuationError: if ``output`` is not finite or outside ``[0, 1]``,
            or if the interval is not positive.
    """
    interval_seconds = float(None)
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


def x_resolve_actuation__mutmut_3(
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
    if not interval_seconds > 0.0 and not pd.api.types.is_scalar(interval_seconds):
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


def x_resolve_actuation__mutmut_4(
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
    if interval_seconds > 0.0 or not pd.api.types.is_scalar(interval_seconds):
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


def x_resolve_actuation__mutmut_5(
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
    if not interval_seconds >= 0.0 or not pd.api.types.is_scalar(interval_seconds):
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


def x_resolve_actuation__mutmut_6(
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
    if not interval_seconds > 1.0 or not pd.api.types.is_scalar(interval_seconds):
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


def x_resolve_actuation__mutmut_7(
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
    if not interval_seconds > 0.0 or pd.api.types.is_scalar(interval_seconds):
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


def x_resolve_actuation__mutmut_8(
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
    if not interval_seconds > 0.0 or not pd.api.types.is_scalar(None):
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


def x_resolve_actuation__mutmut_9(
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
            None
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


def x_resolve_actuation__mutmut_10(
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

    value = None
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


def x_resolve_actuation__mutmut_11(
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

    value = float(None)
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


def x_resolve_actuation__mutmut_12(
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
    if value == value:  # NaN
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


def x_resolve_actuation__mutmut_13(
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
            None
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


def x_resolve_actuation__mutmut_14(
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
            "XXHeater output is NaN; refusing to actuate. Re-run the optimizer.XX"
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


def x_resolve_actuation__mutmut_15(
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
            "heater output is nan; refusing to actuate. re-run the optimizer."
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


def x_resolve_actuation__mutmut_16(
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
            "HEATER OUTPUT IS NAN; REFUSING TO ACTUATE. RE-RUN THE OPTIMIZER."
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


def x_resolve_actuation__mutmut_17(
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
    if value not in (float("inf"), float("-inf")):
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


def x_resolve_actuation__mutmut_18(
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
    if value in (float(None), float("-inf")):
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


def x_resolve_actuation__mutmut_19(
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
    if value in (float("XXinfXX"), float("-inf")):
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


def x_resolve_actuation__mutmut_20(
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
    if value in (float("INF"), float("-inf")):
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


def x_resolve_actuation__mutmut_21(
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
    if value in (float("inf"), float(None)):
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


def x_resolve_actuation__mutmut_22(
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
    if value in (float("inf"), float("XX-infXX")):
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


def x_resolve_actuation__mutmut_23(
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
    if value in (float("inf"), float("-INF")):
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


def x_resolve_actuation__mutmut_24(
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
            None
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


def x_resolve_actuation__mutmut_25(
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
    if 0.0 <= value <= 1.0:
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


def x_resolve_actuation__mutmut_26(
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
    if not 1.0 <= value <= 1.0:
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


def x_resolve_actuation__mutmut_27(
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
    if not 0.0 < value <= 1.0:
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


def x_resolve_actuation__mutmut_28(
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
    if not 0.0 <= value < 1.0:
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


def x_resolve_actuation__mutmut_29(
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
    if not 0.0 <= value <= 2.0:
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


def x_resolve_actuation__mutmut_30(
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
            None
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


def x_resolve_actuation__mutmut_31(
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

    if value != 0.0:
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


def x_resolve_actuation__mutmut_32(
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

    if value == 1.0:
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


def x_resolve_actuation__mutmut_33(
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
            segments=None,
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


def x_resolve_actuation__mutmut_34(
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
            interval_seconds=None,
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


def x_resolve_actuation__mutmut_35(
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


def x_resolve_actuation__mutmut_36(
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


def x_resolve_actuation__mutmut_37(
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
            segments=(ActuationSegment(on=None, seconds=interval_seconds),),
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


def x_resolve_actuation__mutmut_38(
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
            segments=(ActuationSegment(on=False, seconds=None),),
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


def x_resolve_actuation__mutmut_39(
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
            segments=(ActuationSegment(seconds=interval_seconds),),
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


def x_resolve_actuation__mutmut_40(
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
            segments=(ActuationSegment(on=False, ),),
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


def x_resolve_actuation__mutmut_41(
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
            segments=(ActuationSegment(on=True, seconds=interval_seconds),),
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


def x_resolve_actuation__mutmut_42(
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

    on_seconds = None
    # Bounded duty cycle: clamp into [min_pulse, interval].
    on_seconds = min(max(on_seconds, min_pulse_seconds), interval_seconds)

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_43(
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

    on_seconds = value / interval_seconds
    # Bounded duty cycle: clamp into [min_pulse, interval].
    on_seconds = min(max(on_seconds, min_pulse_seconds), interval_seconds)

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_44(
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
    on_seconds = None

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_45(
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
    on_seconds = min(None, interval_seconds)

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_46(
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
    on_seconds = min(max(on_seconds, min_pulse_seconds), None)

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_47(
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
    on_seconds = min(interval_seconds)

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_48(
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
    on_seconds = min(max(on_seconds, min_pulse_seconds), )

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_49(
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
    on_seconds = min(max(None, min_pulse_seconds), interval_seconds)

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_50(
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
    on_seconds = min(max(on_seconds, None), interval_seconds)

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_51(
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
    on_seconds = min(max(min_pulse_seconds), interval_seconds)

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_52(
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
    on_seconds = min(max(on_seconds, ), interval_seconds)

    segments = [ActuationSegment(on=True, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_53(
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

    segments = None
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_54(
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

    segments = [ActuationSegment(on=None, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_55(
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

    segments = [ActuationSegment(on=True, seconds=None)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_56(
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

    segments = [ActuationSegment(seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_57(
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

    segments = [ActuationSegment(on=True, )]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_58(
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

    segments = [ActuationSegment(on=False, seconds=on_seconds)]
    off_seconds = interval_seconds - on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_59(
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
    off_seconds = None
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_60(
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
    off_seconds = interval_seconds + on_seconds
    if off_seconds > 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_61(
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
    if off_seconds >= 0.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_62(
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
    if off_seconds > 1.0:
        segments.append(ActuationSegment(on=False, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_63(
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
        segments.append(None)
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_64(
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
        segments.append(ActuationSegment(on=None, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_65(
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
        segments.append(ActuationSegment(on=False, seconds=None))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_66(
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
        segments.append(ActuationSegment(seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_67(
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
        segments.append(ActuationSegment(on=False, ))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_68(
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
        segments.append(ActuationSegment(on=True, seconds=off_seconds))
    return ActuationPlan(
        segments=tuple(segments), interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_69(
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
        segments=None, interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_70(
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
        segments=tuple(segments), interval_seconds=None
    )


def x_resolve_actuation__mutmut_71(
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
        interval_seconds=interval_seconds
    )


def x_resolve_actuation__mutmut_72(
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
        segments=tuple(segments), )


def x_resolve_actuation__mutmut_73(
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
        segments=tuple(None), interval_seconds=interval_seconds
    )

mutants_x_resolve_actuation__mutmut['_mutmut_orig'] = x_resolve_actuation__mutmut_orig # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_1'] = x_resolve_actuation__mutmut_1 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_2'] = x_resolve_actuation__mutmut_2 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_3'] = x_resolve_actuation__mutmut_3 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_4'] = x_resolve_actuation__mutmut_4 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_5'] = x_resolve_actuation__mutmut_5 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_6'] = x_resolve_actuation__mutmut_6 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_7'] = x_resolve_actuation__mutmut_7 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_8'] = x_resolve_actuation__mutmut_8 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_9'] = x_resolve_actuation__mutmut_9 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_10'] = x_resolve_actuation__mutmut_10 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_11'] = x_resolve_actuation__mutmut_11 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_12'] = x_resolve_actuation__mutmut_12 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_13'] = x_resolve_actuation__mutmut_13 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_14'] = x_resolve_actuation__mutmut_14 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_15'] = x_resolve_actuation__mutmut_15 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_16'] = x_resolve_actuation__mutmut_16 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_17'] = x_resolve_actuation__mutmut_17 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_18'] = x_resolve_actuation__mutmut_18 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_19'] = x_resolve_actuation__mutmut_19 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_20'] = x_resolve_actuation__mutmut_20 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_21'] = x_resolve_actuation__mutmut_21 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_22'] = x_resolve_actuation__mutmut_22 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_23'] = x_resolve_actuation__mutmut_23 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_24'] = x_resolve_actuation__mutmut_24 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_25'] = x_resolve_actuation__mutmut_25 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_26'] = x_resolve_actuation__mutmut_26 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_27'] = x_resolve_actuation__mutmut_27 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_28'] = x_resolve_actuation__mutmut_28 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_29'] = x_resolve_actuation__mutmut_29 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_30'] = x_resolve_actuation__mutmut_30 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_31'] = x_resolve_actuation__mutmut_31 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_32'] = x_resolve_actuation__mutmut_32 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_33'] = x_resolve_actuation__mutmut_33 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_34'] = x_resolve_actuation__mutmut_34 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_35'] = x_resolve_actuation__mutmut_35 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_36'] = x_resolve_actuation__mutmut_36 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_37'] = x_resolve_actuation__mutmut_37 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_38'] = x_resolve_actuation__mutmut_38 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_39'] = x_resolve_actuation__mutmut_39 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_40'] = x_resolve_actuation__mutmut_40 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_41'] = x_resolve_actuation__mutmut_41 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_42'] = x_resolve_actuation__mutmut_42 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_43'] = x_resolve_actuation__mutmut_43 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_44'] = x_resolve_actuation__mutmut_44 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_45'] = x_resolve_actuation__mutmut_45 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_46'] = x_resolve_actuation__mutmut_46 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_47'] = x_resolve_actuation__mutmut_47 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_48'] = x_resolve_actuation__mutmut_48 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_49'] = x_resolve_actuation__mutmut_49 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_50'] = x_resolve_actuation__mutmut_50 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_51'] = x_resolve_actuation__mutmut_51 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_52'] = x_resolve_actuation__mutmut_52 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_53'] = x_resolve_actuation__mutmut_53 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_54'] = x_resolve_actuation__mutmut_54 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_55'] = x_resolve_actuation__mutmut_55 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_56'] = x_resolve_actuation__mutmut_56 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_57'] = x_resolve_actuation__mutmut_57 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_58'] = x_resolve_actuation__mutmut_58 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_59'] = x_resolve_actuation__mutmut_59 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_60'] = x_resolve_actuation__mutmut_60 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_61'] = x_resolve_actuation__mutmut_61 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_62'] = x_resolve_actuation__mutmut_62 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_63'] = x_resolve_actuation__mutmut_63 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_64'] = x_resolve_actuation__mutmut_64 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_65'] = x_resolve_actuation__mutmut_65 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_66'] = x_resolve_actuation__mutmut_66 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_67'] = x_resolve_actuation__mutmut_67 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_68'] = x_resolve_actuation__mutmut_68 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_69'] = x_resolve_actuation__mutmut_69 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_70'] = x_resolve_actuation__mutmut_70 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_71'] = x_resolve_actuation__mutmut_71 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_72'] = x_resolve_actuation__mutmut_72 # type: ignore # mutmut generated
mutants_x_resolve_actuation__mutmut['x_resolve_actuation__mutmut_73'] = x_resolve_actuation__mutmut_73 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_plan_from_schedule__mutmut)
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


def x_plan_from_schedule__mutmut_orig(
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


def x_plan_from_schedule__mutmut_1(
    schedule: pd.DataFrame,
    interval_seconds: float,
    min_pulse_seconds: float = MIN_PULSE_SECONDS,
    index: int = 1,
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


def x_plan_from_schedule__mutmut_2(
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
    if schedule is None and len(schedule) == 0:
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


def x_plan_from_schedule__mutmut_3(
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
    if schedule is not None or len(schedule) == 0:
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


def x_plan_from_schedule__mutmut_4(
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
    if schedule is None or len(schedule) != 0:
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


def x_plan_from_schedule__mutmut_5(
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
    if schedule is None or len(schedule) == 1:
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


def x_plan_from_schedule__mutmut_6(
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
            None
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


def x_plan_from_schedule__mutmut_7(
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
            "XXSchedule is empty; refusing to actuate. Check the optimizer run.XX"
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


def x_plan_from_schedule__mutmut_8(
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
            "schedule is empty; refusing to actuate. check the optimizer run."
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


def x_plan_from_schedule__mutmut_9(
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
            "SCHEDULE IS EMPTY; REFUSING TO ACTUATE. CHECK THE OPTIMIZER RUN."
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


def x_plan_from_schedule__mutmut_10(
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
    if REQUIRED_OUTPUT_COLUMN in schedule.columns:
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


def x_plan_from_schedule__mutmut_11(
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
            None
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


def x_plan_from_schedule__mutmut_12(
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
            "XXrefusing to actuate.XX"
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


def x_plan_from_schedule__mutmut_13(
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
            "REFUSING TO ACTUATE."
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


def x_plan_from_schedule__mutmut_14(
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
    if 0 <= index < len(schedule):
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


def x_plan_from_schedule__mutmut_15(
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
    if not 1 <= index < len(schedule):
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


def x_plan_from_schedule__mutmut_16(
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
    if not 0 < index < len(schedule):
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


def x_plan_from_schedule__mutmut_17(
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
    if not 0 <= index <= len(schedule):
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


def x_plan_from_schedule__mutmut_18(
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
            None
        )

    raw = schedule[REQUIRED_OUTPUT_COLUMN].iloc[index]
    if pd.isna(raw):
        raise InvalidScheduleError(
            "Heater output is NaN (solver failure?); refusing to actuate."
        )
    return resolve_actuation(float(raw), interval_seconds, min_pulse_seconds)


def x_plan_from_schedule__mutmut_19(
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

    raw = None
    if pd.isna(raw):
        raise InvalidScheduleError(
            "Heater output is NaN (solver failure?); refusing to actuate."
        )
    return resolve_actuation(float(raw), interval_seconds, min_pulse_seconds)


def x_plan_from_schedule__mutmut_20(
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
    if pd.isna(None):
        raise InvalidScheduleError(
            "Heater output is NaN (solver failure?); refusing to actuate."
        )
    return resolve_actuation(float(raw), interval_seconds, min_pulse_seconds)


def x_plan_from_schedule__mutmut_21(
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
            None
        )
    return resolve_actuation(float(raw), interval_seconds, min_pulse_seconds)


def x_plan_from_schedule__mutmut_22(
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
            "XXHeater output is NaN (solver failure?); refusing to actuate.XX"
        )
    return resolve_actuation(float(raw), interval_seconds, min_pulse_seconds)


def x_plan_from_schedule__mutmut_23(
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
            "heater output is nan (solver failure?); refusing to actuate."
        )
    return resolve_actuation(float(raw), interval_seconds, min_pulse_seconds)


def x_plan_from_schedule__mutmut_24(
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
            "HEATER OUTPUT IS NAN (SOLVER FAILURE?); REFUSING TO ACTUATE."
        )
    return resolve_actuation(float(raw), interval_seconds, min_pulse_seconds)


def x_plan_from_schedule__mutmut_25(
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
    return resolve_actuation(None, interval_seconds, min_pulse_seconds)


def x_plan_from_schedule__mutmut_26(
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
    return resolve_actuation(float(raw), None, min_pulse_seconds)


def x_plan_from_schedule__mutmut_27(
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
    return resolve_actuation(float(raw), interval_seconds, None)


def x_plan_from_schedule__mutmut_28(
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
    return resolve_actuation(interval_seconds, min_pulse_seconds)


def x_plan_from_schedule__mutmut_29(
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
    return resolve_actuation(float(raw), min_pulse_seconds)


def x_plan_from_schedule__mutmut_30(
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
    return resolve_actuation(float(raw), interval_seconds, )


def x_plan_from_schedule__mutmut_31(
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
    return resolve_actuation(float(None), interval_seconds, min_pulse_seconds)

mutants_x_plan_from_schedule__mutmut['_mutmut_orig'] = x_plan_from_schedule__mutmut_orig # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_1'] = x_plan_from_schedule__mutmut_1 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_2'] = x_plan_from_schedule__mutmut_2 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_3'] = x_plan_from_schedule__mutmut_3 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_4'] = x_plan_from_schedule__mutmut_4 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_5'] = x_plan_from_schedule__mutmut_5 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_6'] = x_plan_from_schedule__mutmut_6 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_7'] = x_plan_from_schedule__mutmut_7 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_8'] = x_plan_from_schedule__mutmut_8 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_9'] = x_plan_from_schedule__mutmut_9 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_10'] = x_plan_from_schedule__mutmut_10 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_11'] = x_plan_from_schedule__mutmut_11 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_12'] = x_plan_from_schedule__mutmut_12 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_13'] = x_plan_from_schedule__mutmut_13 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_14'] = x_plan_from_schedule__mutmut_14 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_15'] = x_plan_from_schedule__mutmut_15 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_16'] = x_plan_from_schedule__mutmut_16 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_17'] = x_plan_from_schedule__mutmut_17 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_18'] = x_plan_from_schedule__mutmut_18 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_19'] = x_plan_from_schedule__mutmut_19 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_20'] = x_plan_from_schedule__mutmut_20 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_21'] = x_plan_from_schedule__mutmut_21 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_22'] = x_plan_from_schedule__mutmut_22 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_23'] = x_plan_from_schedule__mutmut_23 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_24'] = x_plan_from_schedule__mutmut_24 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_25'] = x_plan_from_schedule__mutmut_25 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_26'] = x_plan_from_schedule__mutmut_26 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_27'] = x_plan_from_schedule__mutmut_27 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_28'] = x_plan_from_schedule__mutmut_28 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_29'] = x_plan_from_schedule__mutmut_29 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_30'] = x_plan_from_schedule__mutmut_30 # type: ignore # mutmut generated
mutants_x_plan_from_schedule__mutmut['x_plan_from_schedule__mutmut_31'] = x_plan_from_schedule__mutmut_31 # type: ignore # mutmut generated
mutants_x_execute_plan__mutmut: MutantDict = {}  # type: ignore


@_mutmut_mutated(mutants_x_execute_plan__mutmut)
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


async def x_execute_plan__mutmut_orig(
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


async def x_execute_plan__mutmut_1(
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
        await clock.sleep(None)

mutants_x_execute_plan__mutmut['_mutmut_orig'] = x_execute_plan__mutmut_orig # type: ignore # mutmut generated
mutants_x_execute_plan__mutmut['x_execute_plan__mutmut_1'] = x_execute_plan__mutmut_1 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut: MutantDict = {}  # type: ignore
mutants_xǁMaxOnWatchdogǁstart__mutmut: MutantDict = {}  # type: ignore
mutants_xǁMaxOnWatchdogǁstop__mutmut: MutantDict = {}  # type: ignore
mutants_xǁMaxOnWatchdogǁnotify_on__mutmut: MutantDict = {}  # type: ignore
mutants_xǁMaxOnWatchdogǁnotify_off__mutmut: MutantDict = {}  # type: ignore
mutants_xǁMaxOnWatchdogǁ_run__mutmut: MutantDict = {}  # type: ignore


class MaxOnWatchdog:
    """Independent maximum-on safety timer.

    The watchdog keeps its own belief about whether the plug is ON (fed via
    :meth:`notify_on` / :meth:`notify_off`) and forces the plug OFF if that
    state persists for more than ``max_on_seconds``. It never consults the
    optimizer, so a stale or crashed controller cannot leave the heater on
    indefinitely.
    """

    @_mutmut_mutated(mutants_xǁMaxOnWatchdogǁ__init____mutmut)
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

    def xǁMaxOnWatchdogǁ__init____mutmut_orig(
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

    def xǁMaxOnWatchdogǁ__init____mutmut_1(
        self,
        plug,
        max_on_seconds: float = MAX_ON_SECONDS_DEFAULT,
        clock: Clock | None = None,
        poll_seconds: float = 31.0,
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

    def xǁMaxOnWatchdogǁ__init____mutmut_2(
        self,
        plug,
        max_on_seconds: float = MAX_ON_SECONDS_DEFAULT,
        clock: Clock | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        if max_on_seconds > 0.0:
            raise ValueError("max_on_seconds must be positive.")
        self._plug = plug
        self._max_on_seconds = float(max_on_seconds)
        self._clock: Clock = clock or SystemClock()
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_3(
        self,
        plug,
        max_on_seconds: float = MAX_ON_SECONDS_DEFAULT,
        clock: Clock | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        if not max_on_seconds >= 0.0:
            raise ValueError("max_on_seconds must be positive.")
        self._plug = plug
        self._max_on_seconds = float(max_on_seconds)
        self._clock: Clock = clock or SystemClock()
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_4(
        self,
        plug,
        max_on_seconds: float = MAX_ON_SECONDS_DEFAULT,
        clock: Clock | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        if not max_on_seconds > 1.0:
            raise ValueError("max_on_seconds must be positive.")
        self._plug = plug
        self._max_on_seconds = float(max_on_seconds)
        self._clock: Clock = clock or SystemClock()
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_5(
        self,
        plug,
        max_on_seconds: float = MAX_ON_SECONDS_DEFAULT,
        clock: Clock | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        if not max_on_seconds > 0.0:
            raise ValueError(None)
        self._plug = plug
        self._max_on_seconds = float(max_on_seconds)
        self._clock: Clock = clock or SystemClock()
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_6(
        self,
        plug,
        max_on_seconds: float = MAX_ON_SECONDS_DEFAULT,
        clock: Clock | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        if not max_on_seconds > 0.0:
            raise ValueError("XXmax_on_seconds must be positive.XX")
        self._plug = plug
        self._max_on_seconds = float(max_on_seconds)
        self._clock: Clock = clock or SystemClock()
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_7(
        self,
        plug,
        max_on_seconds: float = MAX_ON_SECONDS_DEFAULT,
        clock: Clock | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        if not max_on_seconds > 0.0:
            raise ValueError("MAX_ON_SECONDS MUST BE POSITIVE.")
        self._plug = plug
        self._max_on_seconds = float(max_on_seconds)
        self._clock: Clock = clock or SystemClock()
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_8(
        self,
        plug,
        max_on_seconds: float = MAX_ON_SECONDS_DEFAULT,
        clock: Clock | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        if not max_on_seconds > 0.0:
            raise ValueError("max_on_seconds must be positive.")
        self._plug = None
        self._max_on_seconds = float(max_on_seconds)
        self._clock: Clock = clock or SystemClock()
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_9(
        self,
        plug,
        max_on_seconds: float = MAX_ON_SECONDS_DEFAULT,
        clock: Clock | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        if not max_on_seconds > 0.0:
            raise ValueError("max_on_seconds must be positive.")
        self._plug = plug
        self._max_on_seconds = None
        self._clock: Clock = clock or SystemClock()
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_10(
        self,
        plug,
        max_on_seconds: float = MAX_ON_SECONDS_DEFAULT,
        clock: Clock | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        if not max_on_seconds > 0.0:
            raise ValueError("max_on_seconds must be positive.")
        self._plug = plug
        self._max_on_seconds = float(None)
        self._clock: Clock = clock or SystemClock()
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_11(
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
        self._clock: Clock = None
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_12(
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
        self._clock: Clock = clock and SystemClock()
        self._poll_seconds = float(poll_seconds)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_13(
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
        self._poll_seconds = None
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_14(
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
        self._poll_seconds = float(None)
        self._on_since: float | None = None
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_15(
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
        self._on_since: float | None = ""
        self._task: asyncio.Task | None = None
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_16(
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
        self._task: asyncio.Task | None = ""
        self._stopped = False

    def xǁMaxOnWatchdogǁ__init____mutmut_17(
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
        self._stopped = None

    def xǁMaxOnWatchdogǁ__init____mutmut_18(
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
        self._stopped = True

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def on_seconds_elapsed(self) -> float:
        if self._on_since is None:
            return 0.0
        return self._clock.monotonic() - self._on_since

    @_mutmut_mutated(mutants_xǁMaxOnWatchdogǁstart__mutmut)
    def start(self) -> None:
        if self._task is None:
            self._stopped = False
            self._task = asyncio.create_task(self._run())

    def xǁMaxOnWatchdogǁstart__mutmut_orig(self) -> None:
        if self._task is None:
            self._stopped = False
            self._task = asyncio.create_task(self._run())

    def xǁMaxOnWatchdogǁstart__mutmut_1(self) -> None:
        if self._task is not None:
            self._stopped = False
            self._task = asyncio.create_task(self._run())

    def xǁMaxOnWatchdogǁstart__mutmut_2(self) -> None:
        if self._task is None:
            self._stopped = None
            self._task = asyncio.create_task(self._run())

    def xǁMaxOnWatchdogǁstart__mutmut_3(self) -> None:
        if self._task is None:
            self._stopped = True
            self._task = asyncio.create_task(self._run())

    def xǁMaxOnWatchdogǁstart__mutmut_4(self) -> None:
        if self._task is None:
            self._stopped = False
            self._task = None

    def xǁMaxOnWatchdogǁstart__mutmut_5(self) -> None:
        if self._task is None:
            self._stopped = False
            self._task = asyncio.create_task(None)

    @_mutmut_mutated(mutants_xǁMaxOnWatchdogǁstop__mutmut)
    async def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def xǁMaxOnWatchdogǁstop__mutmut_orig(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def xǁMaxOnWatchdogǁstop__mutmut_1(self) -> None:
        self._stopped = None
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def xǁMaxOnWatchdogǁstop__mutmut_2(self) -> None:
        self._stopped = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def xǁMaxOnWatchdogǁstop__mutmut_3(self) -> None:
        self._stopped = True
        if self._task is None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def xǁMaxOnWatchdogǁstop__mutmut_4(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = ""

    @_mutmut_mutated(mutants_xǁMaxOnWatchdogǁnotify_on__mutmut)
    def notify_on(self) -> None:
        """Report that the plug was switched ON."""
        if self._on_since is None:
            self._on_since = self._clock.monotonic()

    def xǁMaxOnWatchdogǁnotify_on__mutmut_orig(self) -> None:
        """Report that the plug was switched ON."""
        if self._on_since is None:
            self._on_since = self._clock.monotonic()

    def xǁMaxOnWatchdogǁnotify_on__mutmut_1(self) -> None:
        """Report that the plug was switched ON."""
        if self._on_since is not None:
            self._on_since = self._clock.monotonic()

    def xǁMaxOnWatchdogǁnotify_on__mutmut_2(self) -> None:
        """Report that the plug was switched ON."""
        if self._on_since is None:
            self._on_since = None

    @_mutmut_mutated(mutants_xǁMaxOnWatchdogǁnotify_off__mutmut)
    def notify_off(self) -> None:
        """Report that the plug was switched OFF."""
        self._on_since = None

    def xǁMaxOnWatchdogǁnotify_off__mutmut_orig(self) -> None:
        """Report that the plug was switched OFF."""
        self._on_since = None

    def xǁMaxOnWatchdogǁnotify_off__mutmut_1(self) -> None:
        """Report that the plug was switched OFF."""
        self._on_since = ""

    @_mutmut_mutated(mutants_xǁMaxOnWatchdogǁ_run__mutmut)
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

    async def xǁMaxOnWatchdogǁ_run__mutmut_orig(self) -> None:
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

    async def xǁMaxOnWatchdogǁ_run__mutmut_1(self) -> None:
        while self._stopped:
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

    async def xǁMaxOnWatchdogǁ_run__mutmut_2(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(None)
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

    async def xǁMaxOnWatchdogǁ_run__mutmut_3(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is not None or self.on_seconds_elapsed >= self._max_on_seconds
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

    async def xǁMaxOnWatchdogǁ_run__mutmut_4(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is None
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

    async def xǁMaxOnWatchdogǁ_run__mutmut_5(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is not None
                    and self.on_seconds_elapsed > self._max_on_seconds
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

    async def xǁMaxOnWatchdogǁ_run__mutmut_6(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is not None
                    and self.on_seconds_elapsed >= self._max_on_seconds
                ):
                    logger.warning(
                        None,
                        self.on_seconds_elapsed,
                    )
                    await self._plug.turn_off()
                    self._on_since = None
            except asyncio.CancelledError:
                raise
            except Exception:  # defensive: the watchdog must never die silently
                logger.exception("Max-on watchdog iteration failed; continuing.")
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_7(self) -> None:
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
                        None,
                    )
                    await self._plug.turn_off()
                    self._on_since = None
            except asyncio.CancelledError:
                raise
            except Exception:  # defensive: the watchdog must never die silently
                logger.exception("Max-on watchdog iteration failed; continuing.")
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_8(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is not None
                    and self.on_seconds_elapsed >= self._max_on_seconds
                ):
                    logger.warning(
                        self.on_seconds_elapsed,
                    )
                    await self._plug.turn_off()
                    self._on_since = None
            except asyncio.CancelledError:
                raise
            except Exception:  # defensive: the watchdog must never die silently
                logger.exception("Max-on watchdog iteration failed; continuing.")
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_9(self) -> None:
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
                        )
                    await self._plug.turn_off()
                    self._on_since = None
            except asyncio.CancelledError:
                raise
            except Exception:  # defensive: the watchdog must never die silently
                logger.exception("Max-on watchdog iteration failed; continuing.")
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_10(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is not None
                    and self.on_seconds_elapsed >= self._max_on_seconds
                ):
                    logger.warning(
                        "XXMax-on watchdog fired after %.0fs of continuous ON; XX"
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

    async def xǁMaxOnWatchdogǁ_run__mutmut_11(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is not None
                    and self.on_seconds_elapsed >= self._max_on_seconds
                ):
                    logger.warning(
                        "max-on watchdog fired after %.0fs of continuous on; "
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

    async def xǁMaxOnWatchdogǁ_run__mutmut_12(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is not None
                    and self.on_seconds_elapsed >= self._max_on_seconds
                ):
                    logger.warning(
                        "MAX-ON WATCHDOG FIRED AFTER %.0FS OF CONTINUOUS ON; "
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

    async def xǁMaxOnWatchdogǁ_run__mutmut_13(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is not None
                    and self.on_seconds_elapsed >= self._max_on_seconds
                ):
                    logger.warning(
                        "Max-on watchdog fired after %.0fs of continuous ON; "
                        "XXforcing plug OFF.XX",
                        self.on_seconds_elapsed,
                    )
                    await self._plug.turn_off()
                    self._on_since = None
            except asyncio.CancelledError:
                raise
            except Exception:  # defensive: the watchdog must never die silently
                logger.exception("Max-on watchdog iteration failed; continuing.")
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_14(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is not None
                    and self.on_seconds_elapsed >= self._max_on_seconds
                ):
                    logger.warning(
                        "Max-on watchdog fired after %.0fs of continuous ON; "
                        "forcing plug off.",
                        self.on_seconds_elapsed,
                    )
                    await self._plug.turn_off()
                    self._on_since = None
            except asyncio.CancelledError:
                raise
            except Exception:  # defensive: the watchdog must never die silently
                logger.exception("Max-on watchdog iteration failed; continuing.")
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_15(self) -> None:
        while not self._stopped:
            try:
                await self._clock.sleep(self._poll_seconds)
                if (
                    self._on_since is not None
                    and self.on_seconds_elapsed >= self._max_on_seconds
                ):
                    logger.warning(
                        "Max-on watchdog fired after %.0fs of continuous ON; "
                        "FORCING PLUG OFF.",
                        self.on_seconds_elapsed,
                    )
                    await self._plug.turn_off()
                    self._on_since = None
            except asyncio.CancelledError:
                raise
            except Exception:  # defensive: the watchdog must never die silently
                logger.exception("Max-on watchdog iteration failed; continuing.")
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_16(self) -> None:
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
                    self._on_since = ""
            except asyncio.CancelledError:
                raise
            except Exception:  # defensive: the watchdog must never die silently
                logger.exception("Max-on watchdog iteration failed; continuing.")
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_17(self) -> None:
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
                logger.exception(None)
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_18(self) -> None:
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
                logger.exception("XXMax-on watchdog iteration failed; continuing.XX")
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_19(self) -> None:
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
                logger.exception("max-on watchdog iteration failed; continuing.")
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_20(self) -> None:
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
                logger.exception("MAX-ON WATCHDOG ITERATION FAILED; CONTINUING.")
                self._on_since = None

    async def xǁMaxOnWatchdogǁ_run__mutmut_21(self) -> None:
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
                self._on_since = ""

mutants_xǁMaxOnWatchdogǁ__init____mutmut['_mutmut_orig'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_orig # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_1'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_1 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_2'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_2 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_3'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_3 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_4'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_4 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_5'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_5 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_6'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_6 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_7'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_7 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_8'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_8 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_9'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_9 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_10'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_10 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_11'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_11 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_12'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_12 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_13'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_13 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_14'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_14 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_15'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_15 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_16'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_16 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_17'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_17 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ__init____mutmut['xǁMaxOnWatchdogǁ__init____mutmut_18'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ__init____mutmut_18 # type: ignore # mutmut generated

mutants_xǁMaxOnWatchdogǁstart__mutmut['_mutmut_orig'] = MaxOnWatchdog.xǁMaxOnWatchdogǁstart__mutmut_orig # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁstart__mutmut['xǁMaxOnWatchdogǁstart__mutmut_1'] = MaxOnWatchdog.xǁMaxOnWatchdogǁstart__mutmut_1 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁstart__mutmut['xǁMaxOnWatchdogǁstart__mutmut_2'] = MaxOnWatchdog.xǁMaxOnWatchdogǁstart__mutmut_2 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁstart__mutmut['xǁMaxOnWatchdogǁstart__mutmut_3'] = MaxOnWatchdog.xǁMaxOnWatchdogǁstart__mutmut_3 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁstart__mutmut['xǁMaxOnWatchdogǁstart__mutmut_4'] = MaxOnWatchdog.xǁMaxOnWatchdogǁstart__mutmut_4 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁstart__mutmut['xǁMaxOnWatchdogǁstart__mutmut_5'] = MaxOnWatchdog.xǁMaxOnWatchdogǁstart__mutmut_5 # type: ignore # mutmut generated

mutants_xǁMaxOnWatchdogǁstop__mutmut['_mutmut_orig'] = MaxOnWatchdog.xǁMaxOnWatchdogǁstop__mutmut_orig # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁstop__mutmut['xǁMaxOnWatchdogǁstop__mutmut_1'] = MaxOnWatchdog.xǁMaxOnWatchdogǁstop__mutmut_1 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁstop__mutmut['xǁMaxOnWatchdogǁstop__mutmut_2'] = MaxOnWatchdog.xǁMaxOnWatchdogǁstop__mutmut_2 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁstop__mutmut['xǁMaxOnWatchdogǁstop__mutmut_3'] = MaxOnWatchdog.xǁMaxOnWatchdogǁstop__mutmut_3 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁstop__mutmut['xǁMaxOnWatchdogǁstop__mutmut_4'] = MaxOnWatchdog.xǁMaxOnWatchdogǁstop__mutmut_4 # type: ignore # mutmut generated

mutants_xǁMaxOnWatchdogǁnotify_on__mutmut['_mutmut_orig'] = MaxOnWatchdog.xǁMaxOnWatchdogǁnotify_on__mutmut_orig # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁnotify_on__mutmut['xǁMaxOnWatchdogǁnotify_on__mutmut_1'] = MaxOnWatchdog.xǁMaxOnWatchdogǁnotify_on__mutmut_1 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁnotify_on__mutmut['xǁMaxOnWatchdogǁnotify_on__mutmut_2'] = MaxOnWatchdog.xǁMaxOnWatchdogǁnotify_on__mutmut_2 # type: ignore # mutmut generated

mutants_xǁMaxOnWatchdogǁnotify_off__mutmut['_mutmut_orig'] = MaxOnWatchdog.xǁMaxOnWatchdogǁnotify_off__mutmut_orig # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁnotify_off__mutmut['xǁMaxOnWatchdogǁnotify_off__mutmut_1'] = MaxOnWatchdog.xǁMaxOnWatchdogǁnotify_off__mutmut_1 # type: ignore # mutmut generated

mutants_xǁMaxOnWatchdogǁ_run__mutmut['_mutmut_orig'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_orig # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_1'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_1 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_2'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_2 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_3'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_3 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_4'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_4 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_5'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_5 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_6'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_6 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_7'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_7 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_8'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_8 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_9'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_9 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_10'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_10 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_11'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_11 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_12'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_12 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_13'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_13 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_14'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_14 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_15'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_15 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_16'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_16 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_17'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_17 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_18'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_18 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_19'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_19 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_20'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_20 # type: ignore # mutmut generated
mutants_xǁMaxOnWatchdogǁ_run__mutmut['xǁMaxOnWatchdogǁ_run__mutmut_21'] = MaxOnWatchdog.xǁMaxOnWatchdogǁ_run__mutmut_21 # type: ignore # mutmut generated
