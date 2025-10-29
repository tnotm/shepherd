# shepherds_dog.py
# Version: 0.0.2.4
# Description: Monitors USB devices and miner statuses, writing results to JSON.
# CHANGED: Refactored into a class to manage state.
# CHANGED: Now manages and launches MinerMonitor threads for connected miners.
# FIXED: Added missing 'DEBUG_MODE' global variable.
# FIXED: Replaced 'self.name' with 'Dog' for logging.
# FIXED: Corrected TypeError crash when parsing a 'None' last_seen timestamp.
# FIXED (AGAIN): Re-wrote last_seen parsing to be robust against empty strings ('')
# ADDED: Master error handler in main loop to prevent silent crashes.
# ADDED: Granular logging to trace the main loop's progress.

import pyudev
import sqlite3
import json
import time
import os
import threading
import traceback # <-- ADDED FOR BETTER ERROR LOGGING
from datetime import datetime, timedelta, UTC
from shepherd.miner_monitor import MinerMonitor # <-- STEP 2: IMPORT NEW COMPONENT

# --- Configuration ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
DATABASE_FILE = os.path.join(DATA_DIR, 'shepherd.db')
OUTPUT_FILE = os.path.join(DATA_DIR, 'device_state.json')
POLL_INTERVAL_SECONDS = 5 
STALE_THRESHOLD_MINUTES = 5
COMMON_MINER_VENDOR_IDS = {'10c4', '303a', '1a86'}
DEBUG_MODE = False # <-- ADDED MISSING VARIABLE

# --- DB Connection (remains the same) ---
os.makedirs(DATA_DIR, exist_ok=True)
if not os.access(DATA_DIR, os.W_OK): print(f"CRITICAL ERROR: Directory {DATA_DIR} not writable.")
else: print(f"[Permissions] Write access to {DATA_DIR} confirmed.")
def get_db_connection():
    conn = None 
    try:
        conn = sqlite3.connect(DATABASE_FILE, timeout=10); conn.row_factory = sqlite3.Row
        conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='miners';").fetchone()
        return conn
    except sqlite3.OperationalError as e:
        if "no such table: miners" in str(e): print(f"[DB Connection] WARNING: 'miners' table not found...")
        else: print(f"[DB Connection] ERROR: Database operational error: {e}.")
        if conn: conn.close(); return None 
    except Exception as e:
        print(f"[DB Connection] ERROR: Unexpected error connecting to database: {e}")
        if conn: conn.close(); return None

# --- Main Class ---

class ShepherdsDog:
    """
    Manages device monitoring, state file generation, and
    launches/stops MinerMonitor threads.
    """
    def __init__(self):
        self.last_run_miners_serial = {}
        self.last_run_miners_mac = {}
        self.last_run_strays = {}
        self.error_state = None
        self.active_monitors = {} # <-- STEP 2: STATE TO HOLD THREADS

    def get_miner_details(self, conn):
        """Fetches essential details for all configured miners."""
        try:
            miners = conn.execute("""
                SELECT id, miner_id, port_path, attrs_serial, mac_address, status, state, 
                       pool_url, wallet_address, nerdminer_vrs, last_seen, location_notes, chipset
                FROM miners;
            """).fetchall()
            
            miner_map_serial = {}
            miner_map_mac = {}
            
            for m in miners:
                miner_dict = dict(m)
                key_serial = miner_dict['attrs_serial'] 
                key_port = miner_dict['port_path']
                if key_port and key_serial: 
                    miner_map_serial[(key_port, key_serial)] = miner_dict
                
                key_mac = miner_dict['mac_address']
                if key_mac:
                     if key_mac in miner_map_mac:
                          print(f"[Dog] WARNING: Duplicate MAC address '{key_mac}' found.")
                     miner_map_mac[key_mac] = miner_dict

            # print(f"[Dog] Found {len(miner_map_serial)} miners by Serial, {len(miner_map_mac)} by MAC.") # Debug
            return miner_map_serial, miner_map_mac 
        except sqlite3.Error as e:
            print(f"Database error fetching miners: {e}")
            return {}, {}

    def get_stray_details(self, conn):
        """Fetches details for all devices currently in the stray_devices table."""
        try:
            strays = conn.execute("""
                SELECT port_path, serial_number, mac_address, chipset, status, state, 
                       dumped_pool_url, dumped_wallet_address, dumped_firmware_version
                FROM stray_devices; 
            """).fetchall()
            stray_map = {
                (s['port_path'], s['serial_number']): dict(s) 
                for s in strays if s['port_path'] and s['serial_number']
            }
            return stray_map
        except sqlite3.Error as e:
            print(f"Database error fetching stray devices: {e}")
            return {}

    def get_connected_devices(self):
        """
        Gets a list of currently connected USB TTY devices by iterating all devices.
        V.1.0.1: Relaxed filtering to be more permissive.
        """
        context = pyudev.Context()
        devices = []
        if DEBUG_MODE:
            print(f"[Dog] Starting full device scan...") # <-- FIXED self.name

        try:
            for device in context.list_devices(subsystem='tty'):
                devname = device.properties.get('DEVNAME')
                
                # Basic filter: must be a TTY device
                if not devname or not (devname.startswith('/dev/ttyACM') or devname.startswith('/dev/ttyUSB')):
                    continue
                    
                # Find its 'usb_device' parent
                usb_device = None
                try:
                    usb_device = device.find_parent('usb', 'usb_device')
                    if not usb_device:
                        if DEBUG_MODE: print(f"[Dog]   Found {devname}, but no usb_device parent. Skipping.") # <-- FIXED self.name
                        continue
                except Exception:
                    continue # Not a USB TTY device
                
                # --- NEW PERMISSIVE LOGIC ---

                # 1. Get Physical Port Path (This is critical)
                port_path = "Unknown"
                try:
                    devpath_parts = usb_device.device_path.split('/')
                    # Find the physical USB port ID (e.g., '1-1.2', '1-1.3')
                    usb_part = next((part for part in reversed(devpath_parts) if '-' in part and ':' not in part), None)
                    if usb_part:
                        port_path = usb_part
                except Exception:
                    pass # Keep port_path as "Unknown"

                if port_path == "Unknown":
                    if DEBUG_MODE: print(f"[Dog]   Found {devname}, but could not determine port_path. Skipping.") # <-- FIXED self.name
                    continue # We MUST have a port path to use as a key

                # 2. Get Serial Number (This is optional)
                serial_num = usb_device.properties.get('ID_SERIAL_SHORT')
                vendor_id = usb_device.properties.get('ID_VENDOR_ID')
                product_id = usb_device.properties.get('ID_MODEL_ID')

                # If no serial, create a robust placeholder using the port path
                if not serial_num:
                    serial_num = f"PORT_{port_path}_VID_{vendor_id}"
                    if DEBUG_MODE: print(f"[Dog]   Found {devname} on port {port_path} with NO SERIAL. Creating placeholder: {serial_num}") # <-- FIXED self.name
                
                # 3. Add the device
                details = {
                    'dev_path': devname,
                    'port_path': port_path,
                    'serial_number': serial_num, # Will be the real serial or our placeholder
                    'vendor_id': vendor_id,
                    'product_id': product_id
                }
                
                device_key = (details['port_path'], details['serial_number'])
                # Check for duplicates (should be rare with new key)
                if device_key not in [(d['port_path'], d['serial_number']) for d in devices]:
                    devices.append(details)
                    if DEBUG_MODE: print(f"[Dog]   Found valid device: {details}") # <-- FIXED self.name

        except Exception as e:
            print(f"[Dog][udev] ERROR during full device scan: {e}");
        return devices

    def run(self):
        """Main loop to check devices, query DB, and write status file."""
        print("Starting Shepherd's Dog monitoring loop (V.0.0.2.4 - Armored)...")

        while True:
            # --- START OF MASTER ERROR HANDLER ---
            try:
                start_time = time.time()
                print(f"\n[Dog] --- Loop Start ({datetime.now(UTC).isoformat()}) ---") # <-- LOGGING
                merged_state = [] 
                current_error = None 

                # 1. Get currently connected devices
                print("[Dog] ...starting device scan.") # <-- LOGGING
                connected_devices = self.get_connected_devices()
                connected_map = {(d['port_path'], d['serial_number']): d for d in connected_devices if d['port_path'] != 'Unknown' and d['serial_number']} 
                print(f"[Dog] ...scan complete, found {len(connected_map)} devices.") # <-- LOGGING

                # 2. Get miner and stray details from DB
                print("[Dog] ...querying database.") # <-- LOGGING
                miners_from_db_serial = {}
                miners_from_db_mac = {}
                strays_from_db = {} 
                db_conn = get_db_connection() 
                if db_conn:
                    try:
                        miners_from_db_serial, miners_from_db_mac = self.get_miner_details(db_conn)
                        strays_from_db = self.get_stray_details(db_conn) 
                        self.last_run_miners_serial = miners_from_db_serial
                        self.last_run_miners_mac = miners_from_db_mac
                        self.last_run_strays = strays_from_db 
                        if self.error_state == "DB Error": print("[Dog] Database connection restored."); self.error_state = None
                        print(f"[Dog] ...DB query complete. Found {len(miners_from_db_serial)} miners, {len(strays_from_db)} strays.") # <-- LOGGING
                    except Exception as e: 
                        print(f"ERROR: Exception during DB queries: {e}")
                        current_error = f"DB Query Error: {e}"
                        miners_from_db_serial = self.last_run_miners_serial
                        miners_from_db_mac = self.last_run_miners_mac
                        strays_from_db = self.last_run_strays 
                    finally:
                        db_conn.close() 
                else:
                    print("ERROR: Failed to establish DB connection. Using cached lists.")
                    current_error = "DB Connection Error"
                    miners_from_db_serial = self.last_run_miners_serial
                    miners_from_db_mac = self.last_run_miners_mac
                    strays_from_db = self.last_run_strays 
                    self.error_state = "DB Error" 

                # 3. Merge and determine status
                print("[Dog] ...starting device/DB merge logic.") # <-- LOGGING
                processed_miner_ids = set() 

                # Iterate through connected devices 
                for key, device_data in connected_map.items():
                    port_key = key[0]; serial_key = key[1]
                    miner_info = None; matched_by = None

                    # --- Matching Logic (unchanged) ---
                    miner_info = miners_from_db_serial.get(key)
                    if miner_info:
                         matched_by = "Serial Key"
                    if not miner_info:
                         stray_info_for_mac_check = strays_from_db.get(key) 
                         potential_mac = stray_info_for_mac_check.get('mac_address') if stray_info_for_mac_check else None
                         if potential_mac:
                              miner_info = miners_from_db_mac.get(potential_mac)
                              if miner_info:
                                   if miner_info.get('port_path') == port_key:
                                        matched_by = "MAC Key (via Stray)"
                                   else:
                                        print(f"[Dog] WARNING: MAC '{potential_mac}' match ignored (port mismatch).")
                                        miner_info = None
                    
                    # --- Process based on Match ---
                    if miner_info:
                         # --- Known Miner - Currently Connected ---
                         miner_id = miner_info['id']
                         if miner_id in processed_miner_ids: continue 
                         processed_miner_ids.add(miner_id)
                         
                         # --- ** STEP 2: MONITOR LAUNCH LOGIC ** ---
                         if miner_id not in self.active_monitors:
                             print(f"[Dog] Detected connection for {miner_info['miner_id']}. Starting monitor thread.")
                             try:
                                 monitor_thread = MinerMonitor(
                                     miner_db_id=miner_id,
                                     dev_path=device_data['dev_path'],
                                     miner_id_str=miner_info['miner_id']
                                 )
                                 monitor_thread.start()
                                 self.active_monitors[miner_id] = monitor_thread
                             except Exception as e:
                                 print(f"[Dog] ERROR: Failed to start MinerMonitor for {miner_id}: {e}")
                         # --- ** END STEP 2 LOGIC ** ---
                         
                         # ... (Rest of status/state logic for known miners is unchanged) ...
                         status = miner_info['status']; state_msg = miner_info['state']; display_status = "Unknown"
                         last_seen_dt = None
                         
                         # --- ROBUST FIX V2: Handle None, '', and bad data ---
                         current_last_seen = miner_info['last_seen']
                         if current_last_seen: # Only try to parse if it's not None or ''
                             try:
                                 # Z-aware parsing
                                 if 'Z' in current_last_seen or '+' in current_last_seen:
                                     last_seen_dt = datetime.fromisoformat(current_last_seen.replace('Z', '+00:00'))
                                 # Naive timestamp
                                 else:
                                     dt_naive = datetime.fromisoformat(current_last_seen)
                                     last_seen_dt = dt_naive.replace(tzinfo=UTC)
                             except (ValueError, TypeError) as e: 
                                 print(f"[Dog] WARNING: Could not parse last_seen '{current_last_seen}' for miner {miner_info['miner_id']}: {e}")
                                 pass # Ignore parse error, last_seen_dt remains None
                         # --- END FIX V2 ---

                         stale_cutoff = datetime.now(UTC) - timedelta(minutes=STALE_THRESHOLD_MINUTES)
                         if status == 'Active':
                             if last_seen_dt and last_seen_dt >= stale_cutoff: display_status = "Online"; state_msg = state_msg or "Actively Mining"
                             else: display_status = "Stale"; state_msg = f"Last seen {miner_info['last_seen']}" if miner_info['last_seen'] else "Never seen (Stale)"
                         elif status == 'Inactive': display_status = "Inactive"; state_msg = state_msg or "Set to Inactive"
                         elif status == 'Offline': display_status = "Connected (DB Offline)"; state_msg = state_msg or "Device connected, DB Offline"
                         else: display_status = status; state_msg = state_msg or f"DB Status: {status}"
                         
                         merged_state.append({
                             'type': 'miner', 'id': miner_id, 'miner_id': miner_info['miner_id'],
                             'port_path': port_key, 'serial_number': serial_key, 
                             'mac_address': miner_info.get('mac_address'), 
                             'dev_path': device_data['dev_path'], 
                             'status': status, 'state_msg': state_msg, 'display_status': display_status,
                             'pool_url': miner_info['pool_url'], 'wallet_address': miner_info['wallet_address'],
                             'version': miner_info['nerdminer_vrs'], 'last_seen': miner_info['last_seen'],
                             'location_notes': miner_info['location_notes'], 'chipset': miner_info['chipset']
                         })

                    else:
                         # --- Unknown Device (Stray) - Currently Connected ---
                         stray_info = strays_from_db.get(key) 
                         stray_data = {
                             'type': 'stray', 'id': None, 'miner_id': None,
                             'port_path': port_key, 'serial_number': serial_key, 
                             'mac_address': None, 'dev_path': device_data['dev_path'],
                             'status': 'Unknown', 'state_msg': 'Detected - Not in DB', 'display_status': "Unconfigured",
                             'vendor_id': device_data['vendor_id'], 'product_id': device_data['product_id'],
                             'pool_url': None, 'wallet_address': None, 'version': None, 'chipset': None
                          }
                         if stray_info:
                              stray_data.update({
                                  'pool_url': stray_info.get('dumped_pool_url'),
                                  'wallet_address': stray_info.get('dumped_wallet_address'),
                                  'version': stray_info.get('dumped_firmware_version'),
                                  'chipset': stray_info.get('chipset'),
                                  'mac_address': stray_info.get('mac_address'),
                                  'status': stray_info.get('status', 'Unknown'),
                                  'state_msg': stray_info.get('state', 'Detected - In Stray Table')
                              })
                              if 'captured' in stray_data['state_msg'].lower(): stray_data['display_status'] = "Unconfigured (Captured)"
                              elif 'error' in stray_data['state_msg'].lower() or 'failed' in stray_data['state_msg'].lower(): stray_data['display_status'] = "Capture Failed"
                              else: stray_data['display_status'] = "Unconfigured"
                         merged_state.append(stray_data)

                print("[Dog] ...starting disconnect check.") # <-- LOGGING
                # Iterate through DB miners to find any not currently connected
                for key, miner_info in miners_from_db_serial.items():
                     miner_id = miner_info['id']
                     if miner_id not in processed_miner_ids:
                         # --- Known Miner - Not Currently Connected ---
                         processed_miner_ids.add(miner_id)
                         
                         # --- ** STEP 2: MONITOR STOP LOGIC ** ---
                         if miner_id in self.active_monitors:
                             print(f"[Dog] Detected disconnect for {miner_info['miner_id']}. Stopping monitor thread.")
                             try:
                                 monitor_to_stop = self.active_monitors.pop(miner_id)
                                 monitor_to_stop.stop()
                             except Exception as e:
                                 print(f"[Dog] ERROR: Failed to stop MinerMonitor for {miner_id}: {e}")
                         # --- ** END STEP 2 LOGIC ** ---
                         
                         merged_state.append({
                             'type': 'miner', 'id': miner_info['id'], 'miner_id': miner_info['miner_id'],
                             'port_path': miner_info['port_path'], 'serial_number': miner_info['attrs_serial'], 
                             'mac_address': miner_info.get('mac_address'), 'dev_path': None, 
                             'status': 'Offline', 'state_msg': f"Disconnected (Last seen: {miner_info['last_seen'] or 'Never'})",
                             'display_status': "Offline", 'pool_url': miner_info['pool_url'],
                             'wallet_address': miner_info['wallet_address'], 'version': miner_info['nerdminer_vrs'],
                             'last_seen': miner_info['last_seen'], 'location_notes': miner_info['location_notes'],
                             'chipset': miner_info['chipset']
                         })

                # 4. Write to JSON file 
                print("[Dog] ...merge complete, writing JSON file.") # <-- LOGGING
                try:
                    temp_output_file = OUTPUT_FILE + ".tmp"
                    output_data = merged_state
                    if current_error:
                        output_data = {"error": current_error, "devices": merged_state}
                    with open(temp_output_file, 'w') as f: json.dump(output_data, f, indent=2) 
                    os.replace(temp_output_file, OUTPUT_FILE)
                    print("[Dog] ...JSON write complete.") # <-- LOGGING
                except IOError as e: print(f"ERROR: Could not write to output file {OUTPUT_FILE}: {e}"); current_error = f"File Write Error: {e}"; self.error_state = "File Write Error"
                except Exception as e: print(f"Unexpected error writing JSON: {e}"); current_error = f"JSON Write Error: {e}"; self.error_state = "JSON Write Error"

                # 5. Sleep 
                elapsed_time = time.time() - start_time
                sleep_time = max(0, POLL_INTERVAL_SECONDS - elapsed_time)
                print(f"[Dog] --- Loop End. Elapsed: {elapsed_time:.2f}s, Sleeping: {sleep_time:.2f}s ---") # <-- LOGGING
                time.sleep(sleep_time)
            
            # --- END OF MASTER ERROR HANDLER ---
            except Exception as e:
                print("\n" + "="*60)
                print(f"[Dog] FATAL ERROR IN MAIN LOOP: {e}")
                print("Traceback:")
                traceback.print_exc()
                print("="*60 + "\n")
                print(f"[Dog] Loop crashed. Restarting after {POLL_INTERVAL_SECONDS}s sleep...")
                time.sleep(POLL_INTERVAL_SECONDS) # Sleep even after a crash to prevent spam


    def stop_all_monitors(self):
        """Signals all active monitor threads to stop."""
        print("[Dog] Stopping all active monitor threads...")
        if not self.active_monitors:
            print("[Dog] No monitors were active.")
            return
            
        for miner_id, monitor in list(self.active_monitors.items()):
            print(f"[Dog] ... signaling stop for {monitor.miner_id_str} (ID: {miner_id})")
            try:
                monitor.stop()
                self.active_monitors.pop(miner_id) # Remove from dict
            except Exception as e:
                print(f"[Dog] Error while stopping monitor {miner_id}: {e}")
        
        print("[Dog] All monitors signaled.")


if __name__ == "__main__":
    dog = ShepherdsDog()
    try:
        dog.run()
    except KeyboardInterrupt:
        print("\n[Dog] Shutdown signal received. Cleaning up...")
    except Exception as e:
        print(f"\n[Dog] FATAL ERROR in main loop: {e}")
        import traceback
        traceback.print_exc()
    finally:
        dog.stop_all_monitors()
        print("[Dog] Exiting.")

