# File: quick_device_sniffer.py
# Description: A standalone diagnostic script to test the new device discovery logic.
# This script monitors for a new USB TTY device, prints its dmesg-style
# attributes, and then captures the first 30 seconds of its serial output.

import pyudev
import serial
import time
import threading
from datetime import datetime, timedelta

def capture_serial_data(dev_path, duration=30):
    """
    Opens a serial port and prints all output for a specified duration.
    """
    print(f"[Serial] Attempting to open port: {dev_path} at 115200 baud...")
    ser = None
    
    start_time = datetime.now()
    end_time = start_time + timedelta(seconds=duration)
    
    try:
        ser = serial.Serial(dev_path, 115200, timeout=0.1)
        print(f"[Serial] Successfully opened {dev_path}. Capturing output...")
        
        while datetime.now() < end_time:
            try:
                line = ser.readline()
                if line:
                    print(line.decode('utf-8', errors='ignore').strip())
            except serial.SerialException as e:
                print(f"[Serial] Error during read: {e}. Port may have closed.")
                break
            except Exception as e:
                print(f"[Serial] Unexpected read error: {e}")
        
        print(f"\n[Serial] Capture complete after {duration} seconds.")
        
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
    """
    print("--- Shepherd Device Sniffer ---")
    print("Waiting for a new USB serial device to be plugged in...")
    
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='tty')

    try:
        for device in iter(monitor.poll, None):
            # We only care about new devices being *added*
            if device.action == 'add':
                
                # We'll use ID_SERIAL_SHORT as the key, just like in our plan.
                # This filters out non-miner serial devices.
                serial_num = device.get('ID_SERIAL_SHORT')
                if serial_num:
                    dev_path = device.device_node
                    print("\n" + "="*40)
                    print(f"--- New Device Detected! ---")
                    print(f"Timestamp: {datetime.now()}")
                    
                    print("\n[udev] Hardware Attributes:")
                    print(f"  TTY Path (dev_path):     {dev_path}")
                    print(f"  Physical Port (port_path): {device.device_path}") # This is the long physical path
                    print(f"  Vendor ID:               {device.get('ID_VENDOR_ID')}")
                    print(f"  Product ID:              {device.get('ID_MODEL_ID')}")
                    print(f"  Serial Number:           {serial_num}")

                    # Give the OS a brief moment to settle before we
                    # try to grab the serial port.
                    print("\n[Main] Waiting 1.5 seconds for device to initialize...")
                    time.sleep(1.5)

                    # Start the 30-second capture
                    capture_serial_data(dev_path, 30)
                    
                    print("="*40)
                    print("\nMonitoring for next device...")

    except KeyboardInterrupt:
        print("\n[Main] Shutdown signal received. Exiting.")
    except Exception as e:
        print(f"\n[Main] An unexpected error occurred: {e}")
    finally:
        print("--- Sniffer Stopped ---")

if __name__ == "__main__":
    main()
