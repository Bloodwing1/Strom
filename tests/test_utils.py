from strom import optimization_utils
from strom.api_utils import read_api_key as get_api_key, get_weather_data, get_prices
from strom.data_utils import get_temp_price_df, join_data

import numpy as np

def test_get_api_key():
    test_key_path = './tests/test_price_api_key.txt'
    api_key = get_api_key(test_key_path)
    assert api_key == 'test123'

def test_get_weather_data():
    temp_df = get_weather_data(city="Oslo")
    assert temp_df.shape[1] == 1
    #check that all values are non nan
    assert not temp_df.isnull().values.any()
    #check that the dataframe has a column whose name is 'Exterior Temperature'
    assert 'Exterior Temperature' in temp_df.columns

def test_get_weather_data_different_cities():
    oslo_df = get_weather_data(city="Oslo")
    bergen_df = get_weather_data(city="Bergen")
    
    assert oslo_df.shape == bergen_df.shape
    assert not oslo_df['Exterior Temperature'].equals(bergen_df['Exterior Temperature'])
    assert oslo_df.shape[1] == 1

def test_join_data():
    weather_df = get_weather_data(city="Oslo")
    prices_df = get_prices()

    df = join_data(weather_df, prices_df)
    assert df.shape[1] == 2
    assert 'Exterior Temperature' in df.columns
    assert 'Price' in df.columns

def test_get_temp_price_df():
    temp_price_df = get_temp_price_df()
    assert temp_price_df.shape[1] == 2
    assert 'Exterior Temperature' in temp_price_df.columns
    assert 'Price' in temp_price_df.columns
    #check that there are no nan values
    assert temp_price_df.isnull().values.any() == False
    #check that the period is 1 hour for each row
    assert (temp_price_df.index[1] - temp_price_df.index[0]).seconds == 3600

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