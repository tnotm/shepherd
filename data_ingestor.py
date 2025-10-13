import sqlite3
import serial
import threading
import time
import re
from datetime import datetime, timedelta
import queue

DB_FILE = 'shepherd.db'
# This dictionary will hold our known miner symlinks and their primary key IDs.
KNOWN_MINERS = {}
# A thread-safe queue to hold data from all miner threads before writing to the DB.
DATA_QUEUE = queue.Queue()

def get_db_connection():
    """Establishes a connection to the database. Essential for each thread."""
    # By adding a timeout, connections will wait for the specified time if the DB is locked.
    conn = sqlite3.connect(DB_FILE, timeout=10, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def update_miner_cache():
    """
    Reads the miners table and populates the KNOWN_MINERS dictionary.
    This is called at the start to know which TTYs to listen to.
    """
    global KNOWN_MINERS
    print("Updating miner cache from database...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, tty_symlink FROM miners WHERE tty_symlink IS NOT NULL;")
        miners = cursor.fetchall()
        conn.close()
        
        KNOWN_MINERS = {row[1]: row[0] for row in miners}
        print(f"Found {len(KNOWN_MINERS)} configured miners to monitor.")
    except Exception as e:
        print(f"Error updating miner cache: {e}")
        print("Please ensure the database exists and the 'miners' table has been created.")


def parse_and_store_data(miner_db_id, line, conn):
    """
    Parses a single log line, updates the main 'miners' table for key stats,
    and inserts the raw log into the 'miner_logs' table.
    """
    match = re.search(r'>>>\s*(.*?):\s*(.*)', line)
    if not match:
        return

    metric_key = match.group(1).strip()
    metric_value = match.group(2).strip()
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()

    # 1. Insert the raw metric into the logs table.
    log_sql = "INSERT INTO miner_logs (miner_id, timestamp, metric_key, metric_value) VALUES (?, ?, ?, ?);"
    cursor.execute(log_sql, (miner_db_id, timestamp, metric_key, metric_value))
    
    # 2. Update the main table with the latest key metrics for the dashboard.
    update_sql = "UPDATE miners SET status = 'online', last_seen = ? WHERE id = ?;"
    update_params = [timestamp, miner_db_id]
    
    if metric_key == 'Hash rate':
        val_match = re.search(r'(\d+\.?\d*)', metric_value)
        if val_match:
            hash_rate = float(val_match.group(1))
            update_sql = "UPDATE miners SET hash_rate = ?, status = 'online', last_seen = ? WHERE id = ?;"
            update_params = [hash_rate, timestamp, miner_db_id]
    elif metric_key == 'Temperature':
        val_match = re.search(r'(\d+\.?\d*)', metric_value)
        if val_match:
            temperature = float(val_match.group(1))
            update_sql = "UPDATE miners SET temperature = ?, status = 'online', last_seen = ? WHERE id = ?;"
            update_params = [temperature, timestamp, miner_db_id]
            
    cursor.execute(update_sql, tuple(update_params))
    # Note: The commit is handled in the database_writer loop.

def database_writer():
    """
    A dedicated thread that pulls data from the queue and writes it to the database.
    This prevents 'database is locked' errors by serializing all writes.
    """
    print("[DB-Writer] Starting database writer thread.")
    conn = get_db_connection()
    
    while True:
        try:
            # The get() method will block until an item is available in the queue.
            miner_db_id, line = DATA_QUEUE.get()
            
            if line is None: # A signal to update the status of an offline miner
                cursor = conn.cursor()
                cursor.execute("UPDATE miners SET status = 'offline' WHERE id = ?;", (miner_db_id,))
            else:
                parse_and_store_data(miner_db_id, line, conn)

            conn.commit() # Commit after each successful write.

        except queue.Empty:
            # This shouldn't happen with a blocking get(), but it's safe to handle.
            time.sleep(0.1)
        except Exception as e:
            print(f"[DB-Writer] Error writing to database: {e}")


def monitor_miner(tty_symlink, miner_db_id):
    """
    The main function for each miner thread. Opens a serial port, reads data,
    and puts it into the DATA_QUEUE for the writer thread to process.
    """
    print(f"[Thread-{miner_db_id}] Starting monitoring for {tty_symlink} (/dev/{tty_symlink})")
    
    while True:
        try:
            ser = serial.Serial(f'/dev/{tty_symlink}', 115200, timeout=1)
            print(f"[Thread-{miner_db_id}] Successfully connected to {tty_symlink}.")
            
            while True:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        # Instead of writing to the DB, put the data in the queue.
                        DATA_QUEUE.put((miner_db_id, line))
                except serial.SerialException as e:
                    print(f"[Thread-{miner_db_id}] Serial error on {tty_symlink}: {e}. Reconnecting...")
                    break
                except Exception as e:
                    print(f"[Thread-{miner_db_id}] Error processing line from {tty_symlink}: {e}")

        except serial.SerialException as e:
            print(f"[Thread-{miner_db_id}] Could not open port {tty_symlink}: {e}. Retrying in 10 seconds...")
            # Put a special message in the queue to mark this miner as offline.
            DATA_QUEUE.put((miner_db_id, None))
            time.sleep(10)
        except Exception as e:
            print(f"[Thread-{miner_db_id}] An unexpected error occurred for {tty_symlink}: {e}. Retrying in 10 seconds...")
            time.sleep(10)

def periodic_cleanup():
    """
    A dedicated thread that periodically cleans up old data from the miner_logs table.
    """
    print("[Cleaner] Starting periodic cleanup thread.")
    while True:
        # Wait for 10 minutes (600 seconds) before running the cleanup.
        time.sleep(600)
        
        try:
            print("[Cleaner] Running cleanup of old log data...")
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Calculate the timestamp for 10 minutes ago in ISO format.
            ten_minutes_ago = (datetime.now() - timedelta(minutes=10)).isoformat()
            
            # Execute the delete operation.
            cursor.execute("DELETE FROM miner_logs WHERE timestamp < ?", (ten_minutes_ago,))
            conn.commit()
            
            deleted_rows = cursor.rowcount
            print(f"[Cleaner] Cleanup complete. Removed {deleted_rows} old log entries.")
            
            conn.close()
        except Exception as e:
            print(f"[Cleaner] Error during cleanup: {e}")

if __name__ == '__main__':
    update_miner_cache()
    
    if not KNOWN_MINERS:
        print("No miners found in the database. Please run the web app and upload a CSV first.")
    else:
        # Start the single database writer thread.
        writer_thread = threading.Thread(target=database_writer)
        writer_thread.daemon = True
        writer_thread.start()

        # Start the periodic cleanup thread.
        cleanup_thread = threading.Thread(target=periodic_cleanup)
        cleanup_thread.daemon = True
        cleanup_thread.start()

        threads = []
        for tty, miner_id in KNOWN_MINERS.items():
            thread = threading.Thread(target=monitor_miner, args=(tty, miner_id))
            thread.daemon = True
            threads.append(thread)
            thread.start()
        
        # Keep the main thread alive to let the daemon threads run.
        while True:
            time.sleep(1)

