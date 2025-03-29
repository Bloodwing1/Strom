from strom import optimization_utils
from strom.api_utils import read_api_key as get_api_key, get_weather_data, get_price_series
from strom.data_utils import get_temp_price_df, join_data

import numpy as np
import pandas as pd

def test_get_api_key():
    test_key_path = './tests/test_price_api_key.txt'
    api_key = get_api_key(test_key_path)
    assert api_key == 'test123'

def test_get_weather_data():
    temp_series = get_weather_data(city="Oslo")
    #check that all values are non nan
    assert not temp_series.isnull().values.any()
    #check that the dataframe has a column whose name is 'Exterior Temperature'
    assert temp_series.name == 'Exterior Temperature'

def test_get_weather_data_different_cities():
    oslo_series = get_weather_data(city="Oslo")
    bergen_series = get_weather_data(city="Bergen")
    
    assert len(oslo_series) == len(bergen_series)
    assert not oslo_series.equals(bergen_series)

def test_get_price_data():
    price_series = get_price_series()

def test_get_historical_price_data():
    end = pd.Timestamp.now(tz='Europe/Madrid')
    start = end - pd.Timedelta(days=29)
    time_range = pd.date_range(start=start, end=end, freq='d', tz='Europe/Madrid')

    price_series = get_price_series(time_range=time_range)
    assert len(price_series) == 30

def test_join_data():
    temp_series = get_weather_data(city="Oslo")
    price_series = get_price_series()

    df = join_data(temp_series, price_series)
    assert df.shape[1] == 2
    assert 'Exterior Temperature' in df.columns
    assert 'Price' in df.columns
    assert df.isnull().values.any() == False

def test_get_temp_price_df():
    temp_price_df = get_temp_price_df()
    assert temp_price_df.shape[1] == 2
    assert 'Exterior Temperature' in temp_price_df.columns
    assert 'Price' in temp_price_df.columns
    #check that there are no nan values
    assert temp_price_df.isnull().values.any() == False
    #check that the period is 1 hour for each row
    assert temp_price_df.index.to_series().diff().dropna().eq(pd.Timedelta(hours=1)).all()

def test_get_state_df():
    temp_price_df = get_temp_price_df()
    time_steps = len(temp_price_df)
    # make a output function that is a sine wave array
    output = np.sin(np.linspace(0, 5*2*np.pi, time_steps))
    #make the sine wave into a square wave between 0 and 1
    output = np.sign(output)
    output = (output + 1) / 2

    house = optimization_utils.House()
    state = optimization_utils.get_state_df(temp_price_df, output, house)
    assert state.shape[0] == time_steps

def test_compare_output_costs():
    temp_price_df = get_temp_price_df()
    house = optimization_utils.House(P_base=0.0)
    optimal_state_df, baseline_state_df = optimization_utils.compare_output_costs(temp_price_df, house)
    assert baseline_state_df.isnull().values.any() == False
    assert optimal_state_df.isnull().values.any() == False
    assert optimal_state_df['Cost'].sum() <= baseline_state_df['Cost'].sum()