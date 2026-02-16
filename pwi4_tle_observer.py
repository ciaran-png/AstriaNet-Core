from datetime import datetime
import os
from io import StringIO  # Modified line
import time
import pythoncom
from pwi4_client import PWI4
from win32com.client import Dispatch

OUTPUT_PATH = 'D:\\SatelliteData'
EXPOSURE_LENGTH_SEC = 0.1
TLE_PLAN_FILENAME = "tleplan.txt"

# Here are the sample contents of a TLE plan file:
SAMPLE_TLE_PLAN_TEXT = """
BEGINLOCAL 2018-10-17 16:14:30
ENDLOCAL 2018-10-17 16:15:30
NAME 15495U
0 SL-14 R/B
1 15495U 85009B   18289.93143704  .00000089  00000-0  77542-5 0  9992
2 15495  82.5218  91.5250 0020622 160.2692 199.9326 14.83822226822146

BEGINLOCAL 2018-10-17 16:16:00
ENDLOCAL 2018-10-17 16:17:00
NAME 14820U
0 SL-14 R/B
1 14820U 84027B   18289.95350827 +.00000084 +00000-0 +73211-5 0  9994
2 14820 082.5420 250.6068 0017200 253.3402 106.5925 14.83611386847046
"""

def run_observer(tle_data):
    try:
        pythoncom.CoInitialize()
        log("Checking connection to PWI4...")
        pwi = PWI4()

        # Camera initialization and cooler control
        log("Connecting to camera")
        cam = Dispatch("MaxIm.CCDCamera")
        cam.LinkEnabled = True
        cam.DisableAutoShutdown = True
        cam.CoolerOn = True  # Turn on the cooler
        # cam.SetTemperature = 20  # Set to a high temperature if needed

        status = pwi.status()
        if not status.mount.is_connected:
            log("ERROR: Not connected to mount")
            return "Mount not connected."

        log("Connecting to camera")
        cam = Dispatch("MaxIm.CCDCamera")
        cam.LinkEnabled = True
        cam.DisableAutoShutdown = True

        f = open(TLE_PLAN_FILENAME)
        tle_plan_text = f.read()
        f.close()

        plan = Plan()
        plan.parse(tle_plan_text)

        for entry in plan.entries:
            while True:
                seconds_until_begin = (entry.begin_time_local - datetime.now()).total_seconds()
                if seconds_until_begin > 0:
                    log("Sleeping %d seconds until next target %s" % (seconds_until_begin, entry.name))
                    time.sleep(1)
                else:
                    break
            log("Slewing to %s" % entry.name)
            response = pwi.mount_follow_tle(entry.tle1, entry.tle2, entry.tle3)
            log("Response: %s" % response)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            subdir_name = "%s_%s" % (timestamp, entry.name)
            image_dir = os.path.join(OUTPUT_PATH, subdir_name)
            if not os.path.exists(image_dir):
                log("Creating directory %s" % image_dir)
                os.makedirs(image_dir)

            image_count = 1

            while True:
                seconds_until_end = (entry.end_time_local - datetime.now()).total_seconds()
                if seconds_until_end < 0:
                    log("Finished with target")
                    pwi.mount_stop()
                    break
                else:
                    cam.Expose(EXPOSURE_LENGTH_SEC, 1)

                    status = pwi.status()
                    azimuth_degs = status.mount.azimuth_degs
                    altitude_degs = status.mount.altitude_degs
                    axis0_dist_to_target_arcsec = status.mount.axis0.dist_to_target_arcsec
                    axis1_dist_to_target_arcsec = status.mount.axis1.dist_to_target_arcsec

                    filename = "%04d_Azm_%.3f_Alt_%.3f_Axis0Dist_%.2f_Axis1Dist_%.2f.fits" % (
                        image_count,
                        azimuth_degs,
                        altitude_degs,
                        axis0_dist_to_target_arcsec,
                        axis1_dist_to_target_arcsec
                    )

                    while not cam.ImageReady:
                        time.sleep(0.1)
                    
                    full_file_path = os.path.join(image_dir, filename)
                    log(full_file_path)
                    cam.SaveImage(full_file_path)
                    image_count += 1

                    log("    Following target for %d more seconds" % seconds_until_end)

        return "Observation completed successfully."

    except Exception as e:
        return f"Observation failed: {str(e)}"

    finally:
        # Turn off the cooler safely
        try:
            if cam:
                log("Setting cooler to high temperature before shutting off")
                cam.SetTemperature = 20  # Set to a high temperature before turning off
                time.sleep(60)  # Wait for 60 seconds (adjust as needed)
                cam.CoolerOn = False  # Turn off the cooler
        except Exception as e:
            log(f"Error in turning off the cooler: {str(e)}")

        # Any other cleanup code, if needed
        pass

def log(line):
    print (line)    

class PlanEntry:
    def __init__(self):
        self.begin_time_local = None
        self.end_time_local = None
        self.name = None
        self.tle1 = None
        self.tle2 = None
        self.tle3 = None

class Plan:
    def __init__(self):
        self.entries = []

    def parse(self, plan_text):
        reader = StringIO(plan_text)

        while True:
            next_entry = self.parse_single_entry(reader)
            if next_entry == None:
                return  # End of file reached
            self.entries.append(next_entry)

    def parse_single_entry(self, plan_reader):
        begin_local_str = self.read_next_record("BEGINLOCAL", plan_reader)
        end_local_str = self.read_next_record("ENDLOCAL", plan_reader)
        name = self.read_next_record("NAME", plan_reader)
        tle1 = self.read_next_record(None, plan_reader)
        tle2 = self.read_next_record(None, plan_reader)
        tle3 = self.read_next_record(None, plan_reader)

        if tle3 == None:
            return None # End of file

        entry = PlanEntry()
        entry.begin_time_local = self.parse_time(begin_local_str)
        entry.end_time_local = self.parse_time(end_local_str)
        entry.name = name
        entry.tle1 = tle1
        entry.tle2 = tle2
        entry.tle3 = tle3

        return entry
        
    
    def read_next_record(self, expected_prefix, plan_reader):
        line = self.read_next_nonempty_line(plan_reader)
        if line == None:
            return None  # End of file
        
        if expected_prefix == None:
            return line

        fields = line.split(' ', 1)
        if fields[0] != expected_prefix:
            raise Exception("Expected prefix '%s', got '%s'" % (expected_prefix, fields[0]))
        return fields[1]
    
    def read_next_nonempty_line(self, plan_reader):
        while True:
            line = plan_reader.readline()
            if line == '':
                return None # End of file
            
            line = line.strip()
            if line == '':
                continue # Blank line
            return line

    def parse_time(self, time_string):
        return datetime.strptime(time_string, "%Y-%m-%d %H:%M:%S")
        


if __name__ == "__main__":
    main()
