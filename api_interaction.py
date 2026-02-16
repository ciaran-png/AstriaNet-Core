import requests
import sys
from datetime import datetime, timedelta, timezone
import logging
import tkinter as tk
from tkinter import simpledialog, messagebox
from concurrent import futures
import time
import json
import os
import argparse
import aiohttp
import asyncio

# Configure logging
from loguru import logger 

# Configure Loguru
logger.remove()
logger.add(sys.stderr, format="<green>{time:YYYY-MM-DD at hh:mm:ss A}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>", level="TRACE")

# Set up command line arguments
parser = argparse.ArgumentParser(description='Run TLE Updater Script.')
parser.add_argument('--days', type=int, default=None, help='Number of days ahead for observation (max 10)')
parser.add_argument('--observation-window', type=int, default=2, help='Observation window in minutes (default: 2)')
parser.add_argument('--non-interactive', action='store_true', help='Run script in non-interactive mode')
args = parser.parse_args()

with open('NoradId.txt', 'r') as file:
    norad_ids_content = file.read()
    norad_ids = norad_ids_content.strip().split(',')

API_KEY = "HW52FN-38SNHM-5WKRHM-566K"  # Replace with your N2YO API key
BASE_URL = "https://api.n2yo.com/rest/v1/satellite"

class JSONDateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

class SimpleCache:
    def __init__(self, filename: str = 'cache.json', expiration_time: int = 3600):
        self.filename = filename
        self.expiration_time = expiration_time
        self.cache = self.load_cache()

    def load_cache(self) -> dict:
        """Load the cache from a file."""
        if os.path.exists(self.filename):
            with open(self.filename, 'r') as file:
                return json.load(file, object_hook=self.json_datetime_hook)
        return {}

    def save_cache(self):
        """Save the cache to a file."""
        with open(self.filename, 'w') as file:
            json.dump(self.cache, file, cls=JSONDateTimeEncoder)

    def set(self, key: str, value: dict):
        """Store an item in the cache."""
        self.cache[key] = {'data': value, 'time': time.time()}
        self.save_cache()

    def get(self, key: str) -> dict:
        """Retrieve an item from the cache if it hasn't expired."""
        if key in self.cache:
            if time.time() - self.cache[key]['time'] < self.expiration_time:
                return self.cache[key]['data']
        return None

    @staticmethod
    def json_datetime_hook(json_dict):
        """Converts string in ISO format back into datetime object."""
        for (key, value) in json_dict.items():
            try:
                json_dict[key] = datetime.fromisoformat(value)
            except (TypeError, ValueError):
                pass
        return json_dict

# Initialize the cache
cache = SimpleCache()

def batch_process_norad_ids(norad_ids: list, batch_size: int) -> list:
    """
    Divide a large list of NORAD IDs into smaller batches.

    Args:
    norad_ids (list): A list of NORAD IDs.
    batch_size (int): The number of NORAD IDs per batch.

    Returns:
    list of lists: A list where each element is a batch (list) of NORAD IDs.
    """
    # Initialize an empty list to hold the batches
    batches = []

    # Loop over the NORAD IDs and create batches
    for i in range(0, len(norad_ids), batch_size):
        # Create a batch from the current position to the batch size
        batch = norad_ids[i:i + batch_size]

        # Append the batch to the batches list
        batches.append(batch)

    return batches

def ask_for_norad_ids_and_days():
    root = tk.Tk()
    root.title("Satellite Observation Configuration")
    root.focus_force()  # Force the window to take focus

    # Check if the user wants to run the script
    run_script = messagebox.askyesno("Run Script", "Do you want to run the script?", parent=root)
    if not run_script:
        print("Script execution cancelled by the user.")
        root.destroy()
        return None, None, None  # Return None values to indicate script cancellation

    class CustomDialog(simpledialog.Dialog):
        def body(self, master):
            tk.Label(master, text="NORAD IDs (comma-separated):").grid(row=0, columnspan=2)
            self.norad_ids_text = tk.Text(master, height=5, width=40)
            self.norad_ids_text.grid(row=1, columnspan=2)

            tk.Label(master, text="Days ahead for observation (max 10):").grid(row=2, column=0)
            self.days_entry = tk.Entry(master)
            self.days_entry.grid(row=2, column=1)

            tk.Label(master, text="Observation window in minutes:").grid(row=3, column=0)
            self.observation_window_entry = tk.Entry(master)
            self.observation_window_entry.grid(row=3, column=1)

            return self.norad_ids_text  # Initial focus

        def apply(self):
            norad_ids_str = self.norad_ids_text.get("1.0", tk.END)
            days_str = self.days_entry.get()
            observation_window_str = self.observation_window_entry.get()

            self.result = (norad_ids_str, days_str, observation_window_str)

    root = tk.Tk()
    root.withdraw()  # Hide the main window

    dialog = CustomDialog(root)
    if dialog.result:
        norad_ids_str, days_str, observation_window_str = dialog.result

        norad_ids = [id.strip() for id in norad_ids_str.split(',')] if norad_ids_str.strip() else []
        days = min(max(int(days_str), 1), 10) if days_str.isdigit() else 1
        observation_window = int(observation_window_str) if observation_window_str.isdigit() else 2
        if observation_window_str.lower() == 'full':
            observation_window = 'full'

        return norad_ids, days, observation_window
    else:
        return None, None, None

def read_current_norad_id(default_id: str) -> str:
    try:
        with open("current_norad_id.txt", "r") as file:
            return file.read().strip()
    except FileNotFoundError:
        return default_id

def write_current_norad_id(norad_id: str):
    with open("current_norad_id.txt", "w") as file:
        file.write(norad_id)


def get_tle(sat_id: str, session) -> dict:
    cached_data = cache.get(sat_id)
    if cached_data:
        logging.info(f"Using cached data for NORAD ID {sat_id}")
        return cached_data

    logging.info(f"Fetching TLE data for NORAD ID {sat_id}...")
    url = f"{BASE_URL}/tle/{sat_id}?apiKey={API_KEY}"
    response = session.get(url)
    if response.status_code == 200:
        data = response.json()
        if 'tle' in data:
            logging.info(f"Raw TLE Data for {sat_id}: {data['tle']}")
            cache.set(sat_id, data)
            return data
        else:
            logging.error(f"TLE data not found for NORAD ID {sat_id}.")
            return None
    else:
        logging.error(f"Failed to retrieve TLE for NORAD ID {sat_id}: {response.status_code}")
        return None

def get_tle_concurrently(sat_ids: list, session) -> dict:
    results = {}
    for sat_id in sat_ids:
        result = get_tle(sat_id, session)
        results[sat_id] = result
    return results

def get_visual_passes(sat_id: str, days: int, min_visibility: int, session) -> list:
    # Coordinates for Cloudcroft, New Mexico
    observer_lat = 32.903
    observer_lng = -105.5295
    observer_alt = 2225

    url = f"{BASE_URL}/visualpasses/{sat_id}/{observer_lat}/{observer_lng}/{observer_alt}/{days}/{min_visibility}/?apiKey={API_KEY}"
    response = session.get(url)
    if response.status_code == 200:
        data = response.json()
        # Check if 'passes' key is in the response
        if 'passes' in data:
            return data['passes']
        else:
            print(f"No visible passes found for satellite {sat_id}.")
            return []
    else:
        print(f"Failed to retrieve visual passes for satellite {sat_id}: {response.status_code}")
        return []

def update_tle_file(tle_data: dict, observation_times: list):
    with open("tleplan.txt", "w") as file:
        for start_time, end_time in observation_times:
            file.write(f"BEGINLOCAL {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            file.write(f"ENDLOCAL {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            file.write(f"NAME {tle_data['info']['satname']}\n")
            file.write(f"0 {tle_data['info']['satname']}\n")

            # Correctly split the TLE data
            tle_lines = tle_data["tle"].split('\n')
            if len(tle_lines) >= 2:
                file.write(f"{tle_lines[0].strip()}\n")
                file.write(f"{tle_lines[1].strip()}\n")
            else:
                print("Unexpected TLE format received")
            file.write("\n")


def convert_visual_passes_to_times(visual_passes: list, observation_window: int = 2) -> list:
    observation_times = []
    for pass_data in visual_passes:
        start_time = datetime.utcfromtimestamp(pass_data['startUTC'])
        end_time = datetime.utcfromtimestamp(pass_data['endUTC'])

        if observation_window == 'full':
            window_start = start_time
            window_end = end_time
        else:
            # Ensure observation_window is positive
            observation_window = max(0, observation_window)
            midpoint = start_time + (end_time - start_time) / 2
            window_start = max(midpoint - timedelta(minutes=observation_window), start_time)
            window_end = min(midpoint + timedelta(minutes=observation_window), end_time)

        observation_times.append((window_start, window_end))

    return observation_times


def utc_to_mst(utc_dt: datetime) -> datetime:
    # MST is UTC-7 hours
    return utc_dt.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-7)))


def filter_observation_times(observation_times: list, min_gap: int) -> list:
    if not observation_times:
        return []

    # Sort the observation times by the start time in the observation dictionary
    sorted_times = sorted(observation_times, key=lambda x: x[2]['start'])

    # Initialize filtered list with the first observation
    filtered_times = [sorted_times[0]]

    for item in sorted_times[1:]:
        # Correctly unpacking the tuple
        _, _, observation = item
        current_start = observation['start']
        last_end = filtered_times[-1][2]['end']

        # Check if the start of the current observation is at least min_gap minutes after the last observation ends
        if current_start >= last_end + timedelta(minutes=min_gap):
            filtered_times.append(item)

    return filtered_times


def main():
    logger.info("Starting main process")
    # Check if non_interactive mode
    if args.non_interactive:
        logger.debug("Running in non-interactive mode")
        # Non-interactive mode
        days_ahead = args.days or 1  # Default to 5 days if not specified
        observation_window = args.observation_window   # Default observation window in non-interactive mode
        with open('NoradId.txt', 'r') as file:
            norad_ids = file.read().strip().split(',')
        logger.debug(f"Loaded NORAD IDs: {norad_ids[:3]}... (truncated for brevity)")
    else:
        logger.debug("Running in interactive mode")
        # Interactive mode
        norad_ids, days_ahead, observation_window = ask_for_norad_ids_and_days()
        if norad_ids is None:
            logger.warning("Operation cancelled by the user.")
            print("Operation cancelled.")
            return  # Exit the main function
        logger.debug(f"User provided NORAD IDs: {norad_ids[:3]}... (truncated for brevity)")

    # Rest of the code remains the same
    all_observation_times = []
    batch_size = 10  # Adjust batch size as needed
    norad_id_batches = batch_process_norad_ids(norad_ids, batch_size)
    logger.debug(f"Processing NORAD IDs in batches of {batch_size}")

    session = requests.Session()  # Using requests instead of aiohttp
    for batch in norad_id_batches:
        logger.debug(f"Processing batch: {batch}")
        # Fetch TLE data for the batch concurrently
        tle_data_results = get_tle_concurrently(batch, session)  # Adjusted to synchronous call
        logger.debug(f"Received TLE data for batch: {list(tle_data_results.keys())}")

        # Process results
        for sat_id, tle_data in tle_data_results.items():
            if tle_data:
                logger.debug(f"Fetching visual passes for NORAD ID {sat_id}")
                visual_passes = get_visual_passes(sat_id, days_ahead, 300, session)  # Adjusted to synchronous call
                logger.debug(f"Visual passes for {sat_id}: {visual_passes[:3]}... (truncated for brevity)")
                observation_times = convert_visual_passes_to_times(visual_passes, observation_window)
                logger.debug(f"Converted observation times for {sat_id}: {observation_times[:3]}... (truncated for brevity)")
                all_observation_times.extend([(sat_id, tle_data, {'start': start_time, 'end': end_time}) for start_time, end_time in observation_times])
            else:
                logger.error(f"Failed to fetch TLE data for NORAD ID {sat_id}")
                print(f"Failed to fetch TLE data for NORAD ID {sat_id}")

    # Just before the call to filter_observation_times
    logger.debug("Debug: Sample of all_observation_times", all_observation_times[:3])  # Print first 3 elements
    filtered_observation_times = filter_observation_times(all_observation_times, 1)
    logger.debug(f"Filtered observation times: {filtered_observation_times[:3]}... (truncated for brevity)")

    # Write sorted and filtered observations to tleplan.txt
    with open("tleplan.txt", "w") as file:
        for sat_id, tle_data, observation in filtered_observation_times:
            start_mst = utc_to_mst(observation['start'])
            end_mst = utc_to_mst(observation['end'])
            file.write(f"BEGINLOCAL {start_mst.strftime('%Y-%m-%d %H:%M:%S')}\n")
            file.write(f"ENDLOCAL {end_mst.strftime('%Y-%m-%d %H:%M:%S')}\n")
            file.write(f"NAME {tle_data['info']['satname']}\n")
            file.write(f"0 {tle_data['info']['satname']}\n")
            tle_lines = tle_data["tle"].split('\r\n')
            if len(tle_lines) >= 2:
                file.write(f"{tle_lines[0].strip()}\n")
                file.write(f"{tle_lines[1].strip()}\n")
            file.write("\n")
            logger.debug(f"Wrote observation for {sat_id} to file")
    logger.info("Main process completed successfully")

if __name__ == "__main__":
    main()
