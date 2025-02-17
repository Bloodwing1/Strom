# Strom: Smart Heating Optimization System

## Introduction

Strom is an intelligent heating control system that optimizes energy usage based on weather forecasts and electricity price data. By leveraging convex optimization techniques, Strom determines the most cost-effective heating schedule while maintaining thermal comfort, automatically controlling a smart plug to implement the optimal heating plan.

This documentation will guide you through setting up and using the Strom system.

## System Overview

Strom consists of three main components:

1. **Data Collection**: Automatically fetches weather forecasts and electricity price data
2. **Optimization Engine**: Determines optimal heating schedules based on collected data
3. **Hardware Control**: Controls a TP-Link Kasa smart plug to implement the heating schedule

### Key Features

- Real-time weather data fetching via OpenWeatherMap API
- Electricity price data retrieval from ENTSO-E API
- Convex optimization for cost-effective heating decisions
- Smart plug control via the Kasa library
- Visualization tools for analyzing heating strategies and cost savings

## Prerequisites

Before you begin, ensure you have:

- Python 3.8 or newer installed
- A TP-Link Kasa smart plug (with known IP address)
- API keys for OpenWeatherMap and ENTSO-E
- A network connection

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/strom.git
   cd strom
   ```

2. Install required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create necessary configuration files:
   - Create a `config` directory in the root of the project
   - Add your API keys and credentials (see Configuration section)

## Configuration

### API Keys Setup

1. Create the following files in the `config` directory:

   - `weather_api_key.txt`: Contains your OpenWeatherMap API key
   - `price_api_key.txt`: Contains your ENTSO-E API key
   - `tapologin.env`: Contains your TP-Link Kasa login credentials

2. For the `tapologin.env` file, use the following format:
   ```
   EMAIL=your_tplink_account_email
   PASSWORD=your_tplink_account_password
   ```

### Device Configuration

Update the `device_ip` variable in `main.py` with the IP address of your Kasa smart plug:

```python
device_ip = "192.168.1.16"  # Replace with your device's IP address
```

## Usage

### Basic Usage

To run the system and apply the optimal heating decision for the current hour:

```bash
python main.py
```

This will:
1. Fetch current weather and price data
2. Determine the optimal heating decision
3. Control the smart plug accordingly

### Customizing Heating Parameters

You can modify the heating parameters in the `find_heating_decision` function call in `main.py`:

```python
user_input = bool(utils.find_heating_decision(
    temp_price_df,
    decision='discrete',
    heat_loss=0.1,             # Adjust heat loss rate
    heating_power=2,           # Adjust heating power
    min_temperature=18         # Adjust minimum temperature
)[0][0])
```

### Analysis and Visualization

To analyze and visualize the performance of different heating strategies:

```python
# In a Python script or notebook
from strom import utils

# Get temperature and price data
temp_price_df = utils.get_temp_price_df()

# Compare optimal vs baseline strategies
compare_df = utils.compare_decision_costs(
    temp_price_df,
    heat_loss=0.1,
    heating_power=2,
    min_temperature=18
)

# Generate visualization
utils.plot_costs_and_temps(compare_df)
```

## Technical Details

### Data Collection

#### Weather Data

Weather data is fetched from OpenWeatherMap for Barcelona. The system:
- Gets 3-hour forecast data
- Interpolates to create hourly temperature forecasts
- Converts temperatures from Kelvin to Celsius

#### Electricity Price Data

Price data is fetched from ENTSO-E for Spain. The system:
- Gets day-ahead market prices
- Converts prices to €/kWh
- Aligns timestamps with weather data

### Optimization Logic

The optimization uses convex programming (via CVXPY) to determine when to heat based on:

1. **Objective Function**: Minimize electricity cost while maintaining comfort
2. **Constraints**:
   - Indoor temperature must stay above minimum threshold
   - Thermal dynamics model (heating power, heat loss rate)
   - Initial temperature conditions

The optimization can run in two decision modes:
- **Relaxed**: Allows continuous values between 0-1 (partial heating)
- **Discrete**: Binary decisions (on/off)

And two optimization types:
- **Optimal**: Minimize monetary cost
- **Baseline**: Minimize temperature deviation from target

### Thermal Model

The system models building thermal dynamics with these parameters:

- `heat_loss`: Rate at which the building loses heat to the outdoors (°C/hr per °C difference)
- `heating_power`: Rate at which the heater can increase indoor temperature (°C/hr)
- `min_temperature`: Minimum acceptable indoor temperature (°C)

## Advanced Topics

### Customizing Location

To change the location for weather data:
1. Modify the city parameter in the API call in `get_weather_data()`:
   ```python
   call_str = "https://api.openweathermap.org/data/2.5/forecast?q=YourCity&appid=" + API_KEY
   ```

### Customizing Country for Electricity Prices

To change the country for electricity prices:
1. Modify the country code in `get_prices()`:
   ```python
   country_code = 'XX'  # Replace with your country code
   ```

### Scheduling

For automated operation, consider setting up a cron job (Linux/Mac) or Task Scheduler (Windows) to run `main.py` at regular intervals.

## Troubleshooting

### API Connection Issues

If you encounter API connection issues:
1. Verify your API keys are correct
2. Check your internet connection
3. Ensure you haven't exceeded API rate limits

### Smart Plug Connection Issues

If you have trouble connecting to your smart plug:
1. Verify the IP address is correct
2. Ensure the smart plug is connected to your network
3. Check that your TP-Link credentials are correct

## Contributing

Contributions to Strom are welcome! To contribute:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request with a clear description of your changes

## License

This project is licensed under the MIT License - see the LICENSE file for details.