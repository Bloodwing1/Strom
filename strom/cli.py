import asyncio
from kasa import Discover
from dotenv import load_dotenv
import os
import json
import pandas as pd
from strom.control import (
    SystemClock,
    execute_plan,
    plan_from_schedule,
)
from strom.data_utils import get_temp_price_df
from strom.optimization_utils import find_heating_output, House


def setup_env_config():

    # Load the environment variables from the .env file
    load_dotenv(dotenv_path="./config/tapologin.env")

    email = os.getenv("EMAIL")  # Get email from the environment variable
    password = os.getenv("PASSWORD")  # Get password from the environment variable
    device_ip = os.getenv("DEVICEIP")

    # Load house config parameters
    try:
        with open('./config/house_config.json', 'r') as f:
            house_params = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # If the folder exists but the file does not, print a warning and create an empty JSON file
        config_folder = './config'
        if os.path.isdir(config_folder):
            print("Warning: house_config.json not found. Creating an empty JSON file.")
            with open('./config/house_config.json', 'w') as f:
                json.dump({}, f)
            house_params = {}
        else:
            raise ValueError("House config folder not found.")
        raise ValueError("House config file not found or invalid JSON.")

    house = House(**house_params)

    return email, password, device_ip, house

async def main(email, password, device_ip, house, clock=None):
    from strom.control import MaxOnWatchdog

    clock = clock or SystemClock()

    try:
        # Discover the devices
        if not device_ip:
            raise ValueError("DEVICEIP environment variable is not set or is invalid.")
        dev = await Discover.discover_single(device_ip, username=email, password=password)
        temp_price_df = get_temp_price_df()
        # Resolve the control policy: bounded duty-cycle actuation (issue 31).
        schedule = find_heating_output(temp_price_df, house, 'optimal')
        interval_seconds = pd.to_timedelta(house.freq).total_seconds()
        plan = plan_from_schedule(schedule, interval_seconds=interval_seconds)
        # Check if the device was discovered successfully
        if dev is None:
            raise ValueError("Device could not be discovered. Please check the DEVICEIP, email, and password.")
        # Independent max-on safety net (issue 31).
        watchdog = MaxOnWatchdog(dev)
        watchdog.start()
        try:
            if plan.total_on_seconds > 0:
                watchdog.notify_on()
            await execute_plan(dev, plan, clock)
        finally:
            watchdog.notify_off()
            await watchdog.stop()

        # Update the device state after action
        await dev.update()
        print(f"Device state: {'ON' if dev.is_on else 'OFF'}")

        # Close the device connection manually
        await dev.async_close()
        print("Device connection closed.")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
