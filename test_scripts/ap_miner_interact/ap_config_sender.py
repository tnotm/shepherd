# File: ap_config_sender.py
# Version: 2.0.0
# Description: A script to send a complete configuration (Wi-Fi and Pool) to a NerdMiner in AP mode.

import requests
import argparse
import json
import os
import getpass

# --- Configuration ---
MINER_AP_URL = "http://192.168.4.1/wifisave"
CONFIG_FILE = 'ap_config.json'

def load_config_from_file():
    """Loads all necessary configuration from the JSON config file."""
    if not os.path.exists(CONFIG_FILE):
        print(f"ERROR: Configuration file '{CONFIG_FILE}' not found.")
        return None
    
    required_keys = ["local_wifi_ssid", "poolString", "portNumber", "btcString", "poolPassword", "gmtZone"]
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        missing_keys = [key for key in required_keys if key not in config]
        if missing_keys:
            print(f"ERROR: '{CONFIG_FILE}' is missing required keys: {', '.join(missing_keys)}")
            return None
            
        return config
    except json.JSONDecodeError:
        print(f"ERROR: Could not parse '{CONFIG_FILE}'. Please ensure it is valid JSON.")
        return None

def send_full_config(config, miner_id, wifi_password):
    """
    Sends the complete configuration payload to the miner's combined web form.
    """
    full_wallet_string = f"{config['btcString']}.{miner_id}"
    
    # This payload now matches all the fields in the single form from the source HTML.
    payload = {
        's': config['local_wifi_ssid'],
        'p': wifi_password,
        'Poolurl': config['poolString'],
        'Poolport': str(config['portNumber']),
        'btcAddress': full_wallet_string,
        'TimeZone': str(config['gmtZone']),
        'SaveStatsToNVS': 'T' # Assuming we always want this on.
    }
    
    print(f"--- Sending full configuration to {MINER_AP_URL} ---")
    for key, value in payload.items():
        # Don't print the password.
        if key == 'p': continue
        print(f"  {key}: {value}")
    
    try:
        response = requests.post(MINER_AP_URL, data=payload, timeout=20)
        
        # A successful submission will cause the miner to reboot. The firmware
        # sends back a simple "success" message before it does.
        if response.status_code == 200 and "successfully" in response.text:
            print("\nSUCCESS: Full configuration sent successfully.")
            print("The miner should now reboot and connect to your local network with the new mining settings.")
            return True
        else:
            print(f"\nERROR: Received an unexpected response (Status Code: {response.status_code})")
            print("Response Text:", response.text[:250])
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"\nERROR: Failed to connect to the miner at {MINER_AP_URL}.")
        print("Please ensure the Pi is connected to the 'NerdMinerAP' network.")
        print(f"Details: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Send a complete configuration to a NerdMiner in AP mode.',
        epilog="Example Usage:\n  1. Edit ap_config.json.\n  2. Run: python3 ap_config_sender.py --id MINER_001"
    )
    parser.add_argument('--id', required=True, help='The desired Miner ID to append to the BTC address.')
    
    args = parser.parse_args()
    
    config = load_config_from_file()
    if config:
        try:
            wifi_pass = getpass.getpass(prompt=f"Enter the password for Wi-Fi network '{config['local_wifi_ssid']}': ")
            if wifi_pass:
                send_full_config(config, args.id, wifi_pass)
            else:
                print("Password cannot be empty. Aborting.")
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")

