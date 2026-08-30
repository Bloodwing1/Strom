from strom import optimization_utils
from strom.api_utils import read_api_key as get_api_key

import pytest


def test_get_api_key():
    test_key_path = './tests/test_price_api_key.txt'
    api_key = get_api_key(test_key_path)
    assert api_key == 'test123'


# The remaining legacy tests in this module depend on live weather/price APIs.
# They are kept as integration canaries until the deterministic suite
# (audit issues 34/35/37) replaces them.
pytestmark = pytest.mark.integration


def test_get_weather_data():
    from strom.api_utils import get_weather_data

    temp_series = get_weather_data(city="Oslo")
    assert not temp_series.isnull().any()
    assert temp_series.name == 'ExteriorTemperature'


def test_get_weather_data_different_cities():
    from strom.api_utils import get_weather_data

    oslo_series = get_weather_data(city="Oslo")
    bergen_series = get_weather_data(city="Bergen")

    assert len(oslo_series) == len(bergen_series)
    assert not oslo_series.equals(bergen_series)


def test_get_price_data():
    from strom.api_utils import get_price_series

    get_price_series()


def test_join_data():
    from strom.api_utils import get_price_series, get_weather_data
    from strom.data_utils import join_data

    temp_series = get_weather_data(city="Oslo")
    price_series = get_price_series()

    df = join_data(temp_series, price_series)
    assert df.shape[1] == 2
    assert 'ExteriorTemperature' in df.columns
    assert 'Price' in df.columns
    assert df.isnull().values.any() == False


def test_get_temp_price_df():
    from strom.data_utils import get_temp_price_df

    temp_price_df = get_temp_price_df()
    assert temp_price_df.shape[1] == 2
    assert 'ExteriorTemperature' in temp_price_df.columns
    assert 'Price' in temp_price_df.columns
    assert temp_price_df.isnull().values.any() == False
    assert temp_price_df.index.to_series().diff().dropna().eq(
        pd.Timedelta(hours=1)).all()


def test_compare_output_costs():
    import pandas as pd

    from strom.data_utils import get_temp_price_df

    temp_price_df = get_temp_price_df()
    house = optimization_utils.House(P_base=0.0, Q_cooling=2.0)
    optimal_state_df, baseline_state_df = optimization_utils.compare_output_costs(
        temp_price_df, house)
    assert baseline_state_df.isnull().values.any() == False
    assert optimal_state_df.isnull().values.any() == False
    assert optimal_state_df['Cost'].sum() <= baseline_state_df['Cost'].sum()
