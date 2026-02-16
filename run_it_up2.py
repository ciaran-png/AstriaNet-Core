# -*- coding: utf-8 -*-
import requests
import tkinter as tk
from tkinter import messagebox, font, simpledialog, PhotoImage
from PIL import Image, ImageDraw, ImageFont
import subprocess
from datetime import datetime, timezone, timedelta
import threading
import json
import pytz
import os
import re
import sys
import traceback
import urllib.request
import time

# New imports for logging and progress bars 
from loguru import logger 
from alive_progress import alive_bar
from io import StringIO
print(sys.executable)

from colorama import init, Fore, Back, Style
init(autoreset=True)

# Modify loguru setup
# Modify loguru setup to include file logging
logger.remove()  # Remove default handler
log_file = "guioperations.log"  # Define log file name
logger.add(sys.stderr, format=f"{Fore.GREEN}<green>{{time:YYYY-MM-DD at hh:mm:ss A}}</green> | <level>{{level: <8}}</level> | <cyan>{{name}}</cyan>:<cyan>{{function}}</cyan>:<cyan>{{line}}</cyan> - <level>{{message}}</level>", level="TRACE")
logger.add(log_file, format="{time:YYYY-MM-DD at hh:mm:ss A} | {level: <8} | {name}:{function}:{line} - {message}", level="TRACE") # Add file handler, rotate daily

def show_button_info(info_text):
    info_popup = tk.Toplevel(app)
    info_popup.title("Information")
    info_popup.geometry("300x200")  # Adjust size as needed

    info_label = tk.Label(info_popup, text=info_text, wraplength=280)
    info_label.pack(pady=10, padx=10)

    close_button = tk.Button(info_popup, text="Close", command=info_popup.destroy)
    close_button.pack(pady=10)

def download_and_convert_image(url, jpg_filename, png_filename, size=(500, 500), observatory_coords=(305, 263), label_text="New Mexico Skies"):
    try:
        # Download the image
        print("Downloading image...")
        urllib.request.urlretrieve(url, jpg_filename)
        print("Image downloaded at:", os.path.abspath(jpg_filename))

        # Open the downloaded image
        with Image.open(jpg_filename) as img:
            # Resize the image
            img = img.resize(size, Image.Resampling.LANCZOS)  # Updated line
            
            # Draw a circle and label on the image
            draw = ImageDraw.Draw(img)
            draw.ellipse((observatory_coords[0]-4, observatory_coords[1]-4, observatory_coords[0]+4, observatory_coords[1]+4), fill='red')
            
            # Load a font
            font_path = "arial.ttf"  # Ensure this path is correct or accessible on your system
            try:
                font = ImageFont.truetype(font_path, 14)
            except IOError:
                print(f"Warning: Unable to load font '{font_path}'. Using default font.")
                font = ImageFont.load_default()
            
            # Draw text
            draw.text((314, 263), label_text, fill="white", font=font)
            
            # Save the modified image as PNG
            img.save(png_filename)
        
        print("Image processed. Final image at:", os.path.abspath(png_filename))
        return True
    except Exception as e:
        print(f"Error processing the image: {e}")
        return False


def update_image_label():
    jpg_filename = "weather.jpg"
    png_filename = "weather.png"
    image_url = "https://cdn.star.nesdis.noaa.gov/GOES16/ABI/SECTOR/sr/GEOCOLOR/600x600.jpg"

    if download_and_convert_image(image_url, jpg_filename, png_filename):
        if os.path.exists(png_filename):
            print("PNG file exists, updating label.")
            photo = tk.PhotoImage(file=png_filename)
            image_label.config(image=photo)
            image_label.image = photo  # keep a reference
        else:
            print("PNG file does not exist.")

    # Schedule the next update
    image_label.after(300000, update_image_label)  # Update every 5 minutes


def log_user_access(user_name):
    with open("access_log.txt", "a") as log_file:
        log_file.write(f"{user_name} accessed the application at {datetime.now()}\n")

def check_observatory_status():
    try:
        url = "https://nmskies.com/weather.php"
        response = requests.get(url)
        html_content = response.text

        # Use regular expression to find the image URL
        match = re.search(r'images/(daylight\.jpg|open\.jpg|closed\.jpg)\?', html_content)
        if match:
            img_file = match.group(1)
            if "daylight.jpg" in img_file:
                status = "Daylight (Closed)"
            elif "open.jpg" in img_file:
                status = "Open"
            elif "closed.jpg" in img_file:
                status = "Closed"
            else:
                status = "Unknown"
        else:
            status = "Status image not found"

        return status  # Returning the status string instead of displaying it
    except Exception as e:
        print(f"Failed to check observatory status: {e}")
        return "Error"  # Return an error status in case of an exception

def update_sun_times():
    try:
        lat, lng = 32.957313, -105.742485  # Coordinates for Cloudcroft, New Mexico
        today = datetime.now(pytz.timezone('America/Denver')).date()
        tomorrow = today + timedelta(days=1)

        sunset_response = requests.get(f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lng}&date={today}&formatted=0")
        sunrise_response = requests.get(f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lng}&date={tomorrow}&formatted=0")

        if sunset_response.status_code == 200 and sunrise_response.status_code == 200:
            sunset_data = sunset_response.json()
            sunrise_data = sunrise_response.json()
            if 'results' in sunset_data and 'sunset' in sunset_data['results'] and 'results' in sunrise_data and 'sunrise' in sunrise_data['results']:
                sunset_utc = datetime.fromisoformat(sunset_data['results']['sunset'])
                sunrise_utc = datetime.fromisoformat(sunrise_data['results']['sunrise'])

                mountain_time = pytz.timezone('America/Denver')
                sunset_local = sunset_utc.replace(tzinfo=timezone.utc).astimezone(mountain_time)
                sunrise_local = sunrise_utc.replace(tzinfo=timezone.utc).astimezone(mountain_time)

                logger.info(f"Sunset today: {sunset_local}, Sunrise tomorrow: {sunrise_local}")
                return sunset_local, sunrise_local
            else:
                logger.error("Malformed API response: Missing 'results' or 'sunset/sunrise' data.")
                return None, None
        else:
            logger.error(f"Failed to retrieve data from API. Status codes: {sunset_response.status_code}, {sunrise_response.status_code}")
            return None, None
    except Exception as e:
        logger.error(f"Error in update_sun_times: {e}")
        return None, None

# Function to determine the part of the day
def get_part_of_day(hour):
    return (
        "Good morning" if 5 <= hour <= 11
        else "Good afternoon" if 12 <= hour <= 17
        else "Good evening"
    )

# Flag to control the infinite loop
running_infinitely = False

def infinite_observation_cycle():
    global running_infinitely
    running_infinitely = True
    infinite_cycle_status_label.config(text="Status: Running")
    logger.info("Entering infinite observation cycle.")
    while running_infinitely:
        try:
            automated_observation_cycle()

            # Wait until next day's noon
            now = datetime.now(pytz.timezone('America/Denver'))
            next_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
            if now >= next_noon:
                # If it's already past today's noon, schedule for tomorrow
                next_noon += timedelta(days=1)
            wait_time_seconds = (next_noon - now).total_seconds()

            if wait_time_seconds > 0:
                logger.info(f"Waiting until next noon ({next_noon}) to start the next cycle.")
                time.sleep(wait_time_seconds)
            else:
                logger.warning("No wait time calculated. Starting next cycle immediately.")

        except Exception as e:
            logger.error(f"An error occurred in the infinite loop: {e}")
            logger.error(traceback.format_exc())
            # Optionally, decide whether to continue or break
            # break

    infinite_cycle_status_label.config(text="Status: Stopped")
    logger.info("Exiting infinite observation cycle.")

def stop_infinite_cycle():
    global running_infinitely
    running_infinitely = False
    logger.info("Stopping infinite observation cycle.")
    infinite_cycle_status_label.config(text="Status: Stopping")



def run_script(script_name, status_label, shutdown=False, args=None, completion_flag=None):
    def target():
        try:
            status_label.config(text="Status: Running")
            script_args = ['python', script_name] + (args if args is not None else [])
            if shutdown:
                script_args.append('shutdown')

            with alive_bar(1, title=f"Running {script_name}") as bar:
                result = subprocess.run(
                    script_args,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                bar()

            output = result.stdout
            error_output = result.stderr
            logger.info(f"Script {script_name} output:\n{output}")
            if error_output:
                logger.error(f"Script {script_name} error output:\n{error_output}")

            status_label.config(text="Status: Finished")
            if completion_flag is not None:
                completion_flag.set()
        except subprocess.CalledProcessError as e:
            error_message = f"Error running script {script_name}: {e}\nstdout:\n{e.stdout}\nstderr:\n{e.stderr}"
            print(error_message)
            status_label.config(text="Status: Error")
            logger.error(error_message)
    threading.Thread(target=target).start()

def run_apiinteraction():
    run_script('api_interaction.py', tle_updater_status_label)

def open_tleplan():
    try:
        os.startfile('tleplan.txt')
    except Exception as e:
        messagebox.showerror("Error", f"Failed to open tleplan.txt: {e}")

def run_automated2():
    run_script('automated2.py', automated2_status_label)

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
        logger.warning("tleplan.txt not found. It will be created.")
        return False
    except Exception as e:
        logger.error(f"Error reading tleplan.txt: {e}")
        return False

def automated_observation_cycle():
    logger.info("Starting automated observation cycle.")
    if not is_tleplan_current():
        # Run the TLE Updater script if tleplan.txt is outdated
        try:
            logger.info("Running the TLE updater script.")
            subprocess.run(['python', 'api_interaction.py', '--non-interactive', '--days', '1', '--observation-window', '2'], check=True)
            tle_updater_status_label.config(text="TLE Updater: Finished")
            logger.info("TLE Updater script finished successfully.")
        except subprocess.CalledProcessError as e:
            tle_updater_status_label.config(text=f"TLE Updater: Error ({e})")
            logger.error(f"TLE Updater script encountered an error: {e}")
            return  # Stop the cycle on error
    else:
        logger.info("Skipping TLE updater as tleplan.txt is current.")

    # Fetch sunset and sunrise times
    sunset_time, sunrise_time = update_sun_times()
    if sunset_time is None or sunrise_time is None:
        logger.error("Failed to retrieve sunset and sunrise times. Aborting cycle.")
        return

    # Wait until after sunset to start the automated2.py script
    current_time = datetime.now(pytz.timezone('America/Denver'))
    if current_time < sunset_time:
        wait_time_seconds = (sunset_time - current_time).total_seconds()
        logger.info(f"Waiting until 10 minutes after sunset ({sunset_time + timedelta(minutes=10)}) to start observations.")
        time.sleep(wait_time_seconds + 600)  # Wait until 10 minutes after sunset

    # Immediately start the automated2.py script
    logger.info("Starting automated2.py script.")
    run_script('automated2.py', automated2_status_label)

    logger.info("Automated observation cycle completed.")


app = tk.Tk()
app.title("New Mexico Skies Command Center")

# Prompt for user's first name
user_name = simpledialog.askstring("Enter Name", "Please enter your first name:")

if user_name:
    # Fetch the current time in MTC timezone
    mtc_zone = pytz.timezone('America/Denver')
    mtc_time = datetime.now(mtc_zone)
    
    # Get the part of the day
    part_of_day = get_part_of_day(mtc_time.hour)

    personalized_title = f"{part_of_day} {user_name},\nWelcome to New Mexico Skies Command Center"
    app.title(personalized_title)
    log_user_access(user_name)
else:
    personalized_title = "Welcome to New Mexico Skies Command Center"
    app.title(personalized_title)

# Set the window size and make it not resizable
app.geometry("575x920")

# Modern NASA-style color scheme
background_color = "#D9D9D9"  # Light grey
button_color = "#404040"  # Dark grey
text_color = "#FFFFFF"  # White

# Define a new color for the 'Run all' button
run_all_button_color = "#00FF00"  # Green color

app.configure(bg=background_color)

# Modern font for the title and buttons
title_font = font.Font(family="Arial", size=18, weight="bold")
button_font = font.Font(family="Arial", size=12, weight="bold")

# Modify title label
title_label = tk.Label(app, text=personalized_title, bg=background_color, fg=text_color, font=title_font)
title_label.pack(pady=20)

button_style = {'font': button_font, 'bg': button_color, 'fg': text_color}

# Example for the TLE Updater button
tle_updater_info = (
    "TLE Updater Button:\n\n"
    "Description: The TLE (Two-Line Element) Updater fetches the visible overhead passes for selected satellites. "
    "It uses the N2YO API to process a list of NORAD satellite IDs and calculates their observation times. "
    "This script efficiently manages observation schedules by filtering out overlapping times and ensuring a minimum "
    "one-minute gap between consecutive observations.\n\n"
    "Usage:\n"
    "1. Update Existing NORAD IDs: Automatically updates observation times for previously saved satellite IDs, "
    "defaulting to a one-day-ahead observation period.\n"
    "2. Enter New NORAD IDs: Input a new list of NORAD IDs (comma-separated) and specify the number of days (1-10) "
    "for which you want to fetch observation periods.\n"
    "3. Enter the observation window for the satellite overpasses 'full' for the entire observation or ex. 2 minute "
    "observation window +/- 2 minutes from the midpoint of the observation.\n\n"
    "This tool is essential for planning and scheduling satellite tracking activities, ensuring a streamlined observation process."
)

tle_updater_frame = tk.Frame(app, bg=background_color)
tle_updater_frame.pack(pady=5)

button1 = tk.Button(tle_updater_frame, text="Run TLE Updater", command=lambda: run_apiinteraction(), **button_style)
button1.pack(side=tk.LEFT)

info_button1 = tk.Button(tle_updater_frame, text="?", command=lambda: show_button_info(tle_updater_info), font=button_font, bg=button_color, fg=text_color)
info_button1.pack(side=tk.LEFT, padx=5)

tle_updater_status_label = tk.Label(tle_updater_frame, text="Status: Idle", bg=background_color, fg=text_color, font=button_font)
tle_updater_status_label.pack(side=tk.LEFT)

see_schedule_button = tk.Button(app, text="See Observation Schedule", command=open_tleplan, **button_style)
see_schedule_button.pack(pady=10)

# Automated2.py Function Frame
automated2_info = (
    "Run Observation Button:\n\n"
    "Description: Triggers the central command script for telescope, dome, and tracking/imaging operations.\n\n"
    "Functionality:\n"
    "1. Initiates telescope and dome operations.\n"
    "2. Observation Execution: Executes observations listed in tleplan.txt through the run_observer script.\n"
    "3. Executes shutdown of equipment after run_observer concludes.\n\n"
    "Key for automated and efficient satellite observation."
)

automated2_frame = tk.Frame(app, bg=background_color)
automated2_frame.pack(pady=5)

button3 = tk.Button(automated2_frame, text="Run Observation(s)", command=lambda: run_automated2(), **button_style)
button3.pack(side=tk.LEFT)

info_button3 = tk.Button(automated2_frame, text="?", command=lambda: show_button_info(automated2_info), font=button_font, bg=button_color, fg=text_color)
info_button3.pack(side=tk.LEFT, padx=5)

automated2_status_label = tk.Label(automated2_frame, text="Status: Idle", bg=background_color, fg=text_color, font=button_font)
automated2_status_label.pack(side=tk.LEFT)

# Automated Observation Cycle Frame
automated_cycle_info = (
    "Automated Observation Cycle Button:\n\n"
    "Description: Initiates a sequential execution of three primary observation scripts.\n\n"
    "Functionality:\n"
    "1. TLE Updater: Begins with TLE updater using default NORAD IDs (in the Planewave, Scripts folder - STARLINK SATELLITES) for a one-day-ahead observation period.\n"
    "2. Observation Script Execution: Waits 10 minutes post-sunset to start the observation script.\n"
    "3. Observatory Status Check: Checks observatory status before initiating observations.\n"
    "4. Pre-Sunrise Shutdown: Sends shutdown request to the observation script 10 minutes before sunrise.\n\n"
    "Checkbox Option: Allows skipping TLE updater and filter via a checkbox below this button.\n\n"
    "Ensures a systematic and efficient observation process."
)

automated_cycle_frame = tk.Frame(app, bg=background_color)
automated_cycle_frame.pack(pady=5)

automated_cycle_button = tk.Button(automated_cycle_frame, text="Start Automated Cycle", command=automated_observation_cycle, font=button_font, bg="#00FF00", fg=text_color)
automated_cycle_button.pack(side=tk.LEFT)

info_button_cycle = tk.Button(automated_cycle_frame, text="?", command=lambda: show_button_info(automated_cycle_info), font=button_font, bg=button_color, fg=text_color)
info_button_cycle.pack(side=tk.LEFT, padx=5)

automated_cycle_status_label = tk.Label(automated_cycle_frame, text="Status: Idle", bg=background_color, fg=text_color, font=button_font)
automated_cycle_status_label.pack(side=tk.LEFT)

def update_checkbox_label():
    if skip_scripts_var.get():
        checkbox_status_label.config(text="Skipping TLE Updater")
    else:
        checkbox_status_label.config(text="Including TLE Updater")

skip_scripts_var = tk.BooleanVar(value=False)
skip_scripts_checkbox = tk.Checkbutton(app, text="Skip TLE Updater", variable=skip_scripts_var, onvalue=True, offvalue=False, bg=background_color, fg=text_color, font=button_font, command=update_checkbox_label)
skip_scripts_checkbox.pack(pady=10)

checkbox_status_label = tk.Label(app, text="Including TLE Updater", bg=background_color, fg=text_color, font=button_font)
checkbox_status_label.pack(pady=5)

# Replace "Schedule Automated Observation Cycle" with "Start Infinite Observations"
infinite_cycle_frame = tk.Frame(app, bg=background_color)
infinite_cycle_frame.pack(pady=5)

start_infinite_button = tk.Button(infinite_cycle_frame, text="Start Infinite Observations", command=infinite_observation_cycle, **button_style)
start_infinite_button.pack(side=tk.LEFT)

# Add a stop button for infinite cycle
stop_infinite_button = tk.Button(infinite_cycle_frame, text="Stop Infinite Observations", command=stop_infinite_cycle, **button_style)
stop_infinite_button.pack(side=tk.LEFT, padx=5) # Add padding between buttons

infinite_cycle_status_label = tk.Label(infinite_cycle_frame, text="Status: Idle", bg=background_color, fg=text_color, font=button_font)
infinite_cycle_status_label.pack(side=tk.LEFT)

image_label = tk.Label(app)
image_label.pack(pady=5)

update_image_label()

app.mainloop()