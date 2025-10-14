import sqlite3
import time
import os
from datetime import datetime, timedelta, UTC

# --- Configuration ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
DATABASE_FILE = os.path.join(DATA_DIR, 'shepherd.db')
AGGREGATION_INTERVAL_SECONDS = 5 
DATA_WINDOW_MINUTES = 2 
MINIMUM_TIME_DELTA_SECONDS = 2.0

# --- Database Functions ---
def get_db_connection():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

# --- Summarization Logic ---
def update_summary_stats(conn):
    """
    Calculates all summary stats and updates the miner_summary table in a robust way.
    """
    # First, ensure a summary row exists for every single configured miner.
    # This is a cheap and safe operation that prevents errors later.
    conn.execute("INSERT OR IGNORE INTO miner_summary (miner_id) SELECT id FROM miners;")

    miners_cursor = conn.execute("SELECT id as miner_id FROM miners;")
    miner_ids = [row['miner_id'] for row in miners_cursor.fetchall()]
    
    now_iso = datetime.now(UTC).isoformat()
    cutoff_time = datetime.now(UTC) - timedelta(minutes=DATA_WINDOW_MINUTES)
    cutoff_iso = cutoff_time.isoformat()

    for miner_id in miner_ids:
        # Get all the latest log values for this miner in a single query
        logs_cursor = conn.execute(f"""
            WITH RankedLogs AS (
                SELECT log_key, log_value, created_at,
                       ROW_NUMBER() OVER(PARTITION BY log_key ORDER BY created_at DESC) as rn
                FROM miner_logs
                WHERE miner_id = ? AND created_at >= ?
            )
            SELECT log_key, log_value, created_at FROM RankedLogs WHERE rn = 1;
        """, (miner_id, cutoff_iso))
        
        latest_logs = {row['log_key']: {'value': row['log_value'], 'timestamp': row['created_at']} for row in logs_cursor.fetchall()}

        # Get the previous state for the hashrate calculation
        summary_cursor = conn.execute("SELECT last_mhashes_cumulative, last_mhashes_timestamp FROM miner_summary WHERE miner_id = ?;", (miner_id,))
        summary_state = summary_cursor.fetchone()

        # --- Hashrate Calculation ---
        khs = None
        current_mhashes_data = latest_logs.get('Total MHashes')

        if summary_state and current_mhashes_data:
            try:
                current_mhashes = float(current_mhashes_data['value'])
                current_timestamp_iso = current_mhashes_data['timestamp']
                current_timestamp_dt = datetime.fromisoformat(current_timestamp_iso)

                if summary_state['last_mhashes_cumulative'] is not None and summary_state['last_mhashes_timestamp'] is not None:
                    last_mhashes = summary_state['last_mhashes_cumulative']
                    last_timestamp_dt = datetime.fromisoformat(summary_state['last_mhashes_timestamp'])
                    time_delta = (current_timestamp_dt - last_timestamp_dt).total_seconds()

                    if current_mhashes > last_mhashes and time_delta >= MINIMUM_TIME_DELTA_SECONDS:
                        mhash_delta = current_mhashes - last_mhashes
                        # --- MODIFIED: Adjusted the calculation multiplier. ---
                        # Based on comparison with the pool's reported hashrate, the raw delta
                        # needs to be multiplied by 100 to get the correct kH/s value.
                        khs_float = (mhash_delta * 100) / time_delta
                        # -----------------------------------------------------------
                        khs = f"{khs_float:.2f}"
                
                # --- The Fix: A single, intelligent UPDATE statement ---
                # It only updates KH/s if a new value was calculated.
                # It always updates other stats if new values were found.
                conn.execute("""
                    UPDATE miner_summary
                    SET
                        last_updated = ?,
                        "KH/s" = CASE WHEN ? IS NOT NULL THEN ? ELSE "KH/s" END,
                        "Temperature" = COALESCE(?, "Temperature"),
                        "Valid blocks" = COALESCE(?, "Valid blocks"),
                        "Best difficulty" = COALESCE(?, "Best difficulty"),
                        "Total MHashes" = COALESCE(?, "Total MHashes"),
                        last_mhashes_cumulative = ?,
                        last_mhashes_timestamp = ?
                    WHERE miner_id = ?;
                """, (
                    now_iso,
                    khs, khs, # Used twice for the CASE WHEN statement
                    latest_logs.get('Temperature', {}).get('value'),
                    latest_logs.get('Valid blocks', {}).get('value'),
                    latest_logs.get('Best difficulty', {}).get('value'),
                    current_mhashes_data.get('value'),
                    current_mhashes,
                    current_timestamp_iso,
                    miner_id
                ))
            except (ValueError, TypeError, KeyError) as e:
                print(f"Could not process summary for miner {miner_id}: {e}")

if __name__ == "__main__":
    print("Starting The Shepherd Data Summarizer...")
    try:
        while True:
            try:
                with get_db_connection() as conn:
                    with conn:
                        update_summary_stats(conn)
                    print(f"[{datetime.now(UTC).isoformat()}] Summarization complete.")
            except Exception as e:
                print(f"An error occurred during summarization cycle: {e}")
            
            time.sleep(AGGREGATION_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nShutting down summarizer...")

