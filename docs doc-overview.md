# Strom Price Prediction and Decision System Documentation

## Overview
The Strom Price Prediction and Decision System is a Python-based application designed to analyze energy prices and provide optimal heating decisions. This documentation provides guidance on how to use, configure, and extend the system.

## Installation
### Prerequisites
- Python 3.10+
- pip install requirements.txt

### Setup
```bash
python -m main
```

## Configuration
### API Key
The API key needs to be configured in `utils/config.py`:
```python
STROM_API_KEY = 'your_api_key_here'
```

### Directories
Define directory paths in `utils/config.py`:
```python
BASEPATH = '/path/to/your/base/directory'
DATA_FOLDER = BASEPATH + '/data/'
WEATHER_FOLDER = BASEPATH + '/weather/'
```

## Usage

### Main Features
1. **Price Prediction**
   ```python
   from strom.utils import get_prices
   prices = get_prices(start_date='2024-01-01', end_date='2024-12-31')
   ```

2. **Temperature Analysis**
   ```python 
   from strom.utils import get_temp_price_df
   df = get_temp_price_df(
       temp_folder='path/to/temp/data/',
       price_folder='path/to/price/data/'
   )
   ```

3. **Decision Making**
   ```python
   from strom.utils import find_heating_decision
   decision = find_heating_decision(
       temp_price_df=df,
       heat_loss=0.1,
       heating_power=2,
       min_temperature=18
   )
   ```

### API Reference
#### endpoints:
- `/get-prices`: Retrieves historical price data
- `/get-temperature-data`: Gets temperature records
- `/make-decision`: Generates optimal heating strategy

## Examples

### Example 1: Basic Usage
```python
import strom.utils as utils

# Get prices for last year
prices = utils.get_prices(start_date='2023-12-01', end_date='2024-01-01')

# View results
print(prices)
```

### Example 2: Custom Configuration
```python
import strom.utils as utils

config = {
    'API_KEY': 'your_api_key_here',
    'BASEPATH': '/path/to/your/directory'
}

utils.setup_config(config)
```

## Development
- Create `setup.py` and install dependencies:
  ```bash
  pip install -r requirements.txt
  ```
- Initialize repository:
  ```bash
  python setup.py develop
  ```

## Troubleshooting
1. Ensure API key is valid and stored securely
2. Check network connectivity for API requests
3. Verify paths in config file match your directory structure

## Legal
Please ensure all usage complies with relevant data protection regulations.
