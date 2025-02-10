# Core imports
import asyncio
from kasa import Discover
from dotenv import load_dotenv
import os
from strom import utils

# Load the environment variables from the .env file
load_dotenv(dotenv_path="../../config/tapologin.env")

device_ip = "192.168.1.16"
email = os.getenv("EMAIL")  # Get email from the environment variable
password = os.getenv("PASSWORD")  # Get password from the environment variable

async def main():
    try:
        # Discover the device
        dev = await Discover.discover_single(device_ip, username=email, password=password)
        temp_price_df = utils.get_temp_price_df()
        # Prompt the user for input (0 for off, 1 for on)
        user_input = bool(utils.find_heating_decision(temp_price_df, decision = 'discrete')[0][0])
        # Check user input and turn the light on or off accordingly
        print(user_input)
        if user_input:
            await dev.turn_on()
            print("Device turned on.")
        else:
            await dev.turn_off()
            print("Device turned off.")
       # else:
        #    print("Invalid input. Please enter 0 or 1.")

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
