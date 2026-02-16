import time
import os
from datetime import datetime, timedelta, timezone
import win32com.client
import json
import logging
import traceback
import threading
from pwi4_client import PWI4
from pwi4_tle_observer import run_observer
import pytz
import sys
import requests
from loguru import logger

pwi4 = None
dome_open = False

ddw = win32com.client.Dispatch("TIDigitalDomeWorks.DomeControl")

logging.basicConfig(filename='telescope_automation_log.txt', level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
                    
def startup_pwi4():
    global pwi4
    try:
        if pwi4 is None:
            print("Initializing PWI4...")
            pwi4 = PWI4()
            logging.info("PWI4 instance created.")

        def connect_to_mount():
            print("Connecting to the mount...")
            pwi4.mount_connect()
            while not pwi4.status().mount.is_connected:
                time.sleep(1)
            logging.info("Mount connected.")
            print("Mount connected.")

        def enable_motors():
            print("Enabling motors...")
            pwi4.mount_enable(0)  # Enable axis 0
            pwi4.mount_enable(1)  # Enable axis 1
            logging.info("Motors enabled.")
            print("Motors enabled.")

        def find_home():
            print("Finding home position...")
            pwi4.mount_find_home()
            last_axis0_pos_degs = -99999
            last_axis1_pos_degs = -99999
            while True:
                status = pwi4.status()
                delta_axis0_pos_degs = abs(status.mount.axis0.position_degs - last_axis0_pos_degs)
                delta_axis1_pos_degs = abs(status.mount.axis1.position_degs - last_axis1_pos_degs)
                if delta_axis0_pos_degs < 0.001 and delta_axis1_pos_degs < 0.001:
                    break
                last_axis0_pos_degs = status.mount.axis0.position_degs
                last_axis1_pos_degs = status.mount.axis1.position_degs
                time.sleep(1)
            logging.info("Home position found.")
            print("Home position found.")

        connect_to_mount()
        enable_motors()
        find_home()
        return pwi4

    except Exception as e:
        logging.error(f"Error in startup_pwi4: {e}")
        traceback.print_exc()
        print(f"Error occurred in startup_pwi4: {e}")

#Function to Control Dome via ASCOM
def control_ddw(ddw, action, azimuth=None):
    try:
        # Check if the dome is busy
        while ddw.statIsBusy():
            time.sleep(1)

        # Check if the dome system is online
        if not ddw.statIsOnline():
            raise Exception("DDW is not running.")

        if action == "open_shutter":
            ddw.actOpenShutter()
            time.sleep(5)  # Adjust sleep time as needed
            if not ddw.statIsShutterOpen():  # Check if the shutter is open
                raise Exception("Failed to open dome shutter.")
            print("Dome shutter opened.")

        elif action == "close_shutter":
            ddw.actCloseShutter()
            time.sleep(5)  # Adjust sleep time as needed
            print("Dome shutter closed.")

        elif action == "slave_to_telescope":
            ddw.optSlaveMode = True
            print("Dome slaving to telescope enabled.")

    except Exception as e:
        logging.error(f"Error in control_ddw: {e}")
        traceback.print_exc()
        raise  # Re-raise the exception to be caught by the calling function


# Function to read TLE data from a file

def read_tle_data(filename):
    tle_data = []
    with open(filename, 'r') as file:
        lines = file.readlines()
        print("Reading TLE data from the file...")
        i = 0
        while i < len(lines):
            if lines[i].strip().startswith('BEGINLOCAL'):
                entry = {
                    'start': lines[i].strip(),
                    'end': lines[i + 1].strip(),
                    'name': lines[i + 2].strip(),
                    'tle1': lines[i + 3].strip(),
                    'tle2': lines[i + 4].strip()
                }
                tle_data.append(entry)
                i += 6  # Skip to the next TLE entry
            else:
                i += 1

    if len(tle_data) == 0:
        print("No upcoming observations found in the file.")
        return None
    else:
        return tle_data


def read_next_observation_time():
    logging.info("Reading next observation time from tleplan.txt")
    try:
        with open("tleplan.txt", "r") as file:
            current_time = datetime.now(pytz.timezone('America/Denver'))
            for line in file:
                if line.startswith('BEGINLOCAL'):
                    obs_time_str = ' '.join(line.split()[1:3])
                    next_obs_time = datetime.strptime(obs_time_str, "%Y-%m-%d %H:%M:%S")
                    next_obs_time = pytz.timezone('America/Denver').localize(next_obs_time)
                    if next_obs_time > current_time:
                        logging.info(f"Next observation time: {next_obs_time}")
                        return next_obs_time
    except Exception as e:
        logging.error(f"Error reading next observation time: {e}")
    return None



def is_time_to_observe(next_obs_time):
    # Make current_time timezone-aware
    current_time = datetime.now(pytz.timezone('America/Denver'))

    return current_time >= (next_obs_time - timedelta(minutes=5)) and current_time <= (next_obs_time + timedelta(minutes=10))  # 10-minute buffer for late starts

def check_system_status():
    global pwi4, dome_open, ddw
    pwi4_connected = ddw_operational = False
    successful_connection = False
    check_counter = 0

    while check_counter < 10 and not successful_connection:
        try:
            pwi4_status = pwi4.status()
            pwi4_connected = pwi4_status is not None and pwi4_status.mount.is_connected
        except:
            pwi4_connected = False

        try:
            ddw.actRefreshStatus()
            ddw_operational = ddw.statIsOnline() and not ddw.statIsBusy()
        except:
            ddw_operational = False

        if pwi4_connected and ddw_operational:
            successful_connection = True
            print("Both PWI4 and DDW are operational.")
        else:
            print(f"Attempt {check_counter + 1}: One or both systems are not operational. Checking again...")
            check_counter += 1
            time.sleep(30)  # Waiting 30 seconds before next status check, 10 checks over 5 minutes

    if not successful_connection:
        print("Emergency shutdown due to system status failure.")
        shutdown_sequence()

def shutdown_sequence():
    global pwi4
    global dome_open

    try:
        if pwi4 is not None:
            print("Disabling the mount...")
            pwi4.mount_disable(0)  # Disable axis 0
            pwi4.mount_disable(1)  # Disable axis 1
            print("Mount disabled.")

        if dome_open:
            control_ddw(ddw, "close_shutter")
            dome_open = False
            print("Dome closed.")
    except Exception as e:
        logging.error(f"Error in shutdown_sequence: {e}")
        traceback.print_exc()


def open_dome_operations(ddw, max_retries=5):
    global dome_open
    for attempt in range(max_retries):
        print(f"Attempt {attempt + 1} to open dome.")

        shutter_open = ddw.statIsShutterOpen()
        print(f"Debug: Shutter open status: {shutter_open}")
        dome_open = shutter_open
        print(f"Debug: Dome open status: {dome_open}")

        if not dome_open:
            print("Performing dome operations...")
            control_ddw(ddw, "open_shutter")
            control_ddw(ddw, "slave_to_telescope")
            dome_open = ddw.statIsShutterOpen()
            if dome_open:
                print("Dome successfully opened.")
                return True
            else:
                print("Failed to open dome, retrying...")
        else:
            print("Dome already open, no need to retry.")
            return True

    print("Failed to open dome after maximum retries.")
    return False


def main():
    global pwi4
    global dome_open
    logging.info("Starting main function of the Telescope Automation Script - The Guardian of the Skies.")
    print("Starting main function of the telescope automation script.")

    try:
        logging.info("Stellar Activation: Starting up PWI4...")
        print("Starting up PWI4...")
        pwi4 = startup_pwi4()

        # Trying to open the dome
        if not open_dome_operations(ddw):
            logging.error("Dome Operation Failure: Failed to open the dome, initiating shutdown sequence.")
            print("Initiating shutdown sequence due to failed dome opening.")
            shutdown_sequence()
            sys.exit(1)  # Exit with non-zero code to indicate failure

        logging.info("System Status: Performing a pre-observational system check...")
        print("Checking system status before starting observations...")
        check_system_status()

        logging.info("Observation Plan: Reading the next observation schedule...")
        print("Reading the next observation time...")
        next_obs_time = read_next_observation_time()
        if not next_obs_time:
            logging.warning("Observation Schedule Alert: No upcoming observations. Initiating shutdown sequence.")
            print("No upcoming observations. Initiating shutdown sequence.")
            shutdown_sequence()
            return

        logging.info("Data Acquisition: Retrieving TLE data for satellite tracking...")
        print("Retrieve TLE data for the observer script")
        tle_data = read_tle_data("tleplan.txt")
        if tle_data is None:
            logging.error("TLE Data Error: Failed to retrieve TLE data. Aborting script.")
            print("Failed to retrieve TLE data. Aborting script.")
            shutdown_sequence()
            return

        logging.info("Orbital Watch: Running the satellite observer script...")
        print("Running the observer script...")
        observation_result = run_observer(tle_data)
        logging.info(f"Observation Outcome: {observation_result}")
        print(f"Observation result: {observation_result}")

        observation_end_time = datetime.now(pytz.timezone('America/Denver'))

        # Initiating shutdown sequence after observer script completion
        logging.info("Observation Complete: Initiating shutdown sequence.")
        print("Observation complete, initiating shutdown sequence.")
        shutdown_sequence()

        # Emergency shutdown check
        if (datetime.now(pytz.timezone('America/Denver')) - observation_end_time).total_seconds() > 7200:
            logging.warning("System Check Reminder: More than 2 hours since last observation, conducting a system status review...")
            print("More than 2 hours since last observation, checking system status...")
            check_system_status()

    except Exception as e:
        logging.error(f"System Error Detected: {e}.")
        print(f"An error occurred: {e}.")
        logging.info("System Status: Assessing system status post-exception...")
        print("Checking system status after an exception occurred...")
        check_system_status()
        logging.info("Shutdown Initiation: Starting shutdown sequence due to an exception.")
        print("Initiating shutdown sequence.")
        shutdown_sequence()
        sys.exit(1)
    finally:
        logging.info("Script Completion: Telescope Automation Script has concluded its operation.")
        print("Main function has completed.")

if __name__ == "__main__":
    logging.Formatter.converter = lambda *args: datetime.now(tz=pytz.timezone('America/Denver')).timetuple()
    logging.info("Debug: Initiating script in __main__")
    print("Debug: Starting script in __main__")

    if "shutdown" in sys.argv:
        logging.info("Debug: Shutdown command detected, executing shutdown sequence.")
        print("Debug: Shutdown command detected")
        shutdown_sequence()
    else:
        logging.info("Telescope Automation: Script activation in progress.")
        print("Telescope automation script initiated.")
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
        main()
