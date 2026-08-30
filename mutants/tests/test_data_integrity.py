"""Time-series integrity tests (audit issue 34).

Synthetic series only: DST spring-forward and fall-back, duplicate and
missing intervals, negative prices, misaligned source frequencies, and
non-mutation of inputs. Everything is UTC-canonical; no network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strom.data_utils import (
    PRICE_COLUMN,
    TEMPERATURE_COLUMN,
    align_prices,
    align_weather,
    get_temp_price_df,
    get_temp_price_from_temp,
    join_data,
)
from strom.errors import CoverageError

H = pd.Timedelta(hours=1)


def utc_range(start, periods):
    return pd.date_range(start, periods=periods, freq="h", tz="UTC")


def weather_series(index, temp=10.0):
    return pd.Series(np.full(len(index), temp), index=index,
                     name=TEMPERATURE_COLUMN)


def price_series(index, price=0.10):
    return pd.Series(np.full(len(index), price), index=index,
                     name=PRICE_COLUMN)


class TestUtcCanonical:
    def test_epoch_parsing_is_utc(self):
        # 1735689600 == 2025-01-01 00:00 UTC (01:00 Madrid).
        df = pd.DataFrame({
            "datetimeEpoch": [1735689600, 1735693200],
            "temp": [10.0, 11.0],
        })
        result = get_temp_price_from_temp(df, prices=price_series(
            utc_range("2025-01-01", 2)))
        assert str(result.index.tz) == "UTC"
        assert result.index[0] == pd.Timestamp("2025-01-01 00:00", tz="UTC")

    def test_naive_input_rejected(self):
        naive = pd.Series([1.0], index=pd.DatetimeIndex(["2025-01-01"]))
        with pytest.raises(ValueError, match="timezone-aware"):
            align_weather(naive, utc_range("2025-01-01", 2))

    def test_duplicate_intervals_rejected(self):
        index = utc_range("2025-01-01", 3)
        dup = pd.concat([price_series(index), price_series(index[:1])])
        with pytest.raises(ValueError, match="duplicated"):
            align_prices(dup, index)

    def test_market_time_fall_back_stays_unique_in_utc(self):
        # 2025-10-26: Madrid repeats 02:00-03:00 local (25-hour day).
        market = pd.date_range("2025-10-26 00:00", periods=25, freq="h",
                               tz="Europe/Madrid")
        prices = price_series(market)
        utc = prices.copy()
        utc.index = market.tz_convert("UTC")
        assert utc.index.is_unique and utc.index.is_monotonic_increasing
        aligned = align_prices(utc, utc_range("2025-10-26", 24))
        assert aligned.index.is_unique

    def test_spring_forward_gap_is_covered_by_bounded_fill(self):
        # 2025-03-30: Madrid skips 02:00-03:00 local (23-hour day). The UTC
        # day still has 24 hourly intervals, one of which no market interval
        # covers; bounded fill (1h) bridges exactly that hour.
        market = pd.date_range("2025-03-30 00:00", periods=23, freq="h",
                               tz="Europe/Madrid")
        utc = price_series(market)
        utc.index = market.tz_convert("UTC")
        target = utc_range("2025-03-29 23:00", 24)
        aligned = align_prices(utc, target)
        assert not aligned.isna().any()


class TestPriceIntegrity:
    def test_exact_interval_alignment_no_interpolation(self):
        index = utc_range("2025-01-01", 4)
        prices = pd.Series([0.10, 0.20, 0.30, 0.40], index=index,
                           name=PRICE_COLUMN)
        target = utc_range("2025-01-01", 4)
        aligned = align_prices(prices, target)
        assert aligned.tolist() == [0.10, 0.20, 0.30, 0.40]

    def test_bounded_fill_within_tolerance(self):
        index = utc_range("2025-01-01", 4)
        prices = pd.Series([0.10, 0.20, np.nan, 0.40], index=index,
                           name=PRICE_COLUMN).dropna()
        aligned = align_prices(prices, index, max_fill=H)
        assert aligned.isna().sum() == 0
        assert aligned.iloc[2] == 0.20  # previous interval reused once

    def test_gap_beyond_tolerance_raises(self):
        index = utc_range("2025-01-01", 5)
        prices = pd.Series([0.10, 0.20, np.nan, np.nan, 0.50],
                           index=index, name=PRICE_COLUMN).dropna()
        with pytest.raises(CoverageError, match="No electricity price"):
            align_prices(prices, index, max_fill=H)

    def test_unpublished_horizon_raises(self):
        index = utc_range("2025-01-01", 2)
        prices = price_series(index)
        target = utc_range("2025-01-02", 4)
        with pytest.raises(CoverageError):
            align_prices(prices, target)

    def test_negative_prices_preserved(self):
        index = utc_range("2025-01-01", 3)
        prices = pd.Series([-0.05, -0.02, 0.01], index=index,
                           name=PRICE_COLUMN)
        aligned = align_prices(prices, index)
        assert aligned.tolist() == [-0.05, -0.02, 0.01]

    def test_half_hourly_source_aligns_to_hourly(self):
        # Misaligned source frequency: 30min market intervals.
        half_hourly = pd.date_range("2025-01-01", periods=8, freq="30min",
                                    tz="UTC")
        prices = pd.Series([0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.22, 0.24],
                           index=half_hourly, name=PRICE_COLUMN)
        aligned = align_prices(prices, utc_range("2025-01-01", 4),
                               max_fill=H)
        # Each hourly interval starts exactly on a market interval.
        assert aligned.tolist() == [0.10, 0.14, 0.18, 0.22]

    def test_half_hourly_gap_uses_bounded_fill(self):
        half_hourly = pd.date_range("2025-01-01", periods=8, freq="30min",
                                    tz="UTC")
        prices = pd.Series([0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.22, 0.24],
                           index=half_hourly, name=PRICE_COLUMN)
        # Drop the 01:30 half interval; 01:00-02:00 has one missing bucket.
        prices = prices.drop(pd.Timestamp("2025-01-01 01:30", tz="UTC"))
        aligned = align_prices(prices, utc_range("2025-01-01", 4),
                               max_fill=pd.Timedelta(minutes=30))
        assert aligned.tolist() == [0.10, 0.14, 0.18, 0.22]


class TestWeatherIntegrity:
    def test_bounded_linear_interpolation(self):
        obs = pd.date_range("2025-01-01", periods=3, freq="2h", tz="UTC")
        temp = pd.Series([10.0, 14.0, 18.0], index=obs,
                         name=TEMPERATURE_COLUMN)
        target = utc_range("2025-01-01", 5)
        aligned = align_weather(temp, target)
        assert aligned.iloc[1] == pytest.approx(12.0)  # midpoint of segment
        assert not aligned.isna().any()

    def test_gap_beyond_max_gap_raises(self):
        obs = pd.date_range("2025-01-01", periods=2, freq="6h", tz="UTC")
        temp = pd.Series([10.0, 20.0], index=obs, name=TEMPERATURE_COLUMN)
        target = utc_range("2025-01-01", 7)
        with pytest.raises(CoverageError, match="no observation within"):
            align_weather(temp, target, max_gap=H)

    def test_three_hourly_forecast_interpolates_to_hourly(self):
        obs = pd.date_range("2025-01-01", periods=4, freq="3h", tz="UTC")
        temp = pd.Series([10.0, 13.0, 16.0, 19.0], index=obs,
                         name=TEMPERATURE_COLUMN)
        target = utc_range("2025-01-01", 10)
        aligned = align_weather(temp, target)
        assert not aligned.isna().any()
        assert aligned.iloc[1] == pytest.approx(11.0)


class TestJoinAndHorizon:
    def test_join_data_normalizes_independently(self):
        temp_index = utc_range("2025-01-01", 6)
        price_index = utc_range("2025-01-01", 6)
        df = join_data(weather_series(temp_index), price_series(price_index))
        assert list(df.columns) == [TEMPERATURE_COLUMN, PRICE_COLUMN]
        assert str(df.index.tz) == "UTC"
        assert df.index.is_unique and df.index.is_monotonic_increasing
        assert not df.isna().values.any()

    def test_inputs_are_not_mutated(self):
        temp_index = pd.date_range("2025-01-01", periods=4, freq="3h",
                                   tz="UTC")
        price_index = utc_range("2025-01-01", 10)
        temp = weather_series(temp_index, temp=5.0)
        prices = price_series(price_index)
        temp_before = temp.copy()
        prices_before = prices.copy()
        join_data(temp, prices)
        pd.testing.assert_series_equal(temp, temp_before)
        pd.testing.assert_series_equal(prices, prices_before)

    def test_get_temp_price_df_with_injected_sources(self):
        now = pd.Timestamp("2025-01-01 13:20", tz="UTC")
        weather = weather_series(utc_range("2025-01-01 12:00", 30))
        prices = price_series(utc_range("2025-01-01 12:00", 30))
        df = get_temp_price_df(weather=weather, prices=prices, now=now,
                               horizon_hours=24)
        assert len(df) == 24
        assert df.index[0] == pd.Timestamp("2025-01-01 14:00", tz="UTC")
        assert str(df.index.tz) == "UTC"
        assert not df.isna().values.any()

    def test_get_temp_price_df_rejects_incomplete_horizon(self):
        now = pd.Timestamp("2025-01-01 13:20", tz="UTC")
        weather = weather_series(utc_range("2025-01-01 12:00", 30))
        prices = price_series(utc_range("2025-01-01 12:00", 4))
        with pytest.raises(CoverageError):
            get_temp_price_df(weather=weather, prices=prices, now=now)
