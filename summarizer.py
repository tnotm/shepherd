import sqlite3
import time
import os
from datetime import datetime, timedelta, UTC

# --- Configuration ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
DATABASE_FILE = os.path.join(DATA_DIR, 'shepherd.db')
AGGREGATION_INTERVAL_SECONDS = 5 
DATA_WINDOW_MINUTES = 2 
MINIMUM_TIME_DELTA_SECONDS = 2.0 # Minimum time between hashrate calculations

# --- Database Functions ---
def get_db_connection():
    """Establishes a connection to the SQLite database."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

# --- Summarization Logic ---

def update_hashrate_summary(conn):
    """
    Calculates the instantaneous hashrate for each miner and UPDATES the
    existing summary row.
    """
    miners_cursor = conn.execute("SELECT id FROM miners;")
    miner_ids = [row['id'] for row in miners_cursor.fetchall()]

    for miner_id in miner_ids:
        latest_log_cursor = conn.execute("""
            SELECT log_value, created_at FROM miner_logs
            WHERE miner_id = ? AND log_key = 'Total MHashes'
            ORDER BY created_at DESC LIMIT 1;
        """, (miner_id,))
        latest_log = latest_log_cursor.fetchone()

        if not latest_log:
            continue

        try:
            current_mhashes = float(latest_log['log_value'])
            current_timestamp_dt = datetime.fromisoformat(latest_log['created_at'])
        except (ValueError, TypeError):
            continue

        summary_cursor = conn.execute("""
            SELECT last_mhashes_cumulative, last_mhashes_timestamp FROM miner_summary
            WHERE miner_id = ?;
        """, (miner_id,))
        summary_state = summary_cursor.fetchone()

        khs = None
        if summary_state and summary_state['last_mhashes_cumulative'] is not None and summary_state['last_mhashes_timestamp'] is not None:
            last_mhashes = summary_state['last_mhashes_cumulative']
            last_timestamp_dt = datetime.fromisoformat(summary_state['last_mhashes_timestamp'])
            
            time_delta = (current_timestamp_dt - last_timestamp_dt).total_seconds()

            if current_mhashes > last_mhashes and time_delta >= MINIMUM_TIME_DELTA_SECONDS:
                mhash_delta = current_mhashes - last_mhashes
                khs_float = (mhash_delta * 1000) / time_delta
                khs = f"{khs_float:.2f}"

        # --- MODIFIED: Changed from a broad INSERT/UPSERT to a targeted UPDATE ---
        # This prevents this function from wiping out the data from the other summary function.
        conn.execute("""
            UPDATE miner_summary
            SET "KH/s" = ?,
                last_mhashes_cumulative = ?,
                last_mhashes_timestamp = ?
            WHERE miner_id = ?;
        """, (khs, current_mhashes, latest_log['created_at'], miner_id))
        # --------------------------------------------------------------------------

def update_general_summary_stats(conn):
    """
    Efficiently updates the non-calculated stats like Temperature, Valid Blocks, etc.
    This function will INSERT new rows if they don't exist.
    """
    keys_to_summarize = ('Temperature', 'Valid blocks', 'Best difficulty', 'Total MHashes')
    
    pivot_cases = ",\n".join([f"                MAX(CASE WHEN log_key = '{key}' THEN log_value END) AS \"{key}\"" for key in keys_to_summarize])

    upsert_sql = f"""
        INSERT INTO miner_summary (miner_id, last_updated, "Temperature", "Valid blocks", "Best difficulty", "Total MHashes")
        SELECT
            m.id AS miner_id,
            ? AS last_updated,
            {pivot_cases}
        FROM
            miners m
        JOIN
            miner_logs ml ON m.id = ml.miner_id
        WHERE
            ml.log_key IN (?{',?' * (len(keys_to_summarize) - 1)}) 
            AND ml.created_at >= ?
        GROUP BY
            m.id
        ON CONFLICT(miner_id) DO UPDATE SET
            last_updated = excluded.last_updated,
            "Temperature" = COALESCE(excluded."Temperature", "Temperature"),
            "Valid blocks" = COALESCE(excluded."Valid blocks", "Valid blocks"),
            "Best difficulty" = COALESCE(excluded."Best difficulty", "Best difficulty"),
            "Total MHashes" = COALESCE(excluded."Total MHashes", "Total MHashes");
    """
    
    now_iso = datetime.now(UTC).isoformat()
    cutoff_time = datetime.now(UTC) - timedelta(minutes=DATA_WINDOW_MINUTES)
    cutoff_iso = cutoff_time.isoformat()
    params = (now_iso,) + keys_to_summarize + (cutoff_iso,)
    
    cursor = conn.cursor()
    cursor.execute(upsert_sql, params)
    return cursor.rowcount

if __name__ == "__main__":
    print("Starting The Shepherd Data Summarizer...")
    try:
        while True:
            try:
                with get_db_connection() as conn:
                    with conn:
                        # General stats run first to ensure the row exists
                        update_general_summary_stats(conn)
                        # Hashrate summary now only UPDATES the existing row
                        update_hashrate_summary(conn)
                    print(f"[{datetime.now(UTC).isoformat()}] Summarization complete.")
            except Exception as e:
                print(f"An error occurred during summarization: {e}")
            
            time.sleep(AGGREGATION_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nShutting down summarizer...")

