"""Time-series assembly with strict data integrity (audit issue 34).

**Canonical internal timezone is UTC.** Unix epoch timestamps are parsed
with ``utc=True`` (epochs are UTC by definition; the old code localized
them as Madrid time, shifting results by 1-2 hours around DST). All indexes
are converted to UTC, which keeps timestamps unique and monotonic across
DST transitions.

Weather and prices are normalized **independently**:

* weather: bounded linear (time) interpolation only — every filled point is
  within ``weather_max_gap`` of a real observation;
* prices: exact market-interval alignment plus bounded forward-fill. Prices
  are never interpolated (cubic or otherwise) and never stretched across
  neighbouring market intervals; intervals without a published price raise
  :class:`~strom.errors.CoverageError` once the fill tolerance is exceeded.

Input data is never mutated in place.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .api_utils import get_price_series, get_weather_data
from .errors import CoverageError

CANONICAL_TZ = "UTC"

TEMPERATURE_COLUMN = "ExteriorTemperature"
PRICE_COLUMN = "Price"


def _to_utc(series: pd.Series, name: str) -> pd.Series:
    """Validate a tz-aware Series and return a UTC copy (input untouched)."""
    if not isinstance(series, pd.Series):
        raise ValueError(f"{name} data must be a pandas Series.")
    if len(series) == 0:
        raise ValueError(f"{name} data is empty.")
    index = series.index
    if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
        raise ValueError(
            f"{name} timestamps must be timezone-aware; UTC is the "
            "canonical internal timezone."
        )
    out = series.copy()
    out.index = index.tz_convert(CANONICAL_TZ)
    if out.index.has_duplicates:
        n = int(out.index.duplicated().sum())
        raise ValueError(
            f"{name} data contains {n} duplicated interval(s) after UTC "
            "conversion; aggregate or drop duplicates first."
        )
    return out.sort_index()


def _infer_step(index: pd.DatetimeIndex) -> pd.Timedelta:
    diffs = index.to_series().diff().dropna()
    if diffs.empty:
        return pd.Timedelta(0)
    step = diffs.median()
    if pd.isna(step) or step <= pd.Timedelta(0):
        raise ValueError("Target index steps must be positive.")
    return step


def align_weather(weather: pd.Series,
                  target_index: pd.DatetimeIndex,
                  max_gap: pd.Timedelta = pd.Timedelta(hours=3)) -> pd.Series:
    """Place weather observations on ``target_index`` (UTC).

    Missing points are linearly interpolated in time, bounded so that no
    point is more than ``max_gap`` away from a real observation. Any
    uncovered interval (interior gaps beyond the bound, or horizons the
    observations do not span) raises :class:`CoverageError` instead of
    inventing weather.
    """
    source = _to_utc(weather, "weather")
    step = _infer_step(target_index)
    limit = max(1, int(max_gap / step) - 1)
    out = source.reindex(target_index)
    out = out.interpolate(method="time", limit=limit, limit_area="inside")
    missing = out.index[out.isna()]
    if len(missing):
        raise CoverageError(
            f"Weather data has no observation within {max_gap} of interval "
            f"starting {missing.min()} (and {len(missing) - 1} more); "
            "refusing to fill from distant observations."
        )
    out.name = weather.name
    return out


def align_prices(prices: pd.Series,
                 target_index: pd.DatetimeIndex,
                 max_fill: pd.Timedelta = pd.Timedelta(hours=1)) -> pd.Series:
    """Place published prices on ``target_index`` (UTC).

    Prices are matched to their exact market interval; intervals with no
    published price are forward-filled at most ``max_fill`` into the past
    (i.e. the previous market interval is reused briefly, never averaged or
    interpolated). Longer outages raise :class:`CoverageError`.
    """
    source = _to_utc(prices, "price")
    step = _infer_step(target_index)
    limit = max(1, int(max_fill / step))
    out = source.reindex(target_index)
    out = out.ffill(limit=limit)
    missing = out.index[out.isna()]
    if len(missing):
        raise CoverageError(
            f"No electricity price was published for interval starting "
            f"{missing.min()} (and {len(missing) - 1} more) and the fill "
            f"tolerance is {max_fill}; refusing to optimize against "
            "invented prices."
        )
    out.name = prices.name
    return out


def join_data(temp_series: pd.Series,
              price_series: pd.Series,
              *,
              freq: str = "1h",
              weather_max_gap: pd.Timedelta = pd.Timedelta(hours=3),
              price_max_fill: pd.Timedelta = pd.Timedelta(hours=1)) -> pd.DataFrame:
    """Merge weather and price series on a UTC grid.

    Both inputs are converted to UTC, placed on a regular ``freq`` grid over
    the union of their spans and normalized independently (see
    :func:`align_weather` / :func:`align_prices`). Inputs are not mutated.
    """
    temp = _to_utc(temp_series, "weather")
    price = _to_utc(price_series, "price")

    start = min(temp.index.min(), price.index.min()).floor(freq)
    end = max(temp.index.max(), price.index.max()).ceil(freq)
    target = pd.date_range(start, end, freq=freq, tz=CANONICAL_TZ)

    aligned_temp = align_weather(temp, target, weather_max_gap)
    aligned_price = align_prices(price, target, price_max_fill)
    df = pd.concat([aligned_temp, aligned_price], axis=1)
    df.columns = [TEMPERATURE_COLUMN, PRICE_COLUMN]
    return df


def get_temp_price_df(
    weather: pd.Series | None = None,
    prices: pd.Series | None = None,
    *,
    horizon_hours: int = 24,
    zone: str = "ES",
    now: pd.Timestamp | None = None,
    weather_max_gap: pd.Timedelta = pd.Timedelta(hours=3),
    price_max_fill: pd.Timedelta = pd.Timedelta(hours=1),
) -> pd.DataFrame:
    """Fetch (or accept injected) weather and prices for the control horizon.

    The horizon is the next ``horizon_hours`` whole-hour UTC intervals after
    the current hour. Both sources are validated for coverage; incomplete
    horizons raise instead of being filled from distant observations.
    """
    now = now or pd.Timestamp.now(tz=CANONICAL_TZ)
    start = now.floor("h") + pd.Timedelta(hours=1)
    target = pd.date_range(start, periods=horizon_hours, freq="1h",
                           tz=CANONICAL_TZ)

    if weather is None:
        weather = get_weather_data()
    if prices is None:
        prices = get_price_series(zone=zone, end=target[-1])

    aligned_temp = align_weather(weather, target, weather_max_gap)
    aligned_price = align_prices(prices, target, price_max_fill)
    df = pd.concat([aligned_temp, aligned_price], axis=1)
    df.columns = [TEMPERATURE_COLUMN, PRICE_COLUMN]
    df.index.name = "Timestamp"
    return df


def get_temp_price_from_temp(temp_df: pd.DataFrame,
                             prices: pd.Series | None = None) -> pd.DataFrame:
    """Build the optimization frame from VisualCrossing-style epoch data.

    Epochs are parsed as UTC (they are UTC by definition). The input frame
    is never mutated. Prices are fetched unless injected via ``prices``.
    """
    df = temp_df.copy()
    df = df.rename(columns={"temp": TEMPERATURE_COLUMN})
    df["Timestamp"] = pd.to_datetime(df["datetimeEpoch"], unit="s",
                                     utc=True)
    df = df.set_index("Timestamp")
    hourly = df.groupby(df.index).mean().resample("1h").asfreq()
    hourly[TEMPERATURE_COLUMN] = hourly[TEMPERATURE_COLUMN].interpolate(
        method="time", limit_area="inside")
    temp_series = hourly[TEMPERATURE_COLUMN]
    if prices is None:
        prices = get_price_series()
    return join_data(temp_series, prices)
