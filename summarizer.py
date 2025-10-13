import sqlite3
import time
import os
from datetime import datetime, timedelta, UTC

# --- Configuration ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
DATABASE_FILE = os.path.join(DATA_DIR, 'shepherd.db')
AGGREGATION_INTERVAL_SECONDS = 5 
DATA_WINDOW_MINUTES = 2 

# --- Database Functions ---
def get_db_connection():
    """Establishes a connection to the SQLite database."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

# --- Main Application Logic ---
def summarize_data():
    """
    Connects to the database, aggregates the latest miner data from the raw logs,
    and upserts it into the miner_summary table.
    """
    print("Running summarization task...")
    
    keys_to_summarize = ('KH/s', 'Temperature', 'Valid blocks', 'Best difficulty', 'Total MHashes')
    
    pivot_cases = ",\n".join([f"                MAX(CASE WHEN log_key = '{key}' THEN log_value END) AS '{key}'" for key in keys_to_summarize])

    upsert_sql = f"""
        INSERT INTO miner_summary (miner_id, last_updated, "KH/s", "Temperature", "Valid blocks", "Best difficulty", "Total MHashes")
        SELECT
            m.id AS miner_id,
            DATETIME('now', 'utc') AS last_updated,
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
            "KH/s" = COALESCE(excluded."KH/s", "KH/s"),
            "Temperature" = COALESCE(excluded."Temperature", "Temperature"),
            "Valid blocks" = COALESCE(excluded."Valid blocks", "Valid blocks"),
            "Best difficulty" = COALESCE(excluded."Best difficulty", "Best difficulty"),
            "Total MHashes" = COALESCE(excluded."Total MHashes", "Total MHashes");
    """

    try:
        with get_db_connection() as conn:
            cutoff_time = datetime.now(UTC) - timedelta(minutes=DATA_WINDOW_MINUTES)
            cutoff_iso = cutoff_time.isoformat()
            params = keys_to_summarize + (cutoff_iso,)
            cursor = conn.cursor()
            cursor.execute(upsert_sql, params)
            conn.commit()
            print(f"Summarization complete. Updated {cursor.rowcount} rows.")
    except Exception as e:
        print(f"An error occurred during summarization: {e}")

if __name__ == "__main__":
    print("Starting The Shepherd Data Summarizer...")
    
    try:
        with get_db_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS miner_summary (
                    miner_id INTEGER PRIMARY KEY,
                    last_updated TEXT,
                    "KH/s" TEXT,
                    "Temperature" TEXT,
                    "Valid blocks" TEXT,
                    "Best difficulty" TEXT,
                    "Total MHashes" TEXT,
                    FOREIGN KEY (miner_id) REFERENCES miners (id)
                );
            """)
            print("Database tables verified.")
    except Exception as e:
        print(f"Could not create or verify summary table: {e}")

    try:
        while True:
            summarize_data()
            time.sleep(AGGREGATION_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nShutting down summarizer...")

