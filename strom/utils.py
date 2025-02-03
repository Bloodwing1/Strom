import numpy as np
import matplotlib.pyplot as plt
import cvxpy as cp

import requests
from datetime import datetime
import pandas as pd
import os
import xml.etree.ElementTree as ET

from entsoe import EntsoePandasClient
import pandas as pd

def find_root_dir(target_folder="Strom"):
    """
    Recursively searches for the specified target folder in the current directory
    and its parent directories, returning the absolute path to the target folder
    if found.
    Args:
        target_folder (str): The name of the folder to search for. Defaults to "Strom".
    Returns:
        str: The absolute path to the target folder if found.
    Raises:
        FileNotFoundError: If the target folder is not found in the current directory
                           or any of its parent directories.
    """
    current_dir = os.getcwd()
    
    while True:
        if target_folder in os.listdir(current_dir):
            return os.path.abspath(os.path.join(current_dir, target_folder))
        
        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:  # Reached the filesystem root
            raise FileNotFoundError(f"'{target_folder}' folder not found in any parent directories.")
        
        current_dir = parent_dir

def get_api_key(key_path):
    """
    Reads an API key from a file.

    Args:
        key_path (str): The path to the file containing the API key.

    Returns:
        str: The API key read from the file.
    """
    with open(key_path, 'r') as file:
        api_key = file.read().strip()  # Read the file
    return api_key

def get_weather_data():
    """
    Fetches weather data for Barcelona from the OpenWeatherMap API, processes it, and returns a DataFrame with hourly temperature data.
    The function performs the following steps:
    1. Reads the OpenWeatherMap API key from a configuration file.
    2. Makes an API call to fetch the weather forecast data for Barcelona.
    3. Parses the JSON response to extract timestamps and temperatures.
    4. Converts the timestamps to the 'Europe/Madrid' timezone.
    5. Converts temperatures from Kelvin to Celsius.
    6. Interpolates missing data points to generate an hourly temperature DataFrame.
    7. Ensures the DataFrame covers exactly a 24-hour range starting from the current hour.
    Returns:
        pd.DataFrame: A DataFrame with two columns:
            - 'Timestamp': Timestamps in the 'Europe/Madrid' timezone.
            - 'Temperature (°C)': Temperatures in Celsius.
    """
    time_steps = 24  # 24 hours in a day

    # open weather map API key text file
    os.chdir(find_root_dir())
    with open('./config/weather_api_key.txt') as f:
        API_KEY = f.read().strip()

    call_str = "https://api.openweathermap.org/data/2.5/forecast?q=Barcelona&appid=" + API_KEY

    # Make the API call
    response = requests.get(call_str)

    # Check if the request was successful (status code 200)
    if response.status_code == 200:
        data = response.json()  # Parse the JSON response

        # Prepare lists for timestamps and temperatures
        timestamps = [
            pd.Timestamp(entry['dt'], unit='s', tz='UTC').tz_convert('Europe/Madrid')  # Convert to Madrid timezone
            for entry in data['list']
        ]
        temperatures = [entry['main']['temp'] for entry in data['list']]

        # Create a DataFrame
        temp_df = pd.DataFrame({
            'Timestamp': timestamps,
            'Temperature (K)': temperatures
        })

        # Convert temperature from Kelvin to Celsius
        temp_df['Temperature (°C)'] = temp_df['Temperature (K)'] - 273.15
        # Remove the temperature in Kelvin
        temp_df = temp_df.drop(columns=['Temperature (K)'])
    else:
        print(f"Error: {response.status_code}")

    # This is a 3-hour forecast, so we have 8 data points per day, interpolate the missing data points
    temp_df = temp_df.set_index('Timestamp').resample('h').interpolate().reset_index()

    # Generate exactly 24-hour range
    start_time = pd.Timestamp.now(tz='Europe/Madrid').floor('h')
    end_time = start_time + pd.Timedelta(hours=time_steps)
    full_range = pd.date_range(start=start_time + pd.Timedelta(hours=1), end=end_time, freq='h', tz='Europe/Madrid')
    temp_df = temp_df.set_index('Timestamp').reindex(full_range).interpolate()
    temp_df.columns = ['Temperature (°C)']  # Rename columns

    # if there are nan values, fill them with the previous value
    if temp_df.isnull().values.any():
        print(f"Warning: There are NaN values in the DataFrame, filling in {temp_df.isnull().sum()} NaN values.")
        temp_df.fillna(method='bfill', inplace=True)
    return temp_df

def get_prices():
    """
    Fetches the day-ahead electricity prices for Spain using the EntsoePandasClient.
    This function retrieves the API key from a specified configuration file, initializes the 
    EntsoePandasClient with the API key, and queries the day-ahead electricity prices for Spain 
    for the next 24 hours starting from the current time in the 'Europe/Madrid' timezone. The 
    resulting prices are returned as a pandas DataFrame with timestamps and corresponding prices.
    Returns:
        pandas.DataFrame: A DataFrame containing the timestamps and corresponding day-ahead 
        electricity prices for Spain, in kWh.
    Note:
        Ensure that the API key is correctly placed in the './config/price_api_key.txt' file as 
        specified in the readme.
    """
    price_api_key = get_api_key('./config/price_api_key.txt')  # Please see readme to see how to create your config folder with the API key

    # Replace with your API key
    client = EntsoePandasClient(api_key=price_api_key)

    # Define the current timestamp (now) and timezone
    start = pd.Timestamp.now(tz='Europe/Madrid')  # Current time in Madrid timezone
    end = start + pd.Timedelta(hours=24)  # 24 hours after the current time

    #make a dataframe with one column for the timestamp and one for the price
    timestamp_index = pd.date_range(start=start, end=end, freq='h', tz='Europe/Madrid')



    # Country code for Spain
    country_code = 'ES'  # Spain

    # Querying the day-ahead prices for Spain
    prices_series = client.query_day_ahead_prices(country_code, start=start, end=end)

    # Convert the Series to a DataFrame and reindex to get exactly 24 hours
    prices_df = prices_series.to_frame(name='Price')
    prices_df = prices_df.reindex(timestamp_index, method='nearest').head(24)

    # divide the prices by 1000 to get the price in €/kWh
    prices_df['Price'] = prices_df['Price'] / 1000

    return prices_df

def join_data(temp_df, prices_df):
    """
    Merge temperature and price dataframes on the 'Timestamp' column and extract temperature and prices as numpy arrays.
    Parameters:
    temp_df (pd.DataFrame): DataFrame containing temperature data with a 'Timestamp' column.
    prices_df (pd.DataFrame): DataFrame containing price data with a 'Timestamp' column.
    Returns:
    pd.DataFrame: Merged DataFrame containing both temperature and price data.
    """
    
    # Reindex temp_df to match the timestamps of prices_df
    temp_df_reindexed = temp_df.reindex(prices_df.index.union(temp_df.index)).interpolate(method='time')

    # Fill any remaining NaN values after interpolation
    temp_df_reindexed = temp_df_reindexed.fillna(method='bfill').fillna(method='ffill')

    # Reindex again to match exactly the prices_df index
    temp_df_reindexed = temp_df_reindexed.reindex(prices_df.index)
    temp_price_df = pd.merge(temp_df_reindexed, prices_df, left_index=True, right_index=True, how='inner')

    return temp_price_df  # Returning the merged dataframe

def get_temp_price_df():
    temp_df = get_weather_data()
    prices_df = get_prices()
    temp_price_df = join_data(temp_df, prices_df)
    return temp_price_df

def find_heating_decision(temp_price_df, type = "optimal", decision = 'relaxed',
                            heat_loss = 0.1,  # Heat loss rate per degree difference per hour
                            heating_power = 2,  # Heating rate (degrees per hour)
                            min_temperature = 18,  # Minimum temperature constraint (°C)
                          ):
    """
    Determines the optimal heating decision for a given day based on outdoor temperature and electricity price.
    Parameters:
    temp_price_df (pd.DataFrame): A DataFrame containing two columns:
        - "Temperature (°C)": Outdoor temperature for each hour of the day.
        - "Price": Electricity price for each hour of the day.
    Returns:
    array: The optimal state of the heater (on/off) throughout the day.
    """

    # Parameters
    time_steps = 24  # 24 hours in a day

    # Simulate outdoor temperature (cool at night, warm in the day)
    outdoor_temperature = temp_price_df["Temperature (°C)"]

    initial_temperature = min_temperature  # Initial temperature (°C)

    # Constraints
    constraints = []

    if decision == 'relaxed':
        # Decision variables
        heater_state = cp.Variable(time_steps)

        # Heater state constraint (continuous between 0 and 1)
        constraints.append(heater_state >= 0)
        constraints.append(heater_state <= 1)

    elif decision == 'discrete':
        # Decision variables
        heater_state = cp.Variable(time_steps, boolean=True)

    indoor_temperature = cp.Variable(time_steps)

    # Objective: Minimize monetary cost (optimal) or temperature deviation from 20°C (baseline)
    if type == "optimal":
        cost = cp.sum(cp.multiply(temp_price_df["Price"], heater_state * heating_power))
    elif type == "baseline":
        cost = cp.sum(cp.abs(indoor_temperature - min_temperature))
    objective = cp.Minimize(cost)

    # Initial temperature constraint
    constraints.append(indoor_temperature[0] == initial_temperature)

    # Minimum temperature constraint
    constraints += [indoor_temperature >= min_temperature]

    # Thermal dynamics constraints
    for t in range(1, time_steps):
        heat_loss_effect = heat_loss * (indoor_temperature[t - 1] - outdoor_temperature[t - 1])
        constraints.append(
            indoor_temperature[t] == indoor_temperature[t - 1]
            + heater_state[t] * heating_power
            - heat_loss_effect
        )

    # Problem definition
    problem = cp.Problem(objective, constraints)

    # Solve the problem
    problem.solve()
    decision = heater_state.value
    indoor_temp = indoor_temperature.value
    return decision, indoor_temp

def compare_decision_costs(temp_price_df,
                            heat_loss = 0.1,  # Heat loss rate per degree difference per hour
                            heating_power = 2,  # Heating rate (degrees per hour)
                            min_temperature = 18,  # Minimum temperature constraint (°C)
                           ):
    """
    Compares the costs of the optimal and baseline heating decisions for a given day.
    Parameters:
    temp_price_df (pd.DataFrame): A DataFrame containing two columns:
        - "Temperature (°C)": Outdoor temperature for each hour of the day.
        - "Price": Electricity price for each hour of the day.
    Returns:
    tuple: A tuple containing the costs of the optimal and baseline heating decisions.
    """
    # Get the optimal heating decision
    optimal_decision, optimal_indoor_temperature  = find_heating_decision(temp_price_df, type = "optimal",
                                                                        heat_loss = heat_loss,
                                                                        heating_power = heating_power,
                                                                        min_temperature = min_temperature)
    
    baseline_decision, baseline_indoor_temperature = find_heating_decision(temp_price_df, type = "baseline",
                                                                        heat_loss = heat_loss,
                                                                        heating_power = heating_power,
                                                                        min_temperature = min_temperature)

    # Calculate the cost of the optimal decision
    optimal_cost= temp_price_df["Price"] * optimal_decision

    # Calculate the cost of the baseline decision
    baseline_cost = temp_price_df["Price"] * baseline_decision

    # merge all the 4 data into one dataframe
    compare_df = pd.DataFrame({
        'Optimal Cost': optimal_cost,
        'Baseline Cost': baseline_cost,
        'Optimal Indoor Temperature': optimal_indoor_temperature,
        'Baseline Indoor Temperature': baseline_indoor_temperature,
        'Price': temp_price_df['Price']
    })

    return compare_df



def plot_costs_and_temps(compare_df):
    """
    Plots the costs of the optimal and baseline decisions and temperatures with two different axes.
    Args:
        compare_df (pd.DataFrame): DataFrame containing the optimal and baseline costs and temperatures.
    """

    #save the plots in the plots folder
    os.chdir(find_root_dir())

    fig, ax1 = plt.subplots()

    color = 'tab:blue'
    ax1.set_xlabel('Time (h)')
    ax1.set_ylabel('Cost (€)', color=color)
    ax1.plot(compare_df['Optimal Cost'].cumsum(), color=color, linestyle='-')
    ax1.plot(compare_df['Baseline Cost'].cumsum(), color=color, linestyle='--')
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.tick_params(axis='x', rotation=45)  # Rotate x-axis tick labels

    ax2 = ax1.twinx()  # instantiate a second axes that shares the same x-axis

    color = 'tab:red'
    ax2.set_ylabel('Indoor Temperature (°C)', color=color)  # we already handled the x-label with ax1
    ax2.plot(compare_df['Optimal Indoor Temperature'], color=color, linestyle='-')
    ax2.plot(compare_df['Baseline Indoor Temperature'], color=color, linestyle='--')
    ax2.tick_params(axis='y', labelcolor=color)
    ax2.tick_params(axis='x', rotation=45)  # Rotate x-axis tick labels

    # add a third line in yellow with the electricity price
    ax3 = ax1.twinx()
    # make the color a pale blue
    color = 'tab:grey'

    ax3.spines['right'].set_position(('outward', 60))
    ax3.plot(compare_df['Price'], color=color)
    ax3.set_ylabel('Price (€/kWh)', color=color)
    ax3.tick_params(axis='y', labelcolor=color)

    fig.tight_layout()  # otherwise the right y-label is slightly clipped
    fig.subplots_adjust(top=0.85) 

    # Add legends
    # Add legends outside the plot area
    ax1.legend(['Optimal Cost', 'Baseline Cost'], loc='upper left', bbox_to_anchor=(0.25, 1.2))
    ax2.legend(['Optimal Temperature', 'Baseline Temperature'], loc='upper left', bbox_to_anchor=(0.65, 1.2))
    ax3.legend(['Price'], loc='upper left', bbox_to_anchor=(0.0, 1.2))

    # Save the plot
    plt.savefig('./plots/compare_costs_temps.png', bbox_inches='tight')

    plt.show()