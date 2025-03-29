import asyncio
from kasa import Discover
from dotenv import load_dotenv
import os
from strom import optimization_utils
from strom.data_utils import get_temp_price_df

# Load the environment variables from the .env file
load_dotenv(dotenv_path="../../config/tapologin.env")

email = os.getenv("EMAIL")  # Get email from the environment variable
password = os.getenv("PASSWORD")  # Get password from the environment variable
device_ip = os.getenv("DEVICEIP")
if not device_ip:
    os.chdir(optimization_utils.find_root_dir())
    with open('./config/device_IP.txt') as f:
        device_ip = f.read().strip()

async def main():
    try:
        # Discover the device
        dev = await Discover.discover_single(device_ip, username=email, password=password)
        temp_price_df = get_temp_price_df()
        # Prompt the user for input (0 for off, 1 for on)
        user_input = bool(optimization_utils.find_heating_output(temp_price_df, output = 'discrete')[0][0])
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
