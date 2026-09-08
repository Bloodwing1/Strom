"""Fake child: reports selected environment entries as JSON, exits 0."""

import json
import os
import sys

print(
    json.dumps(
        {
            "STROM_CONFIG_DIR": os.environ.get("STROM_CONFIG_DIR"),
            "WEATHER_API_KEY": os.environ.get("WEATHER_API_KEY"),
            "PRICE_API_KEY": os.environ.get("PRICE_API_KEY"),
        }
    ),
    flush=True,
)
sys.exit(0)
