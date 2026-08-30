"""API contract tests (audit issue 35).

All providers are exercised through injected fake clients and local
fixtures: no network, no secrets, no wall clock.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import requests

from strom.api_utils import get_price_series, get_weather_data
from strom.errors import PriceProviderError, WeatherProviderError


class FakeResponse:
    def __init__(self, payload=None, status=200, json_exc=None):
        self.payload = payload
        self.status_code = status
        self.json_exc = json_exc

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error",
                                     response=self)

    def json(self):
        if self.json_exc:
            raise self.json_exc
        return self.payload


def valid_weather_payload():
    return {
        "list": [
            {"dt": 1735689600, "main": {"temp": 283.15}},
            {"dt": 1735700400, "main": {"temp": 284.15}},
            {"dt": 1735711200, "main": {"temp": 282.15}},
        ]
    }


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


class FakeEntsoe:
    def __init__(self, series=None, exc=None):
        self.series = series
        self.exc = exc
        self.calls = []

    def query_day_ahead_prices(self, zone, start, end):
        self.calls.append((zone, start, end))
        if self.exc is not None:
            raise self.exc
        return self.series


def madrid_price_series(hours=26, eur_mwh=50.0):
    """Mimic the real client: market-time (Europe/Madrid) index, EUR/MWh."""
    index = pd.date_range("2025-01-01 00:00", periods=hours, freq="h",
                          tz="Europe/Madrid")
    return pd.Series(np.full(hours, eur_mwh), index=index, name="Price")


class TestWeatherContract:
    @pytest.fixture(autouse=True)
    def api_key(self, monkeypatch):
        monkeypatch.setenv("WEATHER_API_KEY", "secret-key")

    def test_valid_payload_returns_utc_series(self):
        http = FakeHttp([FakeResponse(valid_weather_payload())])
        series = get_weather_data("Barcelona, ES", http_get=http,
                                  sleep=lambda s: None)
        assert series.name == "ExteriorTemperature"
        assert str(series.index.tz) == "UTC"
        assert series.index.is_monotonic_increasing
        assert series.iloc[0] == pytest.approx(10.0)  # K -> C conversion
        assert http.calls[0]["timeout"] is not None

    def test_malformed_payload_rejected(self):
        for payload in ([], {"foo": 1}, {"list": [{"nope": 1}]}):
            http = FakeHttp([FakeResponse(payload)])
            with pytest.raises(WeatherProviderError, match="malformed|missing|not a JSON"):
                get_weather_data("X", http_get=http, sleep=lambda s: None)

    def test_empty_forecast_rejected(self):
        http = FakeHttp([FakeResponse({"list": []})])
        with pytest.raises(WeatherProviderError, match="empty forecast"):
            get_weather_data("X", http_get=http, sleep=lambda s: None)

    def test_invalid_json_rejected(self):
        http = FakeHttp([FakeResponse(json_exc=ValueError("bad json"))])
        with pytest.raises(WeatherProviderError, match="JSON"):
            get_weather_data("X", http_get=http, sleep=lambda s: None)

    def test_auth_failure_is_not_retried_and_hides_key(self):
        http = FakeHttp([FakeResponse(status=401)])
        with pytest.raises(WeatherProviderError) as info:
            get_weather_data("X", http_get=http, sleep=lambda s: None)
        assert len(http.calls) == 1
        assert "secret-key" not in str(info.value)

    def test_rate_limit_is_retried_then_typed_error(self):
        http = FakeHttp([FakeResponse(status=429)])
        sleeps = []
        with pytest.raises(WeatherProviderError) as info:
            get_weather_data("X", http_get=http, max_attempts=3,
                             sleep=sleeps.append)
        assert len(http.calls) == 3  # bounded retries
        assert len(sleeps) == 2
        assert sleeps[1] > sleeps[0]  # exponential backoff
        assert info.value.retryable

    def test_server_error_is_retried(self):
        http = FakeHttp([FakeResponse(status=503),
                         FakeResponse(status=503),
                         FakeResponse(valid_weather_payload())])
        series = get_weather_data("X", http_get=http, sleep=lambda s: None)
        assert len(series) == 3

    def test_timeout_is_transient(self):
        def http_get(url, params=None, timeout=None):
            raise requests.Timeout("timed out")

        with pytest.raises(WeatherProviderError) as info:
            get_weather_data("X", http_get=http_get, sleep=lambda s: None)
        assert info.value.retryable

    def test_client_error_not_retried(self):
        http = FakeHttp([FakeResponse(status=404)])
        with pytest.raises(WeatherProviderError):
            get_weather_data("X", http_get=http, sleep=lambda s: None)
        assert len(http.calls) == 1


class TestPriceContract:
    def test_valid_response_converted_to_utc_and_kw(self):
        client = FakeEntsoe(series=madrid_price_series())
        series = get_price_series("ES", client=client, sleep=lambda s: None)
        assert str(series.index.tz) == "UTC"
        assert series.iloc[0] == pytest.approx(0.05)  # EUR/MWh -> EUR/kWh
        assert series.index.is_monotonic_increasing
        zone, start, end = client.calls[0]
        assert zone == "ES" and start < end

    def test_no_published_prices_fail_fast(self):
        from entsoe.exceptions import NoMatchingDataError

        client = FakeEntsoe(exc=NoMatchingDataError())
        with pytest.raises(PriceProviderError, match="No day-ahead prices"):
            get_price_series("ES", client=client, sleep=lambda s: None)
        assert len(client.calls) == 1  # not retried

    def test_rate_limit_retried_bounded(self):
        client = FakeEntsoe(
            exc=requests.HTTPError("429", response=FakeResponse(status=429)))
        with pytest.raises(PriceProviderError) as info:
            get_price_series("ES", client=client, max_attempts=3,
                             sleep=lambda s: None)
        assert len(client.calls) == 3
        assert info.value.retryable

    def test_empty_series_rejected(self):
        client = FakeEntsoe(series=pd.Series(dtype=float))
        with pytest.raises(PriceProviderError, match="no price data"):
            get_price_series("ES", client=client, sleep=lambda s: None)

    def test_naive_index_rejected(self):
        naive = pd.Series(np.full(3, 50.0),
                          index=pd.DatetimeIndex(
                              ["2025-01-01", "2025-01-02", "2025-01-03"]))
        client = FakeEntsoe(series=naive)
        with pytest.raises(PriceProviderError, match="timezone"):
            get_price_series("ES", client=client, sleep=lambda s: None)

    def test_error_messages_hide_api_key(self, monkeypatch):
        monkeypatch.setenv("PRICE_API_KEY", "topsecret-key")
        client = FakeEntsoe(
            exc=requests.HTTPError("boom for topsecret-key",
                                   response=FakeResponse(status=429)))
        with pytest.raises(PriceProviderError) as info:
            get_price_series("ES", client=client, max_attempts=1,
                             sleep=lambda s: None)
        assert "topsecret-key" not in str(info.value)
