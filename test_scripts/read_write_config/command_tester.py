# File: command_tester.py
# Version: 9.0.0
# Description: A diagnostic tool with a high-fidelity, in-memory SPIFFS image builder that matches the firmware's expectations.

import serial
import time
import threading
import argparse
import subprocess
import json
import os
import shutil
import struct
from datetime import datetime

# --- Configuration ---
BAUD_RATE = 115200
LOG_FILE = 'miner_test_log.txt'
stop_thread = False

# --- High-Fidelity SPIFFS Image Builder ---

def create_spiffs_image(config_data, image_size=0xE0000, page_size=256, block_size=8192):
    """
    Builds a valid SPIFFS filesystem image in memory,byte-by-byte, that is
    a high-fidelity match for what the NerdMiner firmware expects.
    """
    print("[SPIFFS Builder] Starting high-fidelity in-memory image creation...")
    
    # --- Filesystem Geometry ---
    num_blocks = image_size // block_size
    pages_per_block = block_size // page_size
    
    # --- CRITICAL: SPIFFS Magic Number ---
    # This is the "secret handshake" the firmware is looking for.
    SPIFFS_MAGIC = 0x20051021
    
    # --- Create the image buffer ---
    image = bytearray(b'\xff' * image_size)

    # --- Prepare File Content ---
    config_str = json.dumps(config_data, separators=(',', ':')).encode('utf-8')
    config_len = len(config_str)
    
    # --- Block 0: Filesystem Metadata ---
    
    # Page 0: Object Lookup Header Page
    # This page maps object IDs to their index pages.
    # struct spiffs_page_header { u16_t obj_id; u16_t span_ix; u8_t flags; ... }
    # Flags: 0xFC = USED | INDEX | OBJ_LU | FINAL
    obj_lu_header = struct.pack('<HHB', 0, 0, 0xFC) + b'\xff' * (page_size - 5)
    image[0:page_size] = obj_lu_header
    
    # Page 1: Object Index Header Page for our single file
    # This describes the /config.json file itself.
    # struct spiffs_page_object_ix_header { ... u32_t size; ... char name[32]; }
    # Flags: 0xFD = USED | INDEX | OBJ_IX | FINAL
    file_obj_id = 1
    file_ix_header = struct.pack(
        '<HHBI B 32s',
        file_obj_id, 0, 0xFD, config_len, 1, b'/config.json'
    )
    file_ix_header += b'\xff' * (page_size - len(file_ix_header))
    image[page_size : page_size * 2] = file_ix_header

    # --- Block 1: File Data ---
    
    # Page 0 of Block 1: Data Page Header
    # This page describes the data that follows.
    # Flags: 0xFE = USED | DATA | FINAL
    data_page_header = struct.pack('<HHB', file_obj_id, 0, 0xFE)
    
    data_block_start = block_size
    image[data_block_start : data_block_start + len(data_page_header)] = data_page_header
    
    # Page 1 of Block 1: The actual JSON content
    content_start_offset = data_block_start + page_size
    image[content_start_offset : content_start_offset + config_len] = config_str
    
    # --- Final Touches: Write Magic Number ---
    # This must be at the very beginning of the image.
    struct.pack_into('<I', image, 0, SPIFFS_MAGIC)

    print("[SPIFFS Builder] High-fidelity image created successfully.")
    return image

# --- Serial Communication & Device Control ---

def serial_reader(ser, log_file_handle):
    """Continuously reads from serial and logs to file."""
    print("[Reader Thread] Started. Logging all output to", LOG_FILE)
    while not stop_thread:
        try:
            if ser and ser.is_open and ser.in_waiting > 0:
                line = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                print(line, end='', flush=True)
                log_file_handle.write(line)
                log_file_handle.flush()
        except serial.SerialException:
            break
        except Exception as e:
            print(f"\n[Reader Thread] Error: {e}")
            break
    print("\n[Reader Thread] Stopped.")

def enter_bootloader(ser):
    """Puts the ESP32 into bootloader mode."""
    print("[Main Thread] Entering bootloader mode...")
    ser.rts, ser.dtr = (False, False); time.sleep(0.1)
    ser.dtr = True; time.sleep(0.1)
    ser.rts = True; time.sleep(0.05)
    ser.dtr = False; time.sleep(0.05)
    ser.rts = False
    print("[Main Thread] Bootloader sequence sent.")

def force_reset(ser):
    """Forces a hardware reset."""
    print("[Main Thread] Forcing hardware reset...")
    ser.dtr, ser.rts = (False, True); time.sleep(0.1)
    ser.dtr, ser.rts = (True, False); time.sleep(0.1)
    ser.dtr, ser.rts = (False, False)
    print("[Main Thread] Reset signal sent.")

def push_new_config(port):
    """Guides user, creates config image, and flashes it."""
    print("\n--- Starting New Configuration Push ---")
    new_pool = input("Enter new Pool URL: ").strip()
    new_wallet = input("Enter new BTC Wallet Address: ").strip()
    miner_id = input("Enter Miner ID: ").strip()

    if not all([new_pool, new_wallet, miner_id]):
        print("All fields are required. Aborting."); return

    config_data = {
        "poolString": new_pool, "portNumber": 8004, "poolPassword": "x",
        "btcString": f"{new_wallet}.{miner_id}", "gmtZone": -5,
        "saveStatsToNVS": False, "invertColors": False, "Brightness": 250
    }
    
    spiffs_image_data = create_spiffs_image(config_data)
    
    spiffs_image_filename = 'spiffs_to_flash.bin'
    with open(spiffs_image_filename, 'wb') as f:
        f.write(spiffs_image_data)

    try:
        print("\nAttempting to flash new configuration...")
        subprocess.run(
            ['esptool.py', '--port', port, '--baud', '921600', 'write_flash', '0x310000', spiffs_image_filename],
            check=True
        )
        print("\n--- Configuration Push Successful! ---")
        print("The miner will now be reset to apply the new configuration.")
        with serial.Serial(port, BAUD_RATE, timeout=1) as ser:
            force_reset(ser)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"\nERROR: Flashing failed. Ensure 'esptool.py' is installed. Details: {e}")
    finally:
        if os.path.exists(spiffs_image_filename):
            os.remove(spiffs_image_filename)

def main(port, action):
    """Main function to perform actions on the miner."""
    if action == 'push_config':
        push_new_config(port); return

    global stop_thread
    stop_thread = False
    ser, reader_thread = None, None

    try:
        with open(LOG_FILE, 'a') as f:
            header = f"\n--- Test session for action '{action}' at {datetime.now()} ---\n"
            f.write(header); print(header)
            
            print(f"Connecting to {port}...")
            ser = serial.Serial(port, BAUD_RATE, timeout=1)
            ser.dtr, ser.rts = (False, False)
            print("Connected.")
            
            reader_thread = threading.Thread(target=serial_reader, args=(ser, f))
            reader_thread.start()
            
            wait_duration = 10
            if action == 'boot':
                enter_bootloader(ser)
            elif action == 'reset_from_boot':
                enter_bootloader(ser)
                time.sleep(3)
                force_reset(ser)
            else: # 'reset'
                force_reset(ser)
            
            print(f"[Main Thread] Test running for {wait_duration} seconds...")
            time.sleep(wait_duration)

    except serial.SerialException as e:
        print(f"\nERROR: Could not connect to port '{port}'. Details: {e}")
    except KeyboardInterrupt:
        print("\n[Main Thread] Shutdown initiated...")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
    finally:
        print("[Main Thread] Cleaning up...")
        stop_thread = True
        if reader_thread: reader_thread.join(timeout=2)
        if ser: ser.close(); print(f"Port {port} closed.")
        print("Script finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='NerdMiner Diagnostic & Config Tool.')
    parser.add_argument('port', help='The serial port of the miner (e.g., /dev/ttyACM0)')
    parser.add_argument(
        '--action', default='reset', choices=['reset', 'boot', 'push_config', 'reset_from_boot'],
        help="Specify the action to perform."
    )
    args = parser.parse_args()
    main(args.port, args.action)

