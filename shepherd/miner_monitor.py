# shepherd/miner_monitor.py
# V.1.0.2
# Description: Self-contained worker thread for monitoring a single miner.
# FIXED: Changed imports back to ABSOLUTE (e.g., shepherd.database) to work
# when imported by a script in the parent directory (shepherds_dog.py).

import serial
import threading
import sqlite3
import time
import re
from datetime import datetime, timedelta, UTC

# --- Use ABSOLUTE imports since this package is loaded by a script ---
from shepherd.database import get_db_connection

# --- Configuration (from original summarizer/ingestor) ---
MINIMUM_TIME_DELTA_SECONDS = 2.0
DEBUG_MODE = False

class MinerMonitor(threading.Thread):
    """
    A dedicated thread to monitor, parse, and summarize data from a single
    NerdMiner serial port.
    """
    def __init__(self, miner_db_id, dev_path, miner_id_str):
        super().__init__()
        self.miner_db_id = miner_db_id
        self.dev_path = dev_path
        self.miner_id_str = miner_id_str # Friendly name for logging
        
        self._stop_event = threading.Event()
        self.setName(f"MinerMonitor-{self.miner_db_id}({self.miner_id_str})")
        
        # --- State for Hashrate Calculation (from summarizer) ---
        self.last_mhashes_cumulative = None
        self.last_mhashes_timestamp = None
        
        # --- State for Database (from ingestor) ---
        self.log_pattern = re.compile(r'>>>\s*(?P<key>.+?):\s*(?P<value>.+)')
        self.db_batch = []
        self.last_batch_commit_time = time.time()

        print(f"[{self.getName()}] Initialized for port {self.dev_path}")

    def stop(self):
        """Signals the thread to stop."""
        print(f"[{self.getName()}] Received stop signal.")
        self._stop_event.set()

    def run(self):
        """The main loop of the monitoring thread."""
        print(f"[{self.getName()}] Thread started, monitoring {self.dev_path}...")

        while not self._stop_event.is_set():
            ser = None
            try:
                # 1. Try to open the serial port
                ser = serial.Serial(self.dev_path, 115200, timeout=1)
                print(f"[{self.getName()}] Successfully connected to {self.dev_path}.")
                self.update_miner_status('Active', 'Connected') # Set status to Active/Connected

                # 2. Read loop while connected
                while ser.is_open and not self._stop_event.is_set():
                    try:
                        if self._stop_event.is_set():
                            break
                            
                        line_bytes = ser.readline()
                        if line_bytes:
                            line = line_bytes.decode('utf-8', errors='ignore').strip()
                            if line:
                                self.process_log_line(line) # Parse and summarize
                        else:
                            # readline timed out (no data), check for stop and loop
                            time.sleep(0.05) 
                            
                        # Check if it's time to commit the batch
                        if self.db_batch and (time.time() - self.last_batch_commit_time > 2.0):
                            self.commit_batch_to_db()

                    except serial.SerialException as read_e:
                        print(f"[{self.getName()}] Device {self.dev_path} disconnected: {read_e}. Retrying...")
                        self.update_miner_status('Offline', 'Disconnected') # Set status to Offline
                        break # Break inner loop to reconnect
                    except Exception as loop_e:
                        print(f"[{self.getName()}] Error reading from {self.dev_path}: {loop_e}")
                        time.sleep(1)

            except serial.SerialException as connect_e:
                if not self._stop_event.is_set():
                    # Only log error if we weren't told to stop
                    print(f"[{self.getName()}] Could not open port {self.dev_path}: {connect_e}. Retrying in 5s...")
            except Exception as outer_e:
                 if not self._stop_event.is_set():
                      print(f"[{self.getName()}] Unexpected error for {self.dev_path}: {outer_e}")
            finally:
                if ser and ser.is_open:
                    try: ser.close()
                    except Exception as close_e: print(f"[{self.getName()}] Error closing port: {close_e}")
                ser = None
                
                # Commit any remaining items before sleeping
                self.commit_batch_to_db()

            # Wait before retrying connection, but check stop event periodically
            wait_start = time.time()
            while time.time() - wait_start < 5.0: # 5 second retry
                if self._stop_event.is_set():
                    break
                time.sleep(0.2)
        
        # Thread is stopping
        self.update_miner_status('Offline', 'Stopped') # Set final status
        self.commit_batch_to_db() # Commit any final logs
        print(f"[{self.getName()}] Thread stopped.")


    def process_log_line(self, line):
        """Parses a raw log line and stages it for DB summary update."""
        if DEBUG_MODE:
            print(f"[{self.getName()}] RAW: {line}")
        
        match = self.log_pattern.match(line)
        if not match:
            return # Not a parsable line

        data = match.groupdict()
        log_key = data['key']
        log_value = data['value']
        now_iso = datetime.now(UTC).isoformat()

        # --- This is the logic from summarizer.py ---
        
        # Standard value update
        # We queue up (key, value) pairs to be updated
        self.db_batch.append((log_key, log_value, now_iso))

        # Specific logic for Hashrate
        if log_key == 'Total MHashes':
            try:
                current_mhashes = float(log_value)
                current_timestamp_dt = datetime.fromisoformat(now_iso)

                if self.last_mhashes_cumulative is not None and self.last_mhashes_timestamp is not None:
                    time_delta = (current_timestamp_dt - self.last_mhashes_timestamp).total_seconds()
                    
                    if current_mhashes > self.last_mhashes_cumulative and time_delta >= MINIMUM_TIME_DELTA_SECONDS:
                        mhash_delta = current_mhashes - self.last_mhashes_cumulative
                        khs_float = (mhash_delta * 100) / time_delta # mH/s * 100 = kH/s
                        khs_str = f"{khs_float:.2f}"
                        # Add the calculated KH/s to the batch
                        self.db_batch.append(('KH/s', khs_str, now_iso))

                # Update state for next calculation
                self.last_mhashes_cumulative = current_mhashes
                self.last_mhashes_timestamp = current_timestamp_dt
                
            except (ValueError, TypeError) as e:
                print(f"[{self.getName()}] Error processing MHashes: {e}")


    def commit_batch_to_db(self):
        """Writes the current batch of summary data to the database."""
        if not self.db_batch:
            return

        conn = None
        try:
            conn = get_db_connection()
            if not conn:
                print(f"[{self.getName()}] ERROR: Could not connect to DB to commit batch.")
                return

            with conn:
                # Ensure the summary row exists
                conn.execute("INSERT OR IGNORE INTO miner_summary (miner_id) VALUES (?);", (self.miner_db_id,))
            
                # Use a dictionary to hold the latest value for each key in the batch
                latest_updates = {}
                for key, value, timestamp in self.db_batch:
                    # Fix for firmware key
                    if key == '32Bit shares':
                        key = 'Shares'
                    latest_updates[key] = (value, timestamp)
                
                # Build the dynamic UPDATE query
                set_clauses = []
                values = []
                
                # Always update last_updated
                set_clauses.append("last_updated = ?")
                values.append(datetime.now(UTC).isoformat()) # Use the commit time as last_updated

                for key, (value, timestamp) in latest_updates.items():
                    # Only update columns that exist in the summary table
                    # We have to use "KH/s" (quoted) because of the slash
                    col_name = f'"{key}"' if '/' in key else key
                    
                    # This is a bit of a hack, but safer than arbitrary keys
                    if col_name in ('"KH/s"', 'Temperature', 'Valid blocks', 'Best difficulty', 
                                    'Total MHashes', 'Submits', 'Shares', 'Time mining', 'Block templates'):
                        
                        set_clauses.append(f"{col_name} = ?")
                        values.append(value)
                        
                        # Specific state update for hashrate calculation
                        if key == 'Total MHashes':
                             set_clauses.append("last_mhashes_cumulative = ?")
                             values.append(value)
                             set_clauses.append("last_mhashes_timestamp = ?")
                             values.append(timestamp)

                if len(set_clauses) > 1: # (We always have last_updated)
                    sql = f"UPDATE miner_summary SET {', '.join(set_clauses)} WHERE miner_id = ?;"
                    values.append(self.miner_db_id)
                    
                    if DEBUG_MODE:
                        print(f"[{self.getName()}] Committing SQL: {sql} VALUES: {values}")
                    
                    conn.execute(sql, values)
            
            # If commit successful, clear batch
            self.db_batch = []
            self.last_batch_commit_time = time.time()

        except sqlite3.Error as e:
            print(f"[{self.getName()}] ERROR committing batch to DB: {e}. Batch will be retried.")
        except Exception as e:
             print(f"[{self.getName()}] UNEXPECTED ERROR committing batch: {e}")
        finally:
            if conn:
                conn.close()

    def update_miner_status(self, new_status, new_state):
        """Updates the miner's main status in the 'miners' table."""
        conn = None
        try:
            conn = get_db_connection()
            if not conn:
                 print(f"[{self.getName()}] ERROR: Could not connect to DB to update status.")
                 return
            with conn:
                conn.execute(
                    "UPDATE miners SET status = ?, state = ?, last_seen = ? WHERE id = ?;",
                    (new_status, new_state, datetime.now(UTC).isoformat(), self.miner_db_id)
                )
            print(f"[{self.getName()}] Set status to '{new_status}' / '{new_state}'")
        except sqlite3.Error as e:
            print(f"[{self.getName()}] ERROR updating miner status: {e}")
        finally:
            if conn:
                conn.close()

