# data_ingestor.py
# Version: 0.0.0.5
# Description: Monitors serial ports for ACTIVE miners and logs their output.
# CHANGED: Main logic now periodically checks DB for active miners and manages threads dynamically.
# CHANGED: monitor_miner thread now accepts and checks a stop event.

import serial
import sqlite3
import time
import threading
import queue
import re
import os
from datetime import datetime, timedelta, UTC

# --- Configuration ---
DEBUG_MODE = False
DATA_DIR = os.path.expanduser('~/shepherd_data')
DATABASE_FILE = os.path.join(DATA_DIR, 'shepherd.db')
LOG_RETENTION_MINUTES = 10
CLEANUP_INTERVAL_MINUTES = 10
POLL_ACTIVE_MINERS_INTERVAL_SECONDS = 15 # How often to check DB for active miners

data_queue = queue.Queue()
active_threads = {} # Dictionary to store active monitoring threads {miner_id: {'thread': thread_obj, 'stop_event': event_obj}}

# --- Database Functions ---

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def get_active_miners(conn):
    """Fetches the list of miners currently marked as 'Active'."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, miner_id, dev_path FROM miners WHERE status = 'Active' AND dev_path IS NOT NULL;")
        miners = cursor.fetchall()
        # Return as a dictionary keyed by miner ID for easier lookup
        return {miner['id']: {'miner_id': miner['miner_id'], 'dev_path': miner['dev_path']} for miner in miners}
    except sqlite3.Error as e:
        print(f"Database error fetching active miners: {e}")
        return {} # Return empty dict on error

# --- Worker Threads ---

def monitor_miner(miner_db_id, dev_path, miner_id_str, stop_event):
    """A thread that monitors a serial port and puts data into a queue until stop_event is set."""
    thread_name = threading.current_thread().name
    log_pattern = re.compile(r'>>>\s*(?P<key>.+?):\s*(?P<value>.+)')
    last_status_update = 'unknown' # Track last status sent
    
    print(f"[{thread_name}] Starting monitoring for Miner ID {miner_db_id} ({miner_id_str}) on {dev_path}")

    while not stop_event.is_set():
        ser = None
        try:
            # Try to open the serial port
            ser = serial.Serial(dev_path, 115200, timeout=1)
            print(f"[{thread_name}] Successfully connected to {dev_path}.")
            if last_status_update != 'online':
                data_queue.put(('STATUS', miner_db_id, 'online')) # Update status via queue
                last_status_update = 'online'

            # Read loop while connected and not stopped
            while ser.is_open and not stop_event.is_set():
                try:
                    # Check for stop signal more frequently
                    if stop_event.is_set():
                         print(f"[{thread_name}] Stop signal received while connected.")
                         break

                    line_bytes = ser.readline()
                    if line_bytes:
                         line = line_bytes.decode('utf-8', errors='ignore').strip()
                         if line:
                            if DEBUG_MODE:
                                print(f"[{thread_name}] RAW: {line}")
                            
                            match = log_pattern.match(line)
                            if match:
                                data = match.groupdict()
                                data_queue.put(('LOG', miner_db_id, data['key'], data['value']))
                    # Add a small sleep if readline times out, prevents tight loop on disconnect/idle
                    else:
                         time.sleep(0.1)

                except serial.SerialException:
                    print(f"[{thread_name}] Device {dev_path} disconnected during read. Retrying connection...")
                    if last_status_update != 'offline':
                        data_queue.put(('STATUS', miner_db_id, 'offline'))
                        last_status_update = 'offline'
                    break # Break inner loop to reconnect
                except Exception as e:
                    print(f"[{thread_name}] Error reading from {dev_path}: {e}")
                    time.sleep(1) # Wait before continuing read loop

        except serial.SerialException as e:
            # Only log error if we haven't been told to stop
            if not stop_event.is_set():
                print(f"[{thread_name}] Could not open port {dev_path}: {e}. Retrying in {POLL_ACTIVE_MINERS_INTERVAL_SECONDS}s...")
                if last_status_update != 'offline':
                    data_queue.put(('STATUS', miner_db_id, 'offline'))
                    last_status_update = 'offline'
        except Exception as e:
             if not stop_event.is_set():
                  print(f"[{thread_name}] Unexpected error for {dev_path}: {e}")
                  if last_status_update != 'offline':
                      data_queue.put(('STATUS', miner_db_id, 'offline'))
                      last_status_update = 'offline'
        finally:
            if ser and ser.is_open:
                try:
                    ser.close()
                    print(f"[{thread_name}] Closed port {dev_path} in finally block.")
                except Exception as close_e:
                     print(f"[{thread_name}] Error closing port {dev_path}: {close_e}")
            ser = None # Ensure ser is None if closed or failed to open
        
        # Wait before retrying connection, but check stop event periodically
        wait_start = time.time()
        while time.time() - wait_start < POLL_ACTIVE_MINERS_INTERVAL_SECONDS:
             if stop_event.is_set():
                 break
             time.sleep(0.5)

    # Thread is stopping
    print(f"[{thread_name}] Stopping monitoring for Miner ID {miner_db_id} on {dev_path}.")
    # Send final offline status if needed (optional, depends if shepherd's dog handles disconnects)
    # data_queue.put(('STATUS', miner_db_id, 'offline'))


def database_writer():
    """A thread that pulls data from the queue and is the ONLY writer to the database."""
    thread_name = threading.current_thread().name
    batch = []
    last_commit_time = time.time()
    last_status = {} # Track last known status written for each miner

    while True:
        try:
            item = data_queue.get(timeout=1) # Use a timeout to allow periodic commits
            batch.append(item)
            data_queue.task_done()
        except queue.Empty:
            pass # No new items, proceed to check commit condition

        # Commit the batch if conditions met
        if batch and (len(batch) >= 20 or time.time() - last_commit_time > 2.0):
            conn = None # Ensure conn is defined
            try:
                conn = get_db_connection()
                if not conn: # Handle connection failure
                     print(f"[{thread_name}] ERROR: Could not connect to DB to write batch. Retrying later.")
                     time.sleep(5)
                     continue # Skip commit, items remain in batch

                with conn: # Start a transaction
                    for item_data in batch:
                        item_type = item_data[0]
                        now_iso = datetime.now(UTC).isoformat()

                        if item_type == 'LOG':
                            _, miner_id, log_key, log_value = item_data
                            conn.execute("""
                                INSERT INTO miner_logs (miner_id, log_key, log_value, created_at)
                                VALUES (?, ?, ?, ?);
                            """, (miner_id, log_key, log_value, now_iso))
                            # Update last_seen ONLY on LOG, not status change
                            conn.execute("UPDATE miners SET last_seen = ? WHERE id = ?;", (now_iso, miner_id))

                        elif item_type == 'STATUS':
                            _, miner_id, new_status = item_data
                            # Only update if status actually changed from last known write
                            if last_status.get(miner_id) != new_status:
                                conn.execute("UPDATE miners SET status = ?, last_seen = ? WHERE id = ?;", 
                                             (new_status, now_iso, miner_id))
                                last_status[miner_id] = new_status # Update last known status
                
                # If transaction successful
                if DEBUG_MODE:
                    print(f"[{thread_name}] Committed {len(batch)} items to database.")
                batch = [] # Clear the batch
                last_commit_time = time.time()

            except sqlite3.Error as e:
                print(f"[{thread_name}] ERROR writing batch to database: {e}. Items remain in batch for retry.")
                # Keep items in batch, they will be retried next cycle
                time.sleep(5) # Wait before next attempt
            except Exception as e:
                 print(f"[{thread_name}] UNEXPECTED ERROR writing batch: {e}. Items remain in batch.")
                 time.sleep(5)
            finally:
                 if conn: conn.close() # Ensure connection is closed


def cleanup_logs():
    """Periodically cleans up old logs from the miner_logs table."""
    thread_name = threading.current_thread().name
    while True:
        # Calculate next cleanup time dynamically based on interval start
        interval_start_time = time.time()
        print(f"[{thread_name}] Running periodic log cleanup...")
        conn = None
        try:
            conn = get_db_connection()
            if not conn:
                 print(f"[{thread_name}] ERROR: Could not connect to DB for cleanup.")
                 # Sleep for interval even on error to avoid tight loop
                 time.sleep(CLEANUP_INTERVAL_MINUTES * 60)
                 continue 
                 
            with conn:
                cutoff_time = datetime.now(UTC) - timedelta(minutes=LOG_RETENTION_MINUTES)
                cutoff_iso = cutoff_time.isoformat()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM miner_logs WHERE created_at < ?;", (cutoff_iso,))
                # No need for explicit commit() when using 'with conn:'
                print(f"[{thread_name}] Deleted {cursor.rowcount} logs older than {cutoff_iso}.")
        except sqlite3.Error as e:
            print(f"[{thread_name}] ERROR during log cleanup: {e}")
        except Exception as e:
             print(f"[{thread_name}] UNEXPECTED ERROR during log cleanup: {e}")
        finally:
             if conn: conn.close()

        # Sleep until the next interval
        elapsed = time.time() - interval_start_time
        sleep_duration = max(0, (CLEANUP_INTERVAL_MINUTES * 60) - elapsed)
        print(f"[{thread_name}] Log cleanup finished. Sleeping for {sleep_duration:.1f} seconds.")
        time.sleep(sleep_duration)


# --- NEW: Main Thread Management Loop ---
def manage_monitor_threads():
    """Periodically checks DB for active miners and manages monitoring threads."""
    global active_threads
    print("[Manager] Starting thread management loop...")

    while True:
        start_time = time.time()
        print(f"[Manager] Checking for active miners...")
        
        current_active_miners = {}
        conn = get_db_connection()
        if conn:
            try:
                current_active_miners = get_active_miners(conn)
                print(f"[Manager] Found {len(current_active_miners)} active miners in DB.")
            except Exception as e:
                 print(f"[Manager] ERROR querying active miners: {e}")
            finally:
                conn.close()
        else:
             print("[Manager] ERROR: Could not connect to DB to check active miners. Skipping this cycle.")
             # Skip management cycle if DB connection fails

        
        # --- Thread Reconciliation ---
        db_miner_ids = set(current_active_miners.keys())
        running_miner_ids = set(active_threads.keys())

        # Miners to start: In DB but not running
        miners_to_start = db_miner_ids - running_miner_ids
        for miner_id in miners_to_start:
            miner_info = current_active_miners[miner_id]
            dev_path = miner_info['dev_path']
            miner_id_str = miner_info['miner_id'] # Get friendly name for logging
            
            # Check if dev_path is actually present (might have changed between DB read and now)
            if not os.path.exists(dev_path):
                 print(f"[Manager] WARNING: dev_path {dev_path} for miner {miner_id} ({miner_id_str}) not found. Cannot start thread.")
                 # Optionally update DB status back to Inactive/Offline here? Or let Shepherd's Dog handle it.
                 continue

            print(f"[Manager] Starting new monitor thread for Miner ID {miner_id} ({miner_id_str}) on {dev_path}")
            stop_event = threading.Event()
            thread = threading.Thread(
                target=monitor_miner, 
                args=(miner_id, dev_path, miner_id_str, stop_event), 
                name=f"Miner-{miner_id}-{miner_id_str}", 
                daemon=True # Daemon threads exit when main thread exits
            )
            active_threads[miner_id] = {'thread': thread, 'stop_event': stop_event}
            thread.start()
            time.sleep(0.1) # Stagger thread starts slightly

        # Miners to stop: Running but not in DB (or status changed)
        miners_to_stop = running_miner_ids - db_miner_ids
        for miner_id in miners_to_stop:
            if miner_id in active_threads:
                print(f"[Manager] Stopping monitor thread for Miner ID {miner_id}")
                active_threads[miner_id]['stop_event'].set() # Signal thread to stop
                # Optional: Join thread here if immediate cleanup needed, but can slow down loop
                # active_threads[miner_id]['thread'].join(timeout=2) 
                del active_threads[miner_id] # Remove from active list

        # Sleep until next check
        elapsed = time.time() - start_time
        sleep_duration = max(0, POLL_ACTIVE_MINERS_INTERVAL_SECONDS - elapsed)
        print(f"[Manager] Check complete in {elapsed:.2f}s. Sleeping for {sleep_duration:.2f}s.")
        time.sleep(sleep_duration)


# --- Main Application Logic ---

if __name__ == "__main__":
    print("Starting The Shepherd Data Ingestor (V.0.0.5 - Dynamic Threads)...")
    
    # Start the single database writer thread
    writer_thread = threading.Thread(target=database_writer, name="DB-Writer", daemon=True)
    writer_thread.start()

    # Start the single log cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_logs, name="Log-Cleaner", daemon=True)
    cleanup_thread.start()
    
    # Start the main thread management loop (this will run forever in the main thread)
    try:
        manage_monitor_threads()
    except KeyboardInterrupt:
        print("\n[Manager] Shutdown signal received. Stopping all monitor threads...")
        # Signal all running threads to stop
        for miner_id, data in active_threads.items():
             print(f"[Manager] Signaling stop for Miner ID {miner_id}...")
             data['stop_event'].set()
        # Optionally wait for threads to finish
        # print("[Manager] Waiting for threads to exit...")
        # for miner_id, data in active_threads.items():
        #     data['thread'].join(timeout=5) 
        print("[Manager] Exiting.")
    except Exception as e:
         print(f"[Manager] UNEXPECTED FATAL ERROR in main loop: {e}")
         import traceback
         traceback.print_exc()
