import serial
import sqlite3
import time
import threading
import queue
import re
from datetime import datetime, timedelta

# --- Configuration ---
DATABASE_FILE = 'shepherd.db'
LOG_RETENTION_MINUTES = 10
CLEANUP_INTERVAL_MINUTES = 10

# A thread-safe queue to hold all incoming data from the miners
data_queue = queue.Queue()

# --- Database Functions ---

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_FILE, timeout=10) # 10-second timeout
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;') # Enable Write-Ahead Logging
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
    port = f'/dev/{tty_symlink}'
    print(f"[{thread_name}] Starting monitoring for {tty_symlink} ({port})")

    while True:
        try:
            ser = serial.Serial(port, 115200, timeout=5)
            print(f"[{thread_name}] Successfully connected to {tty_symlink}.")
            
            # Set status to online on successful connection
            with get_db_connection() as conn:
                conn.execute("UPDATE miners SET status = 'online', last_seen = CURRENT_TIMESTAMP WHERE id = ?;", (miner_db_id,))
                conn.commit()

            while True:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if ">>>" in line:
                    # Put the raw line and miner info into the queue for the DB writer
                    data_queue.put((miner_db_id, line))

        except serial.SerialException as e:
            print(f"[{thread_name}] Could not open port {tty_symlink}: {e}. Retrying in 10 seconds...")
            # Set status to offline on connection failure
            with get_db_connection() as conn:
                 conn.execute("UPDATE miners SET status = 'offline' WHERE id = ?;", (miner_db_id,))
                 conn.commit()
            time.sleep(10)
        except Exception as e:
            print(f"[{thread_name}] An unexpected error occurred with {tty_symlink}: {e}. Reconnecting in 10 seconds...")
            time.sleep(10)

def database_writer():
    """A thread function that writes data from the queue to the database."""
    thread_name = threading.current_thread().name
    print(f"[{thread_name}] Database writer thread started.")
    
    # Regex to parse the key-value pairs from the log lines
    line_parser = re.compile(r'>>>\s*(.*?):\s*(.*)')

    while True:
        try:
            miner_db_id, line = data_queue.get()
            
            match = line_parser.search(line)
            if match:
                key, value = match.groups()
                key = key.strip()
                value = value.strip()

                with get_db_connection() as conn:
                    conn.execute(
                        "INSERT INTO miner_logs (miner_id, log_key, log_value) VALUES (?, ?, ?);",
                        (miner_db_id, key, value)
                    )
                    # Also update the 'last_seen' timestamp in the main miners table
                    conn.execute(
                        "UPDATE miners SET last_seen = CURRENT_TIMESTAMP WHERE id = ?;",
                        (miner_db_id,)
                    )
                    conn.commit()
            
            data_queue.task_done()

        except Exception as e:
            print(f"[{thread_name}] Error processing line '{line}': {e}")


def cleanup_logs():
    """A thread function that periodically cleans old logs from the database."""
    thread_name = threading.current_thread().name
    print(f"[{thread_name}] Log cleanup thread started. Will run every {CLEANUP_INTERVAL_MINUTES} minutes.")
    
    while True:
        time.sleep(CLEANUP_INTERVAL_MINUTES * 60)
        
        try:
            with get_db_connection() as conn:
                print(f"[{thread_name}] Running cleanup job...")
                
                # Calculate the cutoff time
                cutoff_time = datetime.utcnow() - timedelta(minutes=LOG_RETENTION_MINUTES)
                cutoff_iso = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')

                cursor = conn.cursor()
                cursor.execute("DELETE FROM miner_logs WHERE created_at < ?;", (cutoff_iso,))
                conn.commit()
                
                print(f"[{thread_name}] Deleted {cursor.rowcount} logs older than {cutoff_iso}.")

        except Exception as e:
            print(f"[{thread_name}] Error during log cleanup: {e}")


# --- Main Application Logic ---

if __name__ == "__main__":
    print("Starting The Shepherd Data Ingestor...")

    # Start the database writer thread
    writer_thread = threading.Thread(target=database_writer, name="DB-Writer", daemon=True)
    writer_thread.start()

    # Start the log cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_logs, name="Log-Cleaner", daemon=True)
    cleanup_thread.start()

    # Main loop to start and monitor miner threads
    with get_db_connection() as conn:
        miners_to_monitor = get_configured_miners(conn)
        print(f"Found {len(miners_to_monitor)} configured miners to monitor.")

    for tty, info in miners_to_monitor.items():
        thread = threading.Thread(target=monitor_miner, args=(tty, info), name=f"Miner-{info['miner_id']}", daemon=True)
        thread.start()
        time.sleep(0.1) # Stagger thread starts slightly

    try:
        while True:
            time.sleep(60)
            # The main thread can perform other periodic tasks here if needed
            
    except KeyboardInterrupt:
        print("\nShutting down ingestor...")

