# File: ap_network_manager.py
# Version: 1.0.3
# Description: A standalone script to manage the Pi's network connections for configuring a miner's AP.

import subprocess
import time
import argparse
import re
import os
import json

# --- Configuration ---
MINER_AP_SSID = "NerdMinerAP"
APAUTH = "MineYourCoins"
STATE_FILE = os.path.expanduser('~/shepherd_data/network_state.json')

def run_command(command, use_sudo=False):
    """Runs a shell command and returns its output, optionally with sudo."""
    if use_sudo:
        command = "sudo " + command
        
    try:
        result = subprocess.run(command, check=True, shell=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Command '{command}' failed with exit code {e.returncode}")
        print(f"Stderr: {e.stderr.strip()}")
        return None

def save_current_state():
    """Finds the currently active Wi-Fi connection and saves its name."""
    print("--- Finding and saving current Wi-Fi state...")
    # Get the name of the active Wi-Fi device (e.g., wlan0)
    wifi_device = run_command("nmcli -t -f DEVICE,TYPE device status | grep 'wifi' | cut -d':' -f1 | head -n1")
    if not wifi_device:
        print("ERROR: Could not find an active Wi-Fi device.")
        return False
        
    # Get the name (SSID) of the currently connected network on that device
    active_connection = run_command(f"nmcli -t -f NAME,DEVICE connection show --active | grep {wifi_device} | cut -d':' -f1")
    if not active_connection:
        print("ERROR: Could not determine the active Wi-Fi connection name (SSID).")
        return False

    state = {'original_connection': active_connection, 'wifi_device': wifi_device}
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)
        
    print(f"State saved. Original active connection is '{active_connection}' on device '{wifi_device}'.")
    return True

def load_original_state():
    """Loads the saved network state."""
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE, 'r') as f:
        return json.load(f)

def connect_to_miner_ap():
    """Scans for and connects to the miner's AP using a more robust method."""
    print(f"\n--- Attempting to connect to '{MINER_AP_SSID}'...")
    state = load_original_state()
    if not state or 'wifi_device' not in state:
        print("ERROR: Could not determine the Wi-Fi device from saved state.")
        return False
    wifi_device = state['wifi_device']

    # Preemptively delete any old connection profile for the miner
    run_command(f"nmcli connection delete '{MINER_AP_SSID}'", use_sudo=True)
    time.sleep(2)

    print("Scanning for networks...")
    run_command(f"nmcli device wifi rescan", use_sudo=True)
    time.sleep(5)

    scan_result = run_command(f"nmcli device wifi list | grep '{MINER_AP_SSID}'")
    if not scan_result:
        print(f"ERROR: Miner AP '{MINER_AP_SSID}' not found. Is the miner in AP mode?")
        return False

    print(f"Miner AP found. Creating explicit connection profile...")
    
    # This is the new, more robust multi-step connection process.
    # 1. Add a new connection profile.
    add_cmd = f"nmcli connection add type wifi con-name '{MINER_AP_SSID}' ifname '{wifi_device}' ssid '{MINER_AP_SSID}'"
    run_command(add_cmd, use_sudo=True)
    
    # 2. Modify it to specify the security protocol and password.
    modify_sec_cmd = f"nmcli connection modify '{MINER_AP_SSID}' wifi-sec.key-mgmt wpa-psk"
    run_command(modify_sec_cmd, use_sudo=True)
    modify_psk_cmd = f"nmcli connection modify '{MINER_AP_SSID}' wifi-sec.psk '{APAUTH}'"
    run_command(modify_psk_cmd, use_sudo=True)

    # 3. Bring the new connection up.
    up_cmd = f"nmcli connection up '{MINER_AP_SSID}'"
    result = run_command(up_cmd, use_sudo=True)

    if result and "successfully activated" in result:
        print("Successfully connected to the miner's AP.")
        time.sleep(10) # Wait for IP address
        return True
    
    print("ERROR: Failed to connect to the miner's AP.")
    # Clean up the failed profile
    run_command(f"nmcli connection delete '{MINER_AP_SSID}'", use_sudo=True)
    return False

def reconnect_to_original():
    """Disconnects from the miner and reconnects to the original network."""
    print("\n--- Reconnecting to original network...")
    state = load_original_state()
    if not state or 'original_connection' not in state:
        print("ERROR: No original connection state found. Cannot reconnect automatically.")
        return False

    original_connection = state['original_connection']
    print(f"Attempting to reconnect to '{original_connection}'...")
    
    run_command(f"nmcli connection down '{MINER_AP_SSID}'", use_sudo=True)
    run_command(f"nmcli connection delete '{MINER_AP_SSID}'", use_sudo=True)
    
    result = run_command(f"nmcli connection up '{original_connection}'", use_sudo=True)
    
    if result and "successfully activated" in result:
        print("Successfully reconnected to the original network.")
        os.remove(STATE_FILE)
        return True
        
    print(f"ERROR: Failed to reconnect to '{original_connection}'. Please check your network settings.")
    return False

def main(action):
    if action == 'connect':
        if save_current_state():
            connect_to_miner_ap()
    elif action == 'reconnect':
        reconnect_to_original()
    else:
        print(f"Unknown action: {action}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Manage Pi network connections for miner AP configuration.',
        epilog="Example Usage:\n  python3 ap_network_manager.py --action connect\n  python3 ap_network_manager.py --action reconnect"
    )
    parser.add_argument('--action', required=True, choices=['connect', 'reconnect'], help='The action to perform.')
    args = parser.parse_args()
    main(args.action)

