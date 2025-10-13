import serial
import sqlite3
import time
import threading
import queue
import re
import os
from datetime import datetime, timedelta

# --- Configuration ---
# --- NEW: Set to True to print all incoming serial data ---
DEBUG_MODE = True 
# ---------------------------------------------------------

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
    """A thread function that monitors a single miner's serial port."""
    thread_name = threading.current_thread().name
    miner_db_id = miner_info['db_id']
    log_pattern = re.compile(r'>>>\s*(?P<key>.+?):\s*(?P<value>.+)')
    
    while True:
        ser = None
        try:
            ser = serial.Serial(f'/dev/{tty_symlink}', 115200, timeout=1)
            print(f"[{thread_name}] Successfully connected to {tty_symlink}.")
            
            with get_db_connection() as conn:
                conn.execute("UPDATE miners SET status = 'online', last_seen = ? WHERE id = ?;", (datetime.utcnow(), miner_db_id))
                conn.commit()

            while ser.is_open:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        # --- MODIFIED: Print line if in debug mode ---
                        if DEBUG_MODE:
                            print(f"[{thread_name}] RAW: {line}")
                        # ----------------------------------------------
                        
                        match = log_pattern.match(line)
                        if match:
                            data = match.groupdict()
                            data_queue.put((miner_db_id, data['key'], data['value']))
                except serial.SerialException:
                    print(f"[{thread_name}] Device {tty_symlink} disconnected. Retrying...")
                    break
                except Exception as e:
                    print(f"[{thread_name}] Error reading from {tty_symlink}: {e}")
                    time.sleep(1)

        except serial.SerialException as e:
            print(f"[{thread_name}] Could not open port {tty_symlink}: {e}. Retrying in 10 seconds...")
            with get_db_connection() as conn:
                conn.execute("UPDATE miners SET status = 'offline' WHERE id = ?;", (miner_db_id,))
                conn.commit()
        finally:
            if ser and ser.is_open:
                ser.close()
        time.sleep(10)


def database_writer():
    """A thread that pulls data from the queue and writes it to the database."""
    thread_name = threading.current_thread().name
    while True:
        try:
            with get_db_connection() as conn:
                while True:
                    miner_id, log_key, log_value = data_queue.get()
                    
                    conn.execute("""
                        INSERT INTO miner_logs (miner_id, log_key, log_value, created_at)
                        VALUES (?, ?, ?, ?);
                    """, (miner_id, log_key, log_value, datetime.utcnow()))
                    
                    conn.execute("""
                        UPDATE miners SET last_seen = ? WHERE id = ?;
                    """, (datetime.utcnow(), miner_id))

                    conn.commit()
                    data_queue.task_done()
        except Exception as e:
            print(f"[{thread_name}] Error writing to database: {e}. Reconnecting in 5s...")
            time.sleep(5)

def cleanup_logs():
    """Periodically cleans up old logs from the miner_logs table."""
    thread_name = threading.current_thread().name
    while True:
        time.sleep(CLEANUP_INTERVAL_MINUTES * 60)
        try:
            with get_db_connection() as conn:
                cutoff_time = datetime.utcnow() - timedelta(minutes=LOG_RETENTION_MINUTES)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM miner_logs WHERE created_at < ?;", (cutoff_time,))
                conn.commit()
                print(f"[{thread_name}] Deleted {cursor.rowcount} logs older than {cutoff_time}.")
        except Exception as e:
            print(f"[{thread_name}] Error during log cleanup: {e}")

# --- Main Application Logic ---

if __name__ == "__main__":
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

