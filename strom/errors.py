"""Typed exception hierarchy for Strom.

All exceptions in this module represent *expected operational failures*
(misconfiguration, provider outages, solver failures, device trouble, bad
schedules). The controller catches :class:`StromError`, logs context and exits
with a non-zero status. Any other exception is a bug and is allowed to
propagate with its full traceback.

Error messages must never contain credentials or API keys.
"""


def scrub(message: str, *secrets: str | None) -> str:
    """Remove credential material from an error message."""
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message


class StromError(Exception):
    """Base class for expected operational failures."""


class ConfigurationError(StromError):
    """Invalid, missing or malformed configuration."""


class ProviderError(StromError):
    """An external data provider (weather / electricity price) failed."""


class WeatherProviderError(ProviderError):
    """OpenWeather (or another weather provider) failed or returned bad data."""


class PriceProviderError(ProviderError):
    """ENTSO-E (or another price provider) failed or returned bad data."""


class OptimizationError(StromError):
    """The heating schedule could not be produced."""


class InvalidInputError(OptimizationError):
    """Optimizer input was malformed (empty, non-finite, wrong shape/index)."""


class InfeasibleProblemError(OptimizationError):
    """The optimization problem is physically infeasible."""


class SolverError(OptimizationError):
    """The numerical solver failed or returned an unusable result."""


class ActuationError(StromError):
    """A heater output could not be translated into a safe actuation plan."""


class InvalidScheduleError(ActuationError):
    """A schedule was empty, had the wrong shape or contained unusable values."""


class DeviceError(StromError):
    """The smart plug could not be discovered, commanded or verified."""


class CoverageError(StromError):
    """A required data horizon is not covered by real observations.

    Raised instead of silently filling gaps from distant observations
    (audit issue 34).
    """
