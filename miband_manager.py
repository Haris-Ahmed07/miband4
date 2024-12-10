#!/usr/bin/env python3
"""
MiBand 4 Manager Class

This module provides the core management class for interacting with Xiaomi MiBand 4 
using Bluetooth Low Energy (BLE) communication.

Dependencies:
- bluepy
- csv
- datetime
"""

import time
import csv
from datetime import datetime

from bluepy.btle import BTLEDisconnectError
from miband import miband

class MiBandManager:
    """
    Main class to manage MiBand 4 device interactions and data collection.
    """
    
    def __init__(self, mac_address, auth_key=None):
        """
        Initialize MiBand connection and parameters.
        
        Args:
            mac_address (str): Bluetooth MAC address of the MiBand device
            auth_key (bytes, optional): Authentication key for advanced features
        """
        self.MAC_ADDR = mac_address
        self.AUTH_KEY = auth_key
        self.band = None
        self.heart_rate_records = []
        # Flag to control real-time heart rate logging
        self.is_logging_realtime = False
    
    def connect(self):
        """
        Establish connection with the MiBand device.
        
        Returns:
            bool: Connection status
        """
        try:
            if self.AUTH_KEY:
                self.band = miband(self.MAC_ADDR, self.AUTH_KEY, debug=True)
                return self.band.initialize()
            else:
                self.band = miband(self.MAC_ADDR, debug=True)
                return True
        except BTLEDisconnectError:
            print('Connection failed. Retrying...')
            time.sleep(3)
            return False
    
    def heart_logger(self, heart_rate):
        """
        Universal heart rate logging method for both one-time and real-time measurements.
        
        Args:
            heart_rate (int): Heart rate in beats per minute
        """
        try:
            # Generate timestamp for the current heart rate reading
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Create a record dictionary
            record = {
                "timestamp": timestamp, 
                "heart_rate": heart_rate
            }
            
            # Add to records list
            self.heart_rate_records.append(record)
            
            # Print real-time information
            print(f"Heart Rate: {heart_rate} BPM at {timestamp}")
        except Exception as e:
            print(f"Heart rate logging error: {e}")
    
    def get_single_heart_rate(self):
        """
        Get and display a single heart rate measurement.
        """
        try:
            heart_rate = self.band.get_heart_rate_one_time()
            self.heart_logger(heart_rate)
            input('Press any key to continue...')
        except Exception as e:
            print(f"Error getting heart rate: {e}")
            input('Press any key to continue...')
    
    def record_heart_rate_intervals(self, interval=7):
        """
        Record heart rate at specified intervals.
        
        Args:
            interval (int, optional): Time between heart rate measurements. Defaults to 7 seconds.
        """
        # Reset records before starting
        self.heart_rate_records = []
        
        try:
            print(f"Starting heart rate recording. Press Ctrl+C to stop (Interval: {interval} seconds)")
            while True:
                try:
                    heart_rate = self.band.get_heart_rate_one_time()
                    self.heart_logger(heart_rate)
                    time.sleep(interval)
                
                except Exception as e:
                    print(f"Heart rate retrieval error: {e}")
                    break
        
        except KeyboardInterrupt:
            print("\nStopping heart rate recording.")
        finally:
            if self.heart_rate_records:
                self.save_heart_rate_to_csv()
            input('Press any key to continue...')
    
    def record_heart_rate_realtime(self):
        """
        Start real-time heart rate monitoring.
        Allows continuous heart rate tracking with a callback.
        """
        try:
            print("Starting real-time heart rate monitoring. Press Ctrl+C to stop.")
            # Reset records for new real-time session
            self.heart_rate_records = []
            
            # Start real-time heart rate monitoring
            self.is_logging_realtime = True
            self.band.start_heart_rate_realtime(heart_measure_callback=self.heart_logger)
            
            # Wait for user to interrupt
            input('Press Enter to stop real-time monitoring...')
        
        except KeyboardInterrupt:
            print("\nStopping real-time heart rate monitoring.")
        except Exception as e:
            print(f"Real-time heart rate error: {e}")
        finally:
            # Stop real-time monitoring
            self.is_logging_realtime = False
            
            # Save recorded data if any
            if self.heart_rate_records:
                self.save_heart_rate_to_csv()
    
    def save_heart_rate_to_csv(self):
        """
        Save recorded heart rate data to a CSV file.
        """
        try:
            # Generate unique filename with timestamp
            filename = f"heart_rate_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            with open(filename, 'w', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=['timestamp', 'heart_rate'])
                writer.writeheader()
                writer.writerows(self.heart_rate_records)
            
            print(f"Heart rate data saved to {filename}")
        except Exception as e:
            print(f"CSV save error: {e}")

    def get_device_info(self):
        """
        Retrieve and display basic device information.
        """
        print('MiBand Device Information:')
        print('Soft revision:', self.band.get_revision())
        print('Hardware revision:', self.band.get_hrdw_revision())
        print('Serial:', self.band.get_serial())
        print('Battery:', self.band.get_battery_info()['level'])
        print('Time:', self.band.get_current_time()['date'].isoformat())
        input('Press any key to continue...')