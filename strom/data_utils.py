import pandas as pd
from .api_utils import get_weather_data, get_price_series

def join_data(temp_series, price_series):
    """
    Merge temperature and price dataframes on the 'Timestamp' column and extract temperature and prices as numpy arrays.
    Parameters:
    temp_df (pd.DataFrame): DataFrame containing temperature data with a 'Timestamp' column.
    prices_df (pd.DataFrame): DataFrame containing price data with a 'Timestamp' column.
    Returns:
    pd.DataFrame: Merged DataFrame containing both temperature and price data.
    """
    temp_price_df = pd.concat([temp_series, price_series], axis=1)
    temp_price_df.sort_index(inplace=True)
    temp_price_df = temp_price_df.interpolate(method='cubic').bfill().ffill()
    return temp_price_df

def regularize_df(df):
    df_resamp = df.resample('1h').asfreq()
    merged_df = df_resamp.interpolate(method='cubic', limit_direction='both').bfill().ffill()
    return merged_df

def get_temp_price_df():
    temp_series = get_weather_data()
    prices_series = get_price_series()
    temp_price_df = join_data(temp_series, prices_series)
    temp_price_df = regularize_df(temp_price_df)
    return temp_price_df