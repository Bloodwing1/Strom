# Strom Energy Management System Documentation

## Table of Contents
1. [Introduction](#introduction)
2. [Installation](#installation)
3. [Setup](#setup)
4. [Core Functionality](#core-functionality)
5. [Configuration](#configuration)
6. [Error Handling](#error-handling)

## Introduction
The Strom Energy Management System is designed to optimize energy usage by integrating with smart home devices and weather data. It provides intelligent heating control based on electricity prices and outdoor temperature.

## Installation

To install the system, follow these steps:

```bash
git clone https://github.com/yourusername/Strom.git
cd Strom
pip install -r requirements.txt
```

## Setup

1. Create a configuration directory:
   ```bash
   mkdir -p config
   ```

2. Create a `.env` file in the root directory with your credentials:
   ```bash
   touch .env
   ```

3. Edit the `.env` file to include:
   ```
   EMAIL=your@email.com
   PASSWORD=your_password_here
   DEVICE_IP=192.168.1.16
   ```

## Core Functionality

The system includes several key features:

- **Weather Data Integration**: Fetches hourly temperature data from OpenWeatherMap.
- **Electricity Price API**: retrieves real-time pricing data.
- **Heating Decision Maker**: optimizes heating based on price and temperature.
- **Smart Device Control**: interfaces with Kasa devices for heating and cooling.

### Heating Control
The main functionality includes:
```python
# Example usage in main.py:
user_input = bool(utils.find_heating_decision(
    temp_price_df,
    decision='discrete',
    heat_loss=0.1,  # Heat loss rate per degree difference per hour
    heating_power=2,  # Heating rate (degrees per hour)
    min_temperature=18  # Minimum temperature constraint (°C)
)[0]
```

## Configuration

The system uses a configuration directory structure:
```
config/
├── tapologin.env  # Login credentials for smart device
└── price_data/   # Data folder for storing price data
```

## Error Handling

The system includes comprehensive error handling with:
- Logging integration
- Try-except blocks
- Custom error messages
- Retry mechanisms for failed operations

For example, in `main.py`:
```python
try:
    # Main logic here
except Exception as e:
    logger.error(f"Main function error: {e}")
    raise
```

Would you like me to expand on any specific section of the documentation?
