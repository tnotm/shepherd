# shepherds_dog.py
# Version: 0.0.1.9
# Description: Monitors USB devices and miner statuses, writing results to JSON.
# CHANGED: Refined miner matching logic to prioritize MAC address from miners table.

import pyudev
import sqlite3
import json
import time
import os
import threading
from datetime import datetime, timedelta, UTC

# --- Configuration ---
# ... (Config vars remain the same) ...
DATA_DIR = os.path.expanduser('~/shepherd_data')
DATABASE_FILE = os.path.join(DATA_DIR, 'shepherd.db')
OUTPUT_FILE = os.path.join(DATA_DIR, 'device_state.json')
POLL_INTERVAL_SECONDS = 5 
STALE_THRESHOLD_MINUTES = 5
COMMON_MINER_VENDOR_IDS = {'10c4', '303a', '1a86'}


# ... (Permissions Check, DB Connection unchanged) ...
# Ensure DATA_DIR exists
os.makedirs(DATA_DIR, exist_ok=True)
if not os.access(DATA_DIR, os.W_OK): print(f"CRITICAL ERROR: Directory {DATA_DIR} not writable.") # Simplified
else: print(f"[Permissions] Write access to {DATA_DIR} confirmed.")
def get_db_connection():
    # ... unchanged ...
    conn = None 
    try:
        conn = sqlite3.connect(DATABASE_FILE, timeout=10); conn.row_factory = sqlite3.Row
        conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='miners';").fetchone()
        # print("[DB Connection] Database connection successful.") # Simplified log - Can be noisy
        return conn
    except sqlite3.OperationalError as e:
        if "no such table: miners" in str(e): print(f"[DB Connection] WARNING: 'miners' table not found...")
        else: print(f"[DB Connection] ERROR: Database operational error: {e}.")
        if conn: conn.close(); return None 
    except Exception as e:
        print(f"[DB Connection] ERROR: Unexpected error connecting to database: {e}")
        if conn: conn.close(); return None


def get_miner_details(conn):
    """Fetches essential details for all configured miners."""
    try:
        # Fetch MAC address as well
        miners = conn.execute("""
            SELECT id, miner_id, port_path, attrs_serial, mac_address, status, state, 
                   pool_url, wallet_address, nerdminer_vrs, last_seen, location_notes, chipset
            FROM miners;
        """).fetchall()
        
        # ** Build two maps: one by (port, attrs_serial), one by mac_address **
        miner_map_serial = {}
        miner_map_mac = {}
        
        for m in miners:
            miner_dict = dict(m)
            # Key for serial map (port + USB serial/placeholder)
            key_serial = miner_dict['attrs_serial'] 
            key_port = miner_dict['port_path']
            if key_port and key_serial: 
                miner_map_serial[(key_port, key_serial)] = miner_dict
            
            # Key for MAC map (just MAC address)
            key_mac = miner_dict['mac_address']
            if key_mac:
                 # Check for duplicate MACs - should ideally not happen due to DB constraint
                 if key_mac in miner_map_mac:
                      print(f"[Dog] WARNING: Duplicate MAC address '{key_mac}' found in DB for miners {miner_map_mac[key_mac]['id']} and {miner_dict['id']}. Matching might be unreliable.")
                 miner_map_mac[key_mac] = miner_dict

        print(f"[Dog] Found {len(miner_map_serial)} miners by Serial key, {len(miner_map_mac)} by MAC key.") # Debug
        # Return both maps
        return miner_map_serial, miner_map_mac 
    except sqlite3.Error as e:
        print(f"Database error fetching miners: {e}")
        return {}, {} # Return empty maps on error

def get_stray_details(conn):
    """Fetches details for all devices currently in the stray_devices table."""
    try:
        # ** Select MAC address as well **
        strays = conn.execute("""
            SELECT port_path, serial_number, mac_address, chipset, status, state, 
                   dumped_pool_url, dumped_wallet_address, dumped_firmware_version
            FROM stray_devices; 
        """).fetchall()
        # Key by (port_path, original_serial_number)
        stray_map = {
            (s['port_path'], s['serial_number']): dict(s) 
            for s in strays if s['port_path'] and s['serial_number']
        }
        # print(f"[Dog] Found {len(stray_map)} entries in stray_devices table.") # Debug - noisy
        return stray_map
    except sqlite3.Error as e:
        print(f"Database error fetching stray devices: {e}")
        return {}


# --- Device Monitoring ---
def get_connected_devices():
    """Gets a list of currently connected USB TTY devices by iterating all devices."""
    # ... (function content unchanged from V.0.0.1.5) ...
    context = pyudev.Context()
    devices = []
    # print("[Dog][udev] Starting full device scan...") # DEBUG - noisy
    try:
        for device in context.list_devices():
            devname = device.properties.get('DEVNAME')
            is_usb = device.properties.get('ID_BUS') == 'usb'
            is_tty_like = devname and (devname.startswith('/dev/ttyACM') or devname.startswith('/dev/ttyUSB') or 'tty' in (device.subsystem or ''))
            if not (is_usb and is_tty_like): continue 
            # print(f"[Dog][udev]   Potential USB TTY candidate: {devname} (Subsystem: {device.subsystem})") # DEBUG - noisy
            usb_device = None
            try:
                usb_device = device.find_parent('usb', 'usb_device'); 
                if not usb_device: continue
            except: continue
            serial_num = usb_device.properties.get('ID_SERIAL_SHORT')
            vendor_id = usb_device.properties.get('ID_VENDOR_ID')
            product_id = usb_device.properties.get('ID_MODEL_ID') 
            if not serial_num and vendor_id not in COMMON_MINER_VENDOR_IDS: continue
            if not serial_num and vendor_id in COMMON_MINER_VENDOR_IDS: serial_num = f"VID_{vendor_id}_NOSERIAL" 
            port_path = "Unknown"
            try:
                devpath_parts = usb_device.device_path.split('/')
                usb_part = next((part for part in reversed(devpath_parts) if '-' in part and ':' not in part), None)
                if usb_part: port_path = usb_part
            except: pass
            if port_path == "Unknown": continue
            details = { 'dev_path': devname, 'port_path': port_path, 'serial_number': serial_num, 'vendor_id': vendor_id, 'product_id': product_id }
            device_key = (details['port_path'], details['serial_number'])
            if device_key not in [(d['port_path'], d['serial_number']) for d in devices]:
                devices.append(details)
                # print(f"[Dog][udev]   Found device: {details}") # DEBUG - noisy
        # print(f"[Dog][udev] Finished full scan. Found {len(devices)} potential miner devices.") # DEBUG - noisy
    except Exception as e:
        print(f"[Dog][udev] ERROR during full device scan: {e}"); import traceback; traceback.print_exc() 
    return devices


# --- Main Loop ---
def monitor_and_update():
    """Main loop to check devices, query DB, and write status file."""
    print("Starting Shepherd's Dog monitoring loop...")
    last_run_miners_serial = {} # Cache by serial key
    last_run_miners_mac = {} # Cache by MAC key
    last_run_strays = {} # Cache for strays
    error_state = None 

    while True:
        start_time = time.time()
        # print(f"[{datetime.now(UTC).isoformat()}] Running check...") # Debug - noisy

        merged_state = [] 
        current_error = None 

        # 1. Get currently connected devices
        connected_devices = get_connected_devices()
        # Map by (port, serial) reported by udev NOW
        connected_map = {(d['port_path'], d['serial_number']): d for d in connected_devices if d['port_path'] != 'Unknown' and d['serial_number']} 

        # 2. Get miner and stray details from DB (with error handling)
        miners_from_db_serial = {}
        miners_from_db_mac = {} # ** NEW **
        strays_from_db = {} 
        db_conn = get_db_connection() 
        if db_conn:
            try:
                miners_from_db_serial, miners_from_db_mac = get_miner_details(db_conn) # ** MODIFIED **
                strays_from_db = get_stray_details(db_conn) 
                last_run_miners_serial = miners_from_db_serial # Update caches
                last_run_miners_mac = miners_from_db_mac
                last_run_strays = strays_from_db 
                if error_state == "DB Error": print("[Dog] Database connection restored."); error_state = None
            except Exception as e: 
                print(f"ERROR: Exception during DB queries: {e}")
                current_error = f"DB Query Error: {e}"
                miners_from_db_serial = last_run_miners_serial # Use caches
                miners_from_db_mac = last_run_miners_mac
                strays_from_db = last_run_strays 
            finally:
                db_conn.close() 
        else:
            print("ERROR: Failed to establish DB connection. Using cached lists.")
            current_error = "DB Connection Error"
            miners_from_db_serial = last_run_miners_serial # Use caches
            miners_from_db_mac = last_run_miners_mac
            strays_from_db = last_run_strays 
            error_state = "DB Error" 


        # 3. Merge and determine status
        processed_miner_ids = set() # Track miner IDs already added to prevent duplicates from different keys

        # Iterate through connected devices 
        for key, device_data in connected_map.items():
            port_key = key[0]
            serial_key = key[1] # This is the serial reported by udev now
            
            miner_info = None
            matched_by = None

            # --- ** REFINED Matching Logic ** ---
            # Priority 1: Check if this device matches a KNOWN miner by (port, udev_serial)
            miner_info = miners_from_db_serial.get(key)
            if miner_info:
                 matched_by = "Serial Key"
                 print(f"[Dog] Matched connected device {key} to miner ID {miner_info['id']} using Serial Key.") # DEBUG
            
            # Priority 2: If no serial match, check if we have captured a MAC for this STRAY
            #             in the stray_devices table (using udev serial key)
            #             AND if that MAC matches a known miner in the MAC map.
            if not miner_info:
                 stray_info_for_mac_check = strays_from_db.get(key) 
                 potential_mac = stray_info_for_mac_check.get('mac_address') if stray_info_for_mac_check else None # Use dedicated MAC column
                 
                 if potential_mac: # If stray record has a captured MAC
                      miner_info = miners_from_db_mac.get(potential_mac) # Look up miner by MAC
                      if miner_info:
                           # Crucial Check: Ensure the ports also match 
                           if miner_info.get('port_path') == port_key:
                                matched_by = "MAC Key (via Stray)"
                                print(f"[Dog] Matched connected device {key} to miner ID {miner_info['id']} using captured MAC '{potential_mac}' from stray table.") # DEBUG
                           else:
                                print(f"[Dog] WARNING: MAC '{potential_mac}' matches miner {miner_info['id']}, but port mismatch (Device: {port_key}, Miner DB: {miner_info.get('port_path')}). Ignoring MAC match.") # DEBUG
                                miner_info = None # Invalidate match


            # --- Process based on Match ---
            if miner_info:
                 # --- Known Miner - Currently Connected ---
                 miner_id = miner_info['id']
                 if miner_id in processed_miner_ids: 
                      # print(f"[Dog] Skipping duplicate processing for miner ID {miner_id} (Matched by {matched_by}).") # DEBUG - noisy
                      continue 
                 processed_miner_ids.add(miner_id)
                 
                 # ... (Rest of status/state logic for known miners is unchanged) ...
                 status = miner_info['status']; state_msg = miner_info['state']; display_status = "Unknown"
                 last_seen_dt = None
                 if miner_info['last_seen']:
                     try:
                         if '+' not in miner_info['last_seen'] and 'Z' not in miner_info['last_seen']: dt_naive = datetime.fromisoformat(miner_info['last_seen']); last_seen_dt = dt_naive.replace(tzinfo=UTC)
                         else: last_seen_dt = datetime.fromisoformat(miner_info['last_seen'].replace('Z', '+00:00'))
                     except ValueError: print(f"Warning: Could not parse last_seen for miner {miner_info['miner_id']}")
                 stale_cutoff = datetime.now(UTC) - timedelta(minutes=STALE_THRESHOLD_MINUTES)
                 if status == 'Active':
                     if last_seen_dt and last_seen_dt >= stale_cutoff: display_status = "Online"; state_msg = state_msg or "Actively Mining"
                     else: display_status = "Stale"; state_msg = f"Last seen {miner_info['last_seen']}" if miner_info['last_seen'] else "Never seen (Stale)"
                 elif status == 'Inactive': display_status = "Inactive"; state_msg = state_msg or "Set to Inactive"
                 elif status == 'Offline': display_status = "Connected (DB Offline)"; state_msg = state_msg or "Device connected, DB Offline"
                 else: display_status = status; state_msg = state_msg or f"DB Status: {status}"
                 
                 merged_state.append({
                     'type': 'miner', 'id': miner_id, 'miner_id': miner_info['miner_id'],
                     'port_path': port_key, 'serial_number': serial_key, # Report udev serial
                     'mac_address': miner_info.get('mac_address'), # Report DB MAC
                     'dev_path': device_data['dev_path'], 
                     'status': status, 'state_msg': state_msg, 'display_status': display_status,
                     'pool_url': miner_info['pool_url'], 'wallet_address': miner_info['wallet_address'],
                     'version': miner_info['nerdminer_vrs'], 'last_seen': miner_info['last_seen'],
                     'location_notes': miner_info['location_notes'], 'chipset': miner_info['chipset']
                 })

            else:
                 # --- Unknown Device (Stray) - Currently Connected ---
                 # Check if this stray exists in the stray_devices table using udev key
                 stray_info = strays_from_db.get(key) 

                 stray_data = {
                     'type': 'stray', 'id': None, 'miner_id': None,
                     'port_path': port_key, 'serial_number': serial_key, # udev serial
                     'mac_address': None, # Initialize MAC
                     'dev_path': device_data['dev_path'],
                     'status': 'Unknown', 'state_msg': 'Detected - Not in DB', 'display_status': "Unconfigured",
                     'vendor_id': device_data['vendor_id'], 'product_id': device_data['product_id'],
                     'pool_url': None, 'wallet_address': None, 'version': None, 'chipset': None
                  }
                 if stray_info:
                      # print(f"[Dog] Merging captured data for stray device {key}...") # Debug - noisy
                      stray_data['pool_url'] = stray_info.get('dumped_pool_url')
                      stray_data['wallet_address'] = stray_info.get('dumped_wallet_address')
                      stray_data['version'] = stray_info.get('dumped_firmware_version')
                      stray_data['chipset'] = stray_info.get('chipset')
                      stray_data['mac_address'] = stray_info.get('mac_address') # Get MAC from stray table
                      
                      stray_data['status'] = stray_info.get('status', 'Unknown') 
                      stray_data['state_msg'] = stray_info.get('state', 'Detected - In Stray Table')
                      if 'captured' in stray_data['state_msg'].lower(): stray_data['display_status'] = "Unconfigured (Captured)"
                      elif 'error' in stray_data['state_msg'].lower() or 'failed' in stray_data['state_msg'].lower(): stray_data['display_status'] = "Capture Failed"
                      else: stray_data['display_status'] = "Unconfigured"

                 merged_state.append(stray_data)


        # Iterate through DB miners to find any not currently connected
        # Use only the serial map keys for this check, as MAC map is only useful for connected devices
        for key, miner_info in miners_from_db_serial.items():
             miner_id = miner_info['id']
             # Check if this miner was already processed (because it was connected and matched)
             if miner_id not in processed_miner_ids:
                 # --- Known Miner - Not Currently Connected ---
                 processed_miner_ids.add(miner_id) # Mark as processed
                 merged_state.append({
                     'type': 'miner', 'id': miner_info['id'], 'miner_id': miner_info['miner_id'],
                     'port_path': miner_info['port_path'], 'serial_number': miner_info['attrs_serial'], # Report original USB serial
                     'mac_address': miner_info.get('mac_address'), # Report MAC
                     'dev_path': None, 
                     'status': 'Offline', 'state_msg': f"Disconnected (Last seen: {miner_info['last_seen'] or 'Never'})",
                     'display_status': "Offline", 'pool_url': miner_info['pool_url'],
                     'wallet_address': miner_info['wallet_address'], 'version': miner_info['nerdminer_vrs'],
                     'last_seen': miner_info['last_seen'], 'location_notes': miner_info['location_notes'],
                     'chipset': miner_info['chipset']
                 })


        # 4. Write to JSON file 
        # ... (write logic unchanged) ...
        try:
            temp_output_file = OUTPUT_FILE + ".tmp"
            output_data = merged_state
            if current_error:
                output_data = {"error": current_error, "devices": merged_state}
                print(f"WARNING: Writing state file with error: {current_error}")

            with open(temp_output_file, 'w') as f: json.dump(output_data, f, indent=2) 
            os.replace(temp_output_file, OUTPUT_FILE) 
        except IOError as e: print(f"ERROR: Could not write to output file {OUTPUT_FILE}: {e}"); current_error = f"File Write Error: {e}"; error_state = "File Write Error"
        except Exception as e: print(f"Unexpected error writing JSON: {e}"); current_error = f"JSON Write Error: {e}"; error_state = "JSON Write Error"


        # 5. Sleep 
        # ... (sleep logic unchanged) ...
        elapsed_time = time.time() - start_time
        sleep_time = max(0, POLL_INTERVAL_SECONDS - elapsed_time)
        time.sleep(sleep_time)


if __name__ == "__main__":
    monitor_and_update()

