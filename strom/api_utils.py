from datetime import datetime
from pathlib import Path
from typing import Optional

import os
import warnings
import requests
import pandas as pd
from entsoe import EntsoePandasClient
from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

EXAMPLE_CITIES = [
    "Barcelona, ES", "Madrid, ES", "Berlin, DE", 
    "Paris, FR", "London, GB", "Rome, IT"
]

def find_root_dir(target_folder: str = "Strom") -> str:
    current_dir = os.getcwd()
    parent_dir = current_dir

    while parent_dir == current_dir or current_dir != '/':
        if target_folder in os.listdir(current_dir):
            return os.path.abspath(os.path.join(current_dir, target_folder))
        current_dir = os.path.dirname(current_dir)
    
    raise FileNotFoundError(f"'{target_folder}' folder not found in directory tree")

def read_api_key(key_path: str) -> str:
    return Path(key_path).read_text().strip()

def get_api_key(key_path: str) -> str:
    """Alias for read_api_key for backward compatibility"""
    return read_api_key(key_path)

def get_weather_api_key() -> str:
    api_key = os.getenv('WEATHER_API_KEY')
    if api_key:
        return api_key
        
    os.chdir(find_root_dir())
    return read_api_key('./config/weather_api_key.txt')

def get_weather_data(time_range: Optional[pd.DatetimeIndex] = None, city: str = "Barcelona, ES") -> pd.DataFrame:
    """Get weather for specified city. Examples: Barcelona, ES | Madrid, ES | Berlin, DE"""
    api_key = get_weather_api_key()
    
    try:
        response = requests.get(
            f"https://api.openweathermap.org/data/2.5/forecast",
            params={"q": city, "appid": api_key}
        )
        response.raise_for_status()
    except requests.RequestException as e:
        available_cities = "\n".join(f"- {city}" for city in EXAMPLE_CITIES)
        raise ValueError(
            f"Failed to fetch weather data for '{city}'. Examples:\n{available_cities}"
        ) from e
    
    data = response.json()
    weather_data = [(pd.Timestamp(entry['dt'], unit='s', tz='UTC').tz_convert('Europe/Madrid'),
                    entry['main']['temp'] - 273.15) for entry in data['list']]

    # Create a Series where the Timestamp is the index
    temperature_series = pd.Series(
        dict(weather_data),  # Convert the list of tuples to a dictionary
        name='Exterior Temperature'  # Set the name of the series
    )

    return temperature_series

def interpolate_hourly_data(df: pd.DataFrame, hours: int) -> pd.DataFrame:
    df = df.set_index('Timestamp').resample('h').interpolate()
    
    start_time = pd.Timestamp.now(tz='Europe/Madrid').floor('h')
    time_range = pd.date_range(start=start_time + pd.Timedelta(hours=1),
                              end=start_time + pd.Timedelta(hours=hours),
                              freq='h', tz='Europe/Madrid')
    
    df = df.reindex(time_range).interpolate()
    return df.bfill() if df.isnull().values.any() else df

def get_spain_electricity_prices(time_range: Optional[pd.DatetimeIndex] = None) -> pd.DataFrame:
    price_api_key = os.getenv('PRICE_API_KEY') or read_api_key('./config/price_api_key.txt')
    client = EntsoePandasClient(api_key=price_api_key)
    
    if time_range is None:
        start = pd.Timestamp.now(tz='Europe/Madrid')
        end = start + pd.Timedelta(hours=24)
        time_range = pd.date_range(start=start, end=end, freq='h', tz='Europe/Madrid')
    else:
        start = time_range[0]
        end = time_range[-1]
    
    price_series = client.query_day_ahead_prices('ES', start=start, end=end)
    price_series.name = 'Price'
    price_series = price_series.reindex(time_range, method='nearest')
    price_series = price_series/1000.0  # convert price from EUR/MWh to EUR/kWh
    return price_series

def get_price_series(time_range: Optional[pd.DatetimeIndex] = None) -> pd.Series: #TODO: expand to other countries
    return get_spain_electricity_prices(time_range = time_range)