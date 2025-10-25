# File: quick_device_sniffer.py
# Description: A standalone diagnostic script to test the new device discovery logic.
# This script monitors for a new USB TTY device, prints its dmesg-style
# attributes, captures/parses its boot-up log, and then tracks its
# connection-to-pool state, logging ALL serial output.
# This version exits after capturing one device to allow for parallel testing.

import pyudev
import serial
import time
import threading
import re
import json
from datetime import datetime, timedelta

def capture_and_log_serial(dev_path, serial_num, duration_minutes=30):
    """
    Opens a serial port, captures output, logs all data to a file,
    and tracks the key connection-to-pool events.
    """
    print(f"[Serial] Attempting to open port: {dev_path} at 115200 baud...")
    ser = None
    
    # --- Time & State Variables ---
    max_end_time = datetime.now() + timedelta(minutes=duration_minutes)
    
    # --- Log File Setup ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"sniffer_log_{serial_num.replace(':', '')}_{timestamp}.log"
    print(f"[Main] Logging ALL serial data to: {log_filename}")

    # --- Data to find (for initial console summary) ---
    json_buffer = ""
    parsed_config = None
    found_ip = None
    parsing_state = "SCANNING" # States: SCANNING, IN_JSON
    
    # --- NEW: Connection State Tracking ---
    seen_initiating_tasks = False
    seen_worker_started = False
    seen_miner_hw_task = False
    seen_connected_ip = False
    seen_dns_resolved = False
    seen_mining_subscribe = False
    seen_mining_authorize = False
    
    # --- RegEx Patterns ---
    ip_regex = re.compile(r"\*wm:STA IP Address: (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
    
    try:
        ser = serial.Serial(dev_path, 115200, timeout=0.1)
        print(f"[Serial] Successfully opened {dev_path}. Capturing and parsing output...")
        
        with open(log_filename, 'a', encoding='utf-8') as log_file:
            log_file.write(f"# Shepherd Sniffer Log for {serial_num} at {datetime.now()}\n")
            log_file.write(f"# Monitoring port {dev_path}\n")
            log_file.write(f"#" + "="*40 + "\n\n")

            while datetime.now() < max_end_time:
                try:
                    line_bytes = ser.readline()
                    if not line_bytes:
                        continue
                        
                    line = line_bytes.decode('utf-8', errors='ignore').strip()
                    
                    # --- 2. Continuous Logging (to file) ---
                    # Log ALL non-empty lines, no matter what
                    if line:
                        log_file.write(f"[{datetime.now().isoformat()}] {line}\n")
                    else:
                        continue # Skip empty lines
                    
                    # --- 1. Initial Summary Parsing (for console) ---
                    # State Machine for JSON parsing (only runs once)
                    if parsing_state == "SCANNING" and line == "{":
                        parsing_state = "IN_JSON"
                        json_buffer = "{"
                    elif parsing_state == "IN_JSON":
                        json_buffer += line
                        if line == "}":
                            parsing_state = "PARSED_JSON" # Stop parsing for JSON
                            try:
                                parsed_config = json.loads(json_buffer)
                                print("\n" + "="*20 + " INITIAL PARSED DATA " + "="*20)
                                print("[Parser] Successfully parsed config JSON (see console).")
                                print(json.dumps(parsed_config, indent=2))
                                log_file.write(f"[{datetime.now().isoformat()}] # --- Parsed Config JSON ---\n")
                            except json.JSONDecodeError as e:
                                print(f"[Parser] FAILED to parse JSON: {e}")
                                log_file.write(f"[{datetime.now().isoformat()}] # FAILED to parse JSON: {e}\n")
                    
                    # RegEx for IP Address (only runs once)
                    if not found_ip:
                        ip_match = ip_regex.search(line)
                        if ip_match:
                            found_ip = ip_match.group(1)
                            print(f"[Parser] Found IP Address: {found_ip}")
                            print("="*61 + "\n")
                            log_file.write(f"[{datetime.now().isoformat()}] # --- Found IP Address: {found_ip} ---\n")

                    # --- 3. NEW: Connection State Tracking ---
                    # This state machine runs in order and flags key events
                    
                    if not seen_initiating_tasks and "Initiating tasks..." in line:
                        seen_initiating_tasks = True
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Monitor] Found: Initiating tasks...")
                        log_file.write(f"[{datetime.now().isoformat()}] # --- Found: Initiating tasks... ---\n")
                    
                    elif seen_initiating_tasks and not seen_worker_started and "[WORKER] Started. Running (Stratum)" in line:
                        seen_worker_started = True
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Monitor] Found: WORKER Started")
                        log_file.write(f"[{datetime.now().isoformat()}] # --- Found: WORKER Started ---\n")
                    
                    elif seen_worker_started and not seen_miner_hw_task and "[MINER] 0 Started minerWorkerHw Task!" in line:
                        seen_miner_hw_task = True
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Monitor] Found: MINER HW Task Started")
                        log_file.write(f"[{datetime.now().isoformat()}] # --- Found: MINER HW Task Started ---\n")
                    
                    elif seen_miner_hw_task and not seen_connected_ip and "CONNECTED - Current ip:" in line:
                        seen_connected_ip = True
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Monitor] Found: CONNECTED IP")
                        log_file.write(f"[{datetime.now().isoformat()}] # --- Found: CONNECTED IP ---\n")
                    
                    elif seen_connected_ip and not seen_dns_resolved and "Resolved DNS and save ip" in line:
                        seen_dns_resolved = True
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Monitor] Found: DNS Resolved")
                        log_file.write(f"[{datetime.now().isoformat()}] # --- Found: DNS Resolved ---\n")
                    
                    elif seen_dns_resolved and not seen_mining_subscribe and "[WORKER] ==> Mining subscribe" in line:
                        seen_mining_subscribe = True
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Monitor] Found: Mining Subscribe")
                        log_file.write(f"[{datetime.now().isoformat()}] # --- Found: Mining Subscribe ---\n")
                    
                    elif seen_mining_subscribe and not seen_mining_authorize and "[WORKER] ==> Autorize work" in line:
                        seen_mining_authorize = True
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Monitor] Found: Mining Authorize")
                        log_file.write(f"[{datetime.now().isoformat()}] # --- Found: Mining Authorize ---\n")
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Monitor] Full connection sequence captured.")

                except serial.SerialException as e:
                    print(f"[Serial] Error during read: {e}. Port may have closed.")
                    log_file.write(f"[{datetime.now().isoformat()}] # ERROR: SerialException: {e}\n")
                    break
                except Exception as e:
                    print(f"[Serial] Unexpected read error: {e}")
                    log_file.write(f"[{datetime.now().isoformat()}] # ERROR: Unexpected: {e}\n")
        
        # --- 4. Final Summary (Console) ---
        print(f"\n[Serial] Capture complete.")
        
        print("\n" + "="*20 + " CAPTURE SUMMARY " + "="*20)
        print(f"  Log File:   {log_filename}")
        print(f"  Status:     Capture timed out after {duration_minutes} minutes.")
        print("\n  --- Connection Events Captured ---")
        print(f"  1. Initiating Tasks:   {'FOUND' if seen_initiating_tasks else 'NOT FOUND'}")
        print(f"  2. Worker Started:     {'FOUND' if seen_worker_started else 'NOT FOUND'}")
        print(f"  3. Miner HW Task:      {'FOUND' if seen_miner_hw_task else 'NOT FOUND'}")
        print(f"  4. Connected IP:       {'FOUND' if seen_connected_ip else 'NOT FOUND'}")
        print(f"  5. DNS Resolved:       {'FOUND' if seen_dns_resolved else 'NOT FOUND'}")
        print(f"  6. Mining Subscribe:   {'FOUND' if seen_mining_subscribe else 'NOT FOUND'}")
        print(f"  7. Mining Authorize:   {'FOUND' if seen_mining_authorize else 'NOT FOUND'}")
        print("="*60)
        
    except serial.SerialException as e:
        print(f"[Serial] FAILED to open port {dev_path}. Error: {e}")
        print("[Serial] Is the device busy or does the user have permissions (check 'dialout' group)?")
    except Exception as e:
        print(f"[Serial] An unexpected error occurred: {e}")
    finally:
        if ser and ser.is_open:
            ser.close()
            print(f"[Serial] Port {dev_path} closed.")

def main():
    """
    Monitors udev for new ttyUSB or ttyACM devices and triggers data capture.
    This version exits after one device is processed.
    """
    print("--- Shepherd Device Logger (v6 - Connection State) ---")
    print("Waiting for a new USB serial device to be plugged in...")
    
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='tty')

    try:
        for device in iter(monitor.poll, None):
            if device.action == 'add':
                serial_num = device.get('ID_SERIAL_SHORT')
                if serial_num:
                    dev_path = device.device_node
                    print("\n" + "="*40)
                    print(f"--- New Device Detected! ---")
                    print(f"Timestamp: {datetime.now()}")
                    
                    print("\n[udev] Hardware Attributes:")
                    print(f"  TTY Path (dev_path):     {dev_path}")
                    
                    port_path = "N/A"
                    try:
                        parts = device.device_path.split('/')
                        port_path = [p for p in parts if '-' in p and ':' not in p][-1]
                    except Exception:
                        port_path = device.device_path
                        
                    print(f"  Physical Port (port_path): {port_path}")
                    print(f"  Vendor ID:               {device.get('ID_VENDOR_ID')}")
                    print(f"  Product ID:              {device.get('ID_MODEL_ID')}")
                    print(f"  Serial Number:           {serial_num}")

                    print("\n[Main] Waiting 1.5 seconds for device to initialize...")
                    time.sleep(1.5)

                    # Start the long-term capture and logging
                    # We pass serial_num to create the unique log file
                    capture_and_log_serial(dev_path, serial_num)
                    
                    print("="*40)
                    print("\n[Main] Capture for this device finished. Script will now exit.")
                    break # NEW: Exit loop after handling one device

    except KeyboardInterrupt:
        print("\n[Main] Shutdown signal received. Exiting.")
    except Exception as e:
        print(f"\n[Main] An unexpected error occurred: {e}")
    finally:
        print("--- Logger Stopped ---")

if __name__ == "__main__":
    main()

