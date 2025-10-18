# data_ingestor.py
# V.0.0.0.3
# Description: Handles serial data collection from miners and writes to the database.

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

data_queue = queue.Queue()

# --- Database Functions ---

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def get_configured_miners(conn):
    """Fetches the list of configured miners from the database."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, miner_id, tty_symlink FROM miners WHERE tty_symlink IS NOT NULL;")
    miners = cursor.fetchall()
    return {miner['tty_symlink']: {'miner_id': miner['miner_id'], 'db_id': miner['id']} for miner in miners}

# --- Worker Threads ---

def monitor_miner(tty_symlink, miner_info):
# ... existing code ...
    thread_name = threading.current_thread().name
    miner_db_id = miner_info['db_id']
    log_pattern = re.compile(r'>>>\s*(?P<key>.+?):\s*(?P<value>.+)')
    
    while True:
        ser = None
        try:
            ser = serial.Serial(f'/dev/{tty_symlink}', 115200, timeout=1)
            print(f"[{thread_name}] Successfully connected to {tty_symlink}.")
            data_queue.put(('STATUS', miner_db_id, 'online'))

            while ser.is_open:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        if DEBUG_MODE:
                            print(f"[{thread_name}] RAW: {line}")
                        
                        match = log_pattern.match(line)
                        if match:
                            data = match.groupdict()
                            data_queue.put(('LOG', miner_db_id, data['key'], data['value']))
                except serial.SerialException:
                    print(f"[{thread_name}] Device {tty_symlink} disconnected. Retrying...")
                    break
                except Exception as e:
                    print(f"[{thread_name}] Error reading from {tty_symlink}: {e}")
                    time.sleep(1)

        except serial.SerialException as e:
            print(f"[{thread_name}] Could not open port {tty_symlink}: {e}. Retrying in 10 seconds...")
            data_queue.put(('STATUS', miner_db_id, 'offline'))
        finally:
            if ser and ser.is_open:
                ser.close()
        time.sleep(10)


def database_writer():
    """A thread that pulls data from the queue and is the ONLY writer to the database."""
    thread_name = threading.current_thread().name
    while True:
        try:
            # --- MEMORY LEAK FIX ---
            # The 'with' statement is now INSIDE the loop.
            # This ensures the connection is created and, crucially,
            # closed cleanly on every iteration, even if errors occur.
            with get_db_connection() as conn:
                while not data_queue.empty(): # Process all items currently in queue
                    item = data_queue.get()
                    now_iso = datetime.now(UTC).isoformat()

                    with conn: # Use a transaction for the block
                        if item[0] == 'LOG':
                            _, miner_id, log_key, log_value = item
                            conn.execute("""
                                INSERT INTO miner_logs (miner_id, log_key, log_value, created_at)
                                VALUES (?, ?, ?, ?);
                            """, (miner_id, log_key, log_value, now_iso))
                            conn.execute("UPDATE miners SET last_seen = ? WHERE id = ?;", (now_iso, miner_id))

                        elif item[0] == 'STATUS':
                            _, miner_id, new_status = item
                            conn.execute("UPDATE miners SET status = ?, last_seen = ? WHERE id = ?;", (new_status, now_iso, miner_id))
                    
                    data_queue.task_done()
            # -------------------------
            time.sleep(1) # Small sleep to prevent tight-looping if queue is empty

        except Exception as e:
            print(f"[{thread_name}] Error writing to database: {e}. Retrying in 5s...")
            time.sleep(5)


def cleanup_logs():
# ... existing code ...
    thread_name = threading.current_thread().name
    while True:
        time.sleep(CLEANUP_INTERVAL_MINUTES * 60)
        try:
            with get_db_connection() as conn:
                cutoff_time = datetime.now(UTC) - timedelta(minutes=LOG_RETENTION_MINUTES)
                cutoff_iso = cutoff_time.isoformat()
                cursor = conn.cursor()
                cursor.execute("DELETE FROM miner_logs WHERE created_at < ?;", (cutoff_iso,))
                conn.commit()
                print(f"[{thread_name}] Deleted {cursor.rowcount} logs older than {cutoff_iso}.")
        except Exception as e:
            print(f"[{thread_name}] Error during log cleanup: {e}")

# --- Main Application Logic ---

if __name__ == "__main__":
# ... existing code ...
    print("Starting The Shepherd Data Ingestor...")
    writer_thread = threading.Thread(target=database_writer, name="DB-Writer", daemon=True)
    writer_thread.start()

    cleanup_thread = threading.Thread(target=cleanup_logs, name="Log-Cleaner", daemon=True)
    cleanup_thread.start()
    
    with get_db_connection() as conn:
        miners_to_monitor = get_configured_miners(conn)
        print(f"Found {len(miners_to_monitor)} configured miners to monitor.")

    for tty, info in miners_to_monitor.items():
        thread = threading.Thread(target=monitor_miner, args=(tty, info), name=f"Miner-{info['miner_id']}", daemon=True)
        thread.start()
        time.sleep(0.1)

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nShutting down ingestor...")
