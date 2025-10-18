# device_discovery.py
# Version: 0.0.0.3
# Description: A standalone service to monitor for new USB serial devices.

import pyudev
import time
import os
import sqlite3
from datetime import datetime, UTC

# --- Configuration ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
DATABASE_FILE = os.path.join(DATA_DIR, 'shepherd.db')

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def add_unconfigured_device(device, conn):
    """Adds a newly discovered device to the unconfigured_devices table."""
    dev_path = device.device_node
    # DEVPATH provides the physical path, e.g., /devices/platform/scb/fd500000.pcie/pci0000:00/0000:00:00.0/0000:01:00.0/usb1/1-1/1-1.2/1-1.2:1.0/tty/ttyACM0
    # We want to extract the USB bus path, which is typically the part like '1-1.2'
    try:
        devpath_parts = device.device_path.split('/')
        usb_part = [part for part in devpath_parts if '-' in part and ':' not in part][-1]
    except IndexError:
        usb_part = None # Fallback if path format is unexpected
        
    serial = device.get('ID_SERIAL_SHORT', 'UNKNOWN')
    
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM miners WHERE dev_path = ? OR port_path = ?", (dev_path, usb_part))
    if cursor.fetchone() and usb_part is not None:
        print(f"Device at {dev_path} (Port: {usb_part}) is already configured. Ignoring.")
        return

    print(f"New unconfigured device found: {dev_path} (Port: {usb_part}, Serial: {serial})")
    try:
        with conn:
            # Add port_path to the INSERT statement
            conn.execute("""
                INSERT INTO unconfigured_devices (dev_path, port_path, vendor_id, product_id, serial_number, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(dev_path) DO NOTHING;
            """, (
                dev_path,
                usb_part,
                device.get('ID_VENDOR_ID', ''),
                device.get('ID_MODEL_ID', ''),
                serial,
                datetime.now(UTC).isoformat()
            ))
    except Exception as e:
        print(f"Error adding device to database: {e}")


def main():
    """Monitors udev for new ttyUSB or ttyACM devices."""
    print("Starting Shepherd Device Discovery Service...")
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='tty')
    
    try:
        with get_db_connection() as conn:
            print("Performing initial scan of connected devices...")
            for device in context.list_devices(subsystem='tty'):
                 if 'ID_SERIAL_SHORT' in device:
                    add_unconfigured_device(device, conn)
    except Exception as e:
        print(f"Error during initial device scan: {e}")

    print("Monitoring for new USB device events...")
    for device in iter(monitor.poll, None):
        if device.action == 'add' and 'ID_SERIAL_SHORT' in device:
            try:
                with get_db_connection() as conn:
                    add_unconfigured_device(device, conn)
            except Exception as e:
                print(f"Error processing device event: {e}")

if __name__ == "__main__":
    main()

