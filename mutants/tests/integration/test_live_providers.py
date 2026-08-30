"""Live provider canaries (audit issue 35).

These tests require real API keys and network access. They are marked
``integration`` and excluded from the default deterministic gate; run them
explicitly with ``pytest -m integration`` (CI does this on a schedule).
"""

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not os.getenv("WEATHER_API_KEY"),
                    reason="WEATHER_API_KEY not set")
def test_live_weather_provider():
    from strom.api_utils import get_weather_data

    series = get_weather_data("Barcelona, ES")
    assert not series.empty
    assert str(series.index.tz) == "UTC"
    assert series.index.is_monotonic_increasing


@pytest.mark.skipif(not os.getenv("PRICE_API_KEY"),
                    reason="PRICE_API_KEY not set")
def test_live_price_provider():
    from strom.api_utils import get_price_series

    series = get_price_series("ES")
    assert not series.empty
    assert str(series.index.tz) == "UTC"
