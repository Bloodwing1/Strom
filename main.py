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
    """Main function to control smart device with enhanced error handling"""
    try:
        logger.info("Starting main function")
        
        # Load environment variables first
        env_content = await load_env_vars()
        temp_price_df = utils.get_temp_price_df()
        # Get user input with error handling
        try:
            user_input = bool(
                utils.find_heating_decision(
                    temp_price_df,
                    decision='discrete',
                    heat_loss=0.1,
                    heating_power=2,
                    min_temperature=18
                )[0]
            )
        except Exception as e:
            logger.error(f"Error in finding heating decision: {e}")
            raise
        # Execute device actions with error handling
        try:
            if user_input:
                logger.info("User selected to turn device ON")
                await dev.turn_on()
                print("Device turned on.")
            else:
                logger.info("User selected to keep device OFF")
                await dev.turn_off()
                print("Device turned off.")
        except Exception as e:
            logger.error(f"Failed to execute device action: {e}")
            raise
       # else:
        #    print("Invalid input. Please enter 0 or 1.")

        # Update device state with error handling
        try:
            logger.info("Updating device state")
            await dev.update()
            print(f"Device state: {'ON' if dev.is_on else 'OFF'}")
        except Exception as e:
            logger.error(f"Failed to update device state: {e}")
            raise

        # Close device connection with error handling
        try:
            logger.info("Closing device connection")
            await dev.async_close()
            print("Device connection closed successfully.")
        except Exception as e:
            logger.error(f"Failed to close device connection: {e}")
            raise

    except Exception as e:
        logger.error(f"Main function error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
