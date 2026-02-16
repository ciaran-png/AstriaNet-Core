import subprocess
import time
from datetime import datetime, timedelta, timezone
import pytz
import os
import logging
import sys
import traceback

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s: %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout)])

def is_tleplan_current():
    """Checks if the tleplan.txt file is current (today's date)."""
    try:
        with open('tleplan.txt', 'r') as f:
            lines = f.readlines()
        # Extract the date part from the first observation time
        for line in lines:
            if line.startswith("BEGINLOCAL"):
                date_str = line.split()[1]
                first_observation_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return first_observation_date == datetime.now().date()
        return False
    except FileNotFoundError:
        logging.warning("tleplan.txt not found. It will be created.")
        return False
    except Exception as e:
        logging.error(f"Error reading tleplan.txt: {e}")
        return False

def update_tleplan():
    """Runs api_interaction.py to update the tleplan.txt file."""
    try:
        logging.info("Running the TLE updater script.")
        subprocess.run(['python', 'api_interaction.py', '--non-interactive', '--days', '1', '--observation-window', '2'], check=True)
        logging.info("TLE Updater script finished successfully.")
    except subprocess.CalledProcessError as e:
        logging.error(f"TLE Updater script encountered an error: {e}")
        return False
    return True

def update_sun_times():
    """Fetches today's sunset time."""
    try:
        import requests

        lat, lng = 32.957313, -105.742485  # Coordinates for Cloudcroft, New Mexico
        today = datetime.now(pytz.timezone('America/Denver')).date()

        sunset_response = requests.get(
            f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lng}&date={today}&formatted=0"
        )

        if sunset_response.status_code == 200:
            sunset_data = sunset_response.json()
            if 'results' in sunset_data and 'sunset' in sunset_data['results']:
                sunset_time_str = sunset_data['results']['sunset']
                sunset_utc = datetime.fromisoformat(sunset_time_str)
                mountain_time = pytz.timezone('America/Denver')
                sunset_local = sunset_utc.replace(tzinfo=timezone.utc).astimezone(mountain_time)
                logging.info(f"Sunset today: {sunset_local}")
                return sunset_local
            else:
                logging.error("Malformed API response: Missing 'results' or 'sunset' data.")
                return None
        else:
            logging.error(
                f"Failed to retrieve data from API. Status code: {sunset_response.status_code}"
            )
            return None
    except Exception as e:
        logging.error(f"Error in update_sun_times: {e}")
        return None

def run_automated2():
    """Runs automated2.py script and returns True if successful, False otherwise."""
    try:
        logging.info("Starting automated2.py script.")
        subprocess.run(['python', 'automated2.py'], check=True)
        logging.info("automated2.py script finished successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"automated2.py script encountered an error: {e}")
        return False

def shutdown_sequence():
    """Performs shutdown activities such as stopping the mount."""
    try:
        logging.info("Initiating shutdown sequence.")
        subprocess.run(['python', 'automated2.py', 'shutdown'], check=True)
        logging.info("Shutdown sequence completed.")
    except subprocess.CalledProcessError as e:
        logging.error(f"Shutdown sequence encountered an error: {e}")

def wait_until(target_time):
    """Waits until the specified target datetime."""
    now = datetime.now(pytz.timezone('America/Denver'))
    remaining = (target_time - now).total_seconds()
    if remaining > 0:
        logging.info(f"Waiting for {remaining / 60:.2f} minutes until {target_time}")
        time.sleep(remaining)
    else:
        logging.info(f"Target time {target_time} is in the past.")

def main():
    logging.info("Starting infinite observation cycle.")
    failure_count = 0  # Counter for dome operation failures

    while True:
        try:
            # Check if tleplan.txt is current, if not, update it
            if not is_tleplan_current():
                success = update_tleplan()
                if not success:
                    # If updating tleplan failed, wait and retry the next cycle
                    logging.error("Failed to update tleplan.txt. Waiting until next cycle.")
                    time.sleep(3600 * 12)  # Wait 12 hours before next attempt
                    continue
            else:
                logging.info("tleplan.txt is current. Skipping TLE updater.")

            # Fetch sunset time for today
            sunset_time = update_sun_times()
            if sunset_time is None:
                # If unable to get sunset time, wait and retry the next cycle
                logging.error("Failed to retrieve sunset time. Waiting until next cycle.")
                time.sleep(3600 * 12)  # Wait 12 hours before next attempt
                continue

            # Wait until 10 minutes after sunset
            run_time = sunset_time + timedelta(minutes=10)
            wait_until(run_time)

            # Run automated2.py
            success = run_automated2()
            if not success:
                failure_count += 1
                logging.error(f"automated2.py failed. Dome operation failure count: {failure_count}")
                if failure_count > 3:
                    logging.error("Dome operations failed more than 3 times. Initiating shutdown and waiting until next day.")
                    shutdown_sequence()

                    # Calculate time until next day's 12 noon
                    now = datetime.now(pytz.timezone('America/Denver'))
                    next_noon = now.replace(hour=12, minute=0, second=0, microsecond=0) + timedelta(days=1)
                    wait_until(next_noon)
                    failure_count = 0  # Reset failure count after waiting
                else:
                    # Wait some time before retrying
                    logging.info("Waiting 1 hour before retrying automated2.py.")
                    time.sleep(3600)  # Wait 1 hour
                continue  # Go to next iteration of the loop

            # Reset failure count on success
            failure_count = 0

            # Adjusted logic to wait until 12 noon the same day
            now = datetime.now(pytz.timezone('America/Denver'))
            next_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
            if now >= next_noon:
                # If it's already past 12 noon, wait until 12 noon the next day
                next_noon += timedelta(days=1)

            logging.info(f"Waiting until next observation cycle at {next_noon}")
            wait_until(next_noon)

        except Exception as e:
            logging.error(f"An error occurred: {e}")
            logging.error(traceback.format_exc())
            # Wait some time before retrying
            logging.info("Waiting 1 hour before retrying due to an exception.")
            time.sleep(3600)  # Wait 1 hour

if __name__ == "__main__":
    main()