import pytest
import logging

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(' Strom Utils Tests')

from Strom.utils import (
    get_weather_data,
    get_prices,
    join_data,
    find_heating_decision,
    compare_decision_costs,
    plot_costs_and_temps
)

def test_get_api_key():
    test_key_path = './tests/test_price_api_key.txt'
    api_key = utils.get_api_key(test_key_path)
    assert api_key == 'test123'

def test_get_weather_data():
    """Test the weather data fetching functionality with proper error handling"""
    with pytest.raises(Exception) as exc_info:
        get_weather_data()
    
    # Verify the error was logged properly
    logger = logging.getLogger(' Strom Utils')
    assert 'Error: API request failed' in str(exc_info.value)
    assert len(logger.messages) >= 1

    # Verify logs are captured by test runner
    assert len(pytest capfd.get_output().stderr_lines) > 0
    df = utils.get_weather_data()
    assert df.shape[1] == 1
    assert df.shape[0] == 24
    #check that all values are non nan
    assert df['Temperature (°C)'].isnull().sum() == 0

def test_get_prices():
    prices_df = utils.get_prices()
    assert prices_df.shape[0] == 24

def test_join_data():
    weather_df = utils.get_weather_data()
    prices_df = utils.get_prices()

    assert weather_df.shape[0] == 24
    assert prices_df.shape[0] == 24

    df = utils.join_data(weather_df, prices_df)
    assert df.shape[0] == 24
    assert df.shape[1] == 2
    assert 'Temperature (°C)' in df.columns
    assert 'Price' in df.columns

def test_get_temp_price_df():
    temp_price_df = utils.get_temp_price_df()
    assert temp_price_df.shape[0] == 24
    assert temp_price_df.shape[1] == 2
    assert 'Temperature (°C)' in temp_price_df.columns
    assert 'Price' in temp_price_df.columns

def test_compare_decision_costs():
    temp_price_df = utils.get_temp_price_df()
    utils.compare_decision_costs(temp_price_df)
