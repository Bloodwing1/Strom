This repository appears to be an energy optimization system that controls a smart plug (likely for a heater) based on temperature forecasts and electricity prices. I'll walk through the functions and explain how they work together to create an intelligent heating system that minimizes costs while maintaining comfort.

## Main Components and Flow

The system has three main components:
1. Smart plug control (using Kasa smart plugs)
2. Data collection (weather and electricity prices)
3. Optimization algorithm (to decide when to heat)

The `main.py` file ties everything together, while `utils.py` contains the core functionality for data collection and optimization.

Let's break this down step by step:

## Main Execution Flow (`main.py`)

The main script discovers and controls a TP-Link Kasa smart device (likely a smart plug connected to a heater). Here's what it does:

1. Loads login credentials from a `.env` file
2. Connects to the smart device at a specific IP address
3. Gets temperature and price data by calling `utils.get_temp_price_df()`
4. Makes a heating decision by calling `utils.find_heating_decision()`
5. Turns the device on or off based on that decision

The key part is this line:
```python
user_input = bool(utils.find_heating_decision(temp_price_df, decision = 'discrete')[0][0])
```
This calls the optimization function and takes the first decision (current hour) to determine if the heater should be on (True) or off (False).

## Utility Functions (`utils.py`)

Let's go through the key utility functions:

### `find_root_dir()`
This function helps locate the root directory of the project, which is important for finding configuration files.

### `get_api_key()`
A simple function to read API keys from files.

### `get_weather_data()`
This function:
1. Gets the API key for OpenWeatherMap
2. Makes an API call to fetch weather data for Barcelona
3. Processes the response to extract temperature forecasts
4. Converts temperatures from Kelvin to Celsius
5. Interpolates to get hourly temperatures for the next 24 hours

### `get_prices()`
This function:
1. Gets the API key for the ENTSO-E platform (European Network of Transmission System Operators for Electricity)
2. Queries the day-ahead electricity prices for Spain
3. Processes the response to get prices in €/kWh for the next 24 hours

### `join_data()`
Merges the temperature and price data into a single DataFrame indexed by timestamp.

### `get_temp_price_df()`
A wrapper function that calls `get_weather_data()`, `get_prices()`, and `join_data()` to create a combined DataFrame with both temperature and price information.

### `find_heating_decision()`
This is the core optimization function that:
1. Takes the temperature and price DataFrame as input
2. Uses convex optimization (via the `cvxpy` library) to determine when to run the heater
3. Balances cost minimization with maintaining a minimum temperature
4. Can run in different modes:
   - "optimal" (minimize cost)
   - "baseline" (keep temperature close to target)
5. Can make "relaxed" (continuous 0-1) or "discrete" (binary on/off) decisions

The function models the thermal dynamics of the home, including heat loss to the outdoors, and finds the optimal heating schedule within constraints.

### `compare_decision_costs()`
Compares the costs and temperatures of the optimal and baseline heating strategies.

### `plot_costs_and_temps()`
Creates visualization plots comparing the costs, temperatures, and electricity prices over time.

## How Everything Works Together

Here's the full flow:

1. `main.py` is executed and connects to the Kasa device
2. It calls `get_temp_price_df()` which:
   - Gets weather forecast data
   - Gets electricity price data
   - Combines them into one DataFrame
3. It calls `find_heating_decision()` with this data to determine the optimal heating schedule
4. It takes the first decision (for the current hour) and turns the smart plug on or off accordingly
5. It prints the device state to confirm the action

## Key Features of the Optimization

The optimization uses convex programming to make intelligent heating decisions based on:
1. Forecasted outdoor temperature (from OpenWeatherMap)
2. Hourly electricity prices (from ENTSO-E)
3. Thermal characteristics of the home (heat loss rate)
4. Heating system capabilities (heating power)
5. Comfort constraints (minimum temperature)

The goal is to maintain comfort (temperature above minimum) while minimizing electricity costs, taking advantage of times when:
- Electricity is cheaper
- Outdoor temperature is higher (requiring less heating)

## Analysis and Visualization

The repository also includes functions to analyze and visualize the performance of the optimization:
- `compare_decision_costs()` compares optimal vs. baseline strategies
- `plot_costs_and_temps()` creates visualizations showing the cumulative costs, indoor temperatures, and electricity prices over time

This allows the user to see the benefits of the optimization approach compared to a simpler temperature-based approach.

## Summary

This repository creates a smart heating system that:
1. Collects real-time data (weather forecasts and electricity prices)
2. Uses optimization to determine the most cost-effective heating schedule
3. Controls a smart plug to implement that schedule
4. Provides analysis tools to evaluate performance

It's an excellent example of applying optimization techniques to create a practical, cost-saving smart home application.