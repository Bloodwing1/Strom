import pandas as pd
from .api_utils import get_weather_data, get_prices

def join_data(temp_df, prices_df):
    """
    Merge temperature and price dataframes on the 'Timestamp' column and extract temperature and prices as numpy arrays.
    Parameters:
    temp_df (pd.DataFrame): DataFrame containing temperature data with a 'Timestamp' column.
    prices_df (pd.DataFrame): DataFrame containing price data with a 'Timestamp' column.
    Returns:
    pd.DataFrame: Merged DataFrame containing both temperature and price data.
    """
    
    temp_df_reindexed = temp_df.reindex(prices_df.index.union(temp_df.index)).interpolate(method='time')
    temp_df_reindexed = temp_df_reindexed.bfill().ffill()
    temp_df_reindexed = temp_df_reindexed.reindex(prices_df.index)
    temp_price_df = pd.merge(temp_df_reindexed, prices_df, left_index=True, right_index=True, how='inner')
    return temp_price_df

def regularize_df(df):

    df_resamp = df.resample('1h').asfreq()
    # make a new dataframe without any columns
    df_resamp = df_resamp.drop(columns = df_resamp.columns)

    #merge dataframes
    merged_df = pd.merge(df_resamp, df, left_index=True, right_index=True, how='outer')
    #interpolate the missing values
    merged_df = merged_df.interpolate(method='cubic')

    #extrapolate the missing values
    merged_df = merged_df.interpolate(method='cubic', limit_direction='both')
    # take only the rows with indices present in the resampled dataframe
    merged_df = merged_df[merged_df.index.isin(df_resamp.index)]

    #remove rows with Nan
    merged_df = merged_df.dropna()
    return merged_df


def get_temp_price_df():
    temp_df = get_weather_data()
    prices_df = get_prices()
    temp_price_df = join_data(temp_df, prices_df)
    temp_price_df = regularize_df(temp_price_df)
    return temp_price_df