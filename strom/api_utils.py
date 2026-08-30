"""External data providers with reliability guards (audit issue 35).

* Every network call has a finite (connect, read) timeout.
* Transient failures (connection errors, timeouts, 5xx, rate limits) are
  retried a bounded number of times with exponential backoff; permanent
  failures fail fast.
* Responses are schema-validated; malformed, empty, rate-limited or
  incomplete payloads raise typed, credential-free provider errors.
* The HTTP getter, the ENTSO-E client and the sleep used for backoff are
  injectable, so tests run without network access or API secrets.
"""

from __future__ import annotations

import os
import time
import warnings
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
import requests
from bs4 import XMLParsedAsHTMLWarning
from entsoe import EntsoePandasClient

from .errors import (
    ConfigurationError,
    PriceProviderError,
    StromError,
    WeatherProviderError,
)
from entsoe.exceptions import NoMatchingDataError

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

EXAMPLE_CITIES = [
    "Barcelona, ES", "Madrid, ES", "Berlin, DE",
    "Paris, FR", "London, GB", "Rome, IT"
]

WEATHER_URL = "https://api.openweathermap.org/data/2.5/forecast"

#: (connect, read) timeouts in seconds for every HTTP request.
WEATHER_TIMEOUT: tuple[float, float] = (5.0, 15.0)
PRICE_TIMEOUT_SECONDS = 30  # entsoe-py declares timeout as Optional[int]

#: Bounded retry policy for transient failures.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0

#: HTTP statuses considered transient (rate limiting / server trouble).
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _scrub(message: str, *secrets: Optional[str]) -> str:
    """Remove credential material from error messages."""
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message


def _is_transient_http(exc: Exception) -> bool:
    """True for failures where a bounded retry can plausibly help."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    response = getattr(exc, "response", None)
    if response is not None:
        return response.status_code in RETRYABLE_STATUS_CODES
    return False


def _retry_loop(
    attempt_fn: Callable[[], object],
    on_error: Callable[[Exception, bool], Exception],
    max_attempts: int = MAX_ATTEMPTS,
    backoff_seconds: float = BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
):
    """Run ``attempt_fn`` with bounded retries for transient errors only."""
    for attempt in range(max_attempts):
        try:
            return attempt_fn()
        except StromError:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            transient = _is_transient_http(exc)
            last = attempt + 1 >= max_attempts
            if not transient or last:
                raise on_error(exc, transient) from exc
            sleep(backoff_seconds * (2 ** attempt))


def find_config_file(name: str) -> Path:
    """Locate a file in the Strom config directory without side effects.

    Looks in ``$STROM_CONFIG_DIR`` first, then in a ``config/`` folder next
    to any parent of the current working directory. Never calls ``os.chdir``.
    """
    env_dir = os.getenv("STROM_CONFIG_DIR")
    if env_dir:
        candidate = Path(env_dir) / name
        if candidate.exists():
            return candidate
        return candidate
    current = Path.cwd()
    for directory in (current, *current.parents):
        candidate = directory / "config" / name
        if candidate.exists():
            return candidate
    return current / "config" / name


def read_api_key(key_path: str) -> str:
    return Path(key_path).read_text().strip()


def get_api_key(key_path: str) -> str:
    """Alias for read_api_key for backward compatibility"""
    return read_api_key(key_path)


def get_weather_api_key(config_dir: Path | None = None) -> str:
    api_key = os.getenv('WEATHER_API_KEY')
    if api_key and api_key.strip():
        return api_key.strip()

    path = (config_dir / 'weather_api_key.txt') if config_dir \
        else find_config_file('weather_api_key.txt')
    if path.is_file():
        key = path.read_text().strip()
        if key:
            return key
    raise ConfigurationError(
        f"No weather API key found; set WEATHER_API_KEY or create "
        f"{path} with the key."
    )


def get_price_api_key(config_dir: Path | None = None) -> str:
    api_key = os.getenv('PRICE_API_KEY')
    if api_key and api_key.strip():
        return api_key.strip()

    path = (config_dir / 'price_api_key.txt') if config_dir \
        else find_config_file('price_api_key.txt')
    if path.is_file():
        key = path.read_text().strip()
        if key:
            return key
    raise ConfigurationError(
        f"No electricity price API key found; set PRICE_API_KEY or create "
        f"{path} with the key."
    )


def _validate_weather_payload(payload, city: str) -> list[dict]:
    """Schema-check the OpenWeather forecast payload."""
    if not isinstance(payload, dict):
        raise WeatherProviderError(
            f"Weather response for {city!r} is not a JSON object; the "
            "provider response schema has changed or the request was "
            "rejected."
        )
    entries = payload.get("list")
    if entries is None:
        raise WeatherProviderError(
            f"Weather response for {city!r} is missing the forecast list; "
            "unexpected response schema."
        )
    if not entries:
        raise WeatherProviderError(
            f"Weather provider returned an empty forecast for {city!r}."
        )
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict) or "dt" not in entry \
                or "main" not in entry or "temp" not in entry.get("main", {}):
            raise WeatherProviderError(
                f"Weather response for {city!r} is malformed at entry "
                f"{position}; unexpected response schema."
            )
    return entries


def get_weather_data(city: str = "Barcelona, ES",
                     *,
                     api_key: str | None = None,
                     http_get: Callable = requests.get,
                     sleep: Callable[[float], None] = time.sleep,
                     max_attempts: int = MAX_ATTEMPTS,
                     timeout=WEATHER_TIMEOUT) -> pd.Series:
    """Get weather for specified city. Examples: Barcelona, ES | Madrid, ES | Berlin, DE

    Raises:
        WeatherProviderError: on rate limits, transient outages after the
            bounded retries, authentication problems, and malformed or empty
            responses. Messages never contain the API key.
    """
    api_key = api_key or get_weather_api_key()
    params = {"q": city, "appid": api_key}

    def on_error(exc: Exception, transient: bool) -> Exception:
        detail = _scrub(str(exc), api_key)
        if transient:
            return WeatherProviderError(
                f"Weather provider unavailable for {city!r} after "
                f"{max_attempts} attempts: {detail}", retryable=True)
        return WeatherProviderError(
            f"Weather request for {city!r} failed: {detail}")

    def attempt() -> object:
        response = http_get(WEATHER_URL, params=params, timeout=timeout)
        response.raise_for_status()
        return response

    try:
        response = _retry_loop(
            attempt,
            on_error=on_error,
            max_attempts=max_attempts,
            sleep=sleep,
        )
    except WeatherProviderError:
        raise
    except Exception as exc:  # non-HTTP failure (e.g. custom client)
        raise on_error(exc, False) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise WeatherProviderError(
            f"Weather response for {city!r} is not valid JSON."
        ) from exc

    entries = _validate_weather_payload(payload, city)

    # Unix epochs are UTC by definition; UTC is the canonical internal
    # timezone (audit issue 34). Downstream code converts if needed.
    temperature_series = pd.Series(
        {pd.Timestamp(entry['dt'], unit='s', tz='UTC'):
            float(entry['main']['temp']) - 273.15 for entry in entries},
        name='ExteriorTemperature',
    )
    temperature_series.index.name = 'Timestamp'
    return temperature_series.sort_index()


def get_spain_electricity_prices(
    zone: str = 'ES',
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    *,
    api_key: str | None = None,
    client=None,
    sleep: Callable[[float], None] = time.sleep,
    max_attempts: int = MAX_ATTEMPTS,
    now: pd.Timestamp | None = None,
) -> pd.Series:
    """Query day-ahead prices for ``zone`` and return them on a UTC index.

    ENTSO-E market time (CET/CEST) is converted to UTC, the canonical
    internal timezone, so intervals stay unique and monotonic across DST
    transitions. Rate limits and transient outages are retried a bounded
    number of times; unpublished or empty windows raise typed errors.
    """
    if start is None:
        start = (now or pd.Timestamp.now(tz='UTC')).floor('h') \
            - pd.Timedelta(hours=1)
    if end is None:
        end = start + pd.Timedelta(hours=26)

    api_key = api_key or os.getenv('PRICE_API_KEY')
    if client is None:
        api_key = api_key or get_price_api_key()
        client = EntsoePandasClient(api_key=api_key,
                                    timeout=PRICE_TIMEOUT_SECONDS,
                                    retry_count=1)

    def on_error(exc: Exception, transient: bool) -> Exception:
        detail = _scrub(str(exc), api_key)
        if isinstance(exc, NoMatchingDataError):
            return PriceProviderError(
                f"No day-ahead prices are published for zone {zone!r} "
                f"between {start} and {end}.")
        if transient:
            return PriceProviderError(
                f"ENTSO-E unavailable for zone {zone!r} after "
                f"{max_attempts} attempts: {detail}", retryable=True)
        return PriceProviderError(
            f"ENTSO-E request for zone {zone!r} failed: {detail}")

    try:
        price_series = _retry_loop(
            lambda: client.query_day_ahead_prices(zone, start=start, end=end),
            on_error=on_error,
            max_attempts=max_attempts,
            sleep=sleep,
        )
    except PriceProviderError:
        raise
    except Exception as exc:
        raise on_error(exc, False) from exc

    if not isinstance(price_series, pd.Series) or price_series.empty:
        raise PriceProviderError(
            f"ENTSO-E returned no price data for zone {zone!r} between "
            f"{start} and {end}."
        )
    if not isinstance(price_series.index, pd.DatetimeIndex) \
            or price_series.index.tz is None:
        raise PriceProviderError(
            "ENTSO-E returned prices without timezone information.")
    price_series.index = price_series.index.tz_convert('UTC')
    price_series.name = 'Price'
    price_series = price_series[~price_series.index.duplicated(keep='last')]
    price_series = price_series / 1000.0  # EUR/MWh -> EUR/kWh
    return price_series.sort_index()


def get_price_series(zone: str = 'ES',
                     start: pd.Timestamp | None = None,
                     end: pd.Timestamp | None = None,
                     **kwargs) -> pd.Series:  # TODO: expand to other countries
    return get_spain_electricity_prices(zone=zone, start=start, end=end,
                                        **kwargs)
