#!/usr/bin/env python3
"""
MiBand 4 Interaction Script

This script provides a comprehensive interface for interacting with Xiaomi MiBand 4 
using Bluetooth Low Energy (BLE) communication. It offers various features including 
heart rate monitoring, device information retrieval, and data logging.

Dependencies:
- cursesmenu
- argparse
"""

import argparse
from cursesmenu import CursesMenu
from cursesmenu.items import FunctionItem
from miband_manager import MiBandManager

def validate_mac_address(mac_address):
    """
    Validate Bluetooth MAC address format.
    
    Args:
        mac_address (str): MAC address to validate
    
    Raises:
        SystemExit: If MAC address is invalid
    """
    if len(mac_address) != 17:
        print("Error: Invalid MAC address format")
        print("Example: a1:c2:3d:4e:f5:6a")
        exit(1)

def load_auth_key(auth_key_path=None):
    """
    Load authentication key from file or command line.
    
    Args:
        auth_key_path (str, optional): Path to auth key file
    
    Returns:
        bytes or None: Authentication key
    """
    try:
        # Try loading from file if path provided
        if auth_key_path:
            with open(auth_key_path, "r") as f:
                auth_key = f.read().strip()
        else:
            with open("auth_key.txt", "r") as f:
                auth_key = f.read().strip()
        
        # Validate key length
        if len(auth_key) != 32:
            print("Error: Invalid Auth Key length")
            return None
        
        return bytes.fromhex(auth_key)
    
    except FileNotFoundError:
        print("Warning: No auth key found")
        return None

def main():
    """
    Main application entry point.
    Handles argument parsing, device connection, and menu interaction.
    """
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="MiBand 4 Interaction Tool")
    parser.add_argument('-m', '--mac', help='Bluetooth MAC address of MiBand')
    parser.add_argument('-k', '--authkey', help='Authentication key file path')
    args = parser.parse_args()

    # Load MAC address
    mac_address = args.mac or None
    if not mac_address:
        try:
            with open("mac.txt", "r") as f:
                mac_address = f.read().strip()
        except FileNotFoundError:
            print("Error: No MAC address specified")
            exit(1)

    # Validate and load components
    validate_mac_address(mac_address)
    auth_key = load_auth_key(args.authkey)

    # Initialize MiBand manager
    miband_manager = MiBandManager(mac_address, auth_key)

    # Establish connection
    while not miband_manager.connect():
        pass

    # Create interactive menu
    menu = CursesMenu("MiBand4", "Features marked with @ require Auth Key")
    menu.items.extend([
        FunctionItem("Get Device Info", miband_manager.get_device_info),
        FunctionItem("@ Get Single Heart Rate", miband_manager.get_single_heart_rate),
        FunctionItem("@ Record Heart Rate In Intervals", miband_manager.record_heart_rate_intervals),
        FunctionItem("@ Record Heart Rate In RealTime", miband_manager.record_heart_rate_realtime)
    ])

    try:
        menu.show()
    except KeyboardInterrupt:
        print("\nExiting program...")
    finally:
        print("Saving data...")
        miband_manager.save_heart_rate_to_csv()
        print("Goodbye!")

if __name__ == "__main__":
    main()