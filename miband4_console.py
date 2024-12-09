#!/usr/bin/env python3

# This script demonstrates the usage, capability and features of the library.

import argparse
import subprocess
import time
import signal
from datetime import datetime

from bluepy.btle import BTLEDisconnectError
from cursesmenu import *
from cursesmenu.items import *

from constants import MUSICSTATE
from miband import miband

parser = argparse.ArgumentParser()
parser.add_argument('-m', '--mac', required=False, help='Set mac address of the device')
parser.add_argument('-k', '--authkey', required=False, help='Set Auth Key for the device')
args = parser.parse_args()

# Try to obtain MAC from the file
try:
    with open("mac.txt", "r") as f:
        mac_from_file = f.read().strip()
except FileNotFoundError:
    mac_from_file = None

# Use appropriate MAC
if args.mac:
    MAC_ADDR = args.mac
elif mac_from_file:
    MAC_ADDR = mac_from_file
else:
    print("Error:")
    print("  Please specify MAC address of the MiBand")
    print("  Pass the --mac option with MAC address or put your MAC to 'mac.txt' file")
    print("  Example of the MAC: a1:c2:3d:4e:f5:6a")
    exit(1)

# Validate MAC address
if 1 < len(MAC_ADDR) != 17:
    print("Error:")
    print("  Your MAC length is not 17, please check the format")
    print("  Example of the MAC: a1:c2:3d:4e:f5:6a")
    exit(1)

# Try to obtain Auth Key from file
try:
    with open("auth_key.txt", "r") as f:
        auth_key_from_file = f.read().strip()
except FileNotFoundError:
    auth_key_from_file = None

# Use appropriate Auth Key
if args.authkey:
    AUTH_KEY = args.authkey
elif auth_key_from_file:
    AUTH_KEY = auth_key_from_file
else:
    print("Warning:")
    print("  To use additional features of this script please put your Auth Key to 'auth_key.txt' or pass the --authkey option with your Auth Key")
    print()
    AUTH_KEY = None
    
# Validate Auth Key
if AUTH_KEY:
    if 1 < len(AUTH_KEY) != 32:
        print("Error:")
        print("  Your AUTH KEY length is not 32, please check the format")
        print("  Example of the Auth Key: 8fa9b42078627a654d22beff985655db")
        exit(1)

# Convert Auth Key from hex to byte format
if AUTH_KEY:
    AUTH_KEY = bytes.fromhex(AUTH_KEY)

def general_info():
    print ('MiBand')
    print ('Soft revision:',band.get_revision())
    print ('Hardware revision:',band.get_hrdw_revision())
    print ('Serial:',band.get_serial())
    print ('Battery:', band.get_battery_info()['level'])
    print ('Time:', band.get_current_time()['date'].isoformat())
    input('Press a key to continue')



# Needs Auth
def get_heart_rate():
    print ('Latest heart rate is : %i' % band.get_heart_rate_one_time())
    input('Press a key to continue')


# def heart_logger(data):
#     print ('Realtime heart BPM:', data)


# Needs Auth
def get_realtime():
    try:
        print("Starting real-time heart rate monitoring. Press Ctrl+C to stop.")
        band.start_heart_rate_realtime(heart_measure_callback=heart_logger)
    except KeyboardInterrupt:
        print("\nStopping heart rate monitoring...")
        band.stop_realtime()

def heart_logger(data):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Realtime heart BPM: {data} at {timestamp}")
    

import time
from datetime import datetime

heart_rate_records = []

def record_heart_rate():
    try:
        print("Starting heart rate recording. Press any key to stop.")
        while True:
            heart_rate = band.get_heart_rate_one_time()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            heart_rate_records.append({
                "timestamp": timestamp, 
                "heart_rate": heart_rate
            })
            print(f"Heart Rate: {heart_rate} BPM at {timestamp}")
            time.sleep(7)
    except KeyboardInterrupt:
        print("\nStopping heart rate recording.")
    
    # Print final recorded data
    print("\nRecorded Heart Rate Data:")
    for record in heart_rate_records:
        print(f"{record['timestamp']}: {record['heart_rate']} BPM")
        
    # save_to_csv()

def save_to_csv():
    import csv
    filename = f"heart_rate_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(filename, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=['timestamp', 'heart_rate'])
        writer.writeheader()
        writer.writerows(heart_rate_records)
    print(f"Data saved to {filename}")
    
if __name__ == "__main__":
    try:
        success = False
        while not success:
            try:
                if (AUTH_KEY):
                    band = miband(MAC_ADDR, AUTH_KEY, debug=True)
                    success = band.initialize()
                else:
                    band = miband(MAC_ADDR, debug=True)
                    success = True
                break
            except BTLEDisconnectError:
                print('Connection to the MIBand failed. Trying out again in 3 seconds')
                time.sleep(3)
                continue

        menu = CursesMenu("MIBand4", "Features marked with @ require Auth Key")
        info_item = FunctionItem("Get general info of the device", general_info)
        single_heart_rate_item = FunctionItem("@ Get Heart Rate", get_heart_rate)
        real_time_heart_rate_item = FunctionItem("@ Record realtime heart rate data", get_realtime)

        menu.items.append(info_item)
        menu.items.append(single_heart_rate_item)
        menu.items.append(real_time_heart_rate_item)

        menu.show()

    except KeyboardInterrupt:
        print("\nExiting program...")

    finally:
        print("Goodbye!")
