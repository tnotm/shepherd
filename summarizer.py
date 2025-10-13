import sqlite3
import time
from datetime import datetime, timedelta

# --- Configuration ---
DATABASE_FILE = 'shepherd.db'
# How often the summarizer runs
AGGREGATION_INTERVAL_SECONDS = 5 
# How far back to look in the raw logs to find the latest data point
DATA_WINDOW_MINUTES = 2 

# --- Database Functions ---

def get_db_connection():
    """Establishes a connection to the SQLite database."""
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
    
    # These are the specific log keys we want to display on the dashboard.
    # The SQL query will pivot these into columns.
    keys_to_summarize = ('KH/s', 'Temperature', 'Valid blocks', 'Best difficulty', 'Total MHashes')
    
    # We use an "UPSERT" (UPDATE or INSERT) strategy.
    # This query is complex, but very efficient. It finds the most recent value for each
    # of our target keys within the last few minutes and inserts or replaces the
    # summary row for each miner.
    upsert_sql = f"""
        INSERT INTO miner_summary (miner_id, last_updated, {', '.join([f'"{key}"' for key in keys_to_summarize])})
        SELECT
            m.id AS miner_id,
            MAX(l.created_at) as last_updated,
            {', '.join([f"MAX(CASE WHEN l.log_key = '{key}' THEN l.log_value END)" for key in keys_to_summarize])}
        FROM miners m
        JOIN miner_logs l ON m.id = l.miner_id
        WHERE
            l.log_key IN ({', '.join(['?'] * len(keys_to_summarize))})
            AND l.created_at >= ?
        GROUP BY m.id
        ON CONFLICT(miner_id) DO UPDATE SET
            last_updated = excluded.last_updated,
            {', '.join([f'"{key}" = excluded."{key}"' for key in keys_to_summarize])};
    """

    try:
        with get_db_connection() as conn:
            cutoff_time = datetime.utcnow() - timedelta(minutes=DATA_WINDOW_MINUTES)
            params = keys_to_summarize + (cutoff_time,)
            cursor = conn.cursor()
            cursor.execute(upsert_sql, params)
            conn.commit()
            print(f"Summarization complete. Updated {cursor.rowcount} rows.")
    except Exception as e:
        print(f"An error occurred during summarization: {e}")


if __name__ == "__main__":
    print("Starting The Shepherd Data Summarizer...")
    
    # We need to ensure the summary table exists before we start.
    # This will be handled by the main app.py, but it's safe to have it here too.
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

    # Main loop
    try:
        while True:
            summarize_data()
            time.sleep(AGGREGATION_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nShutting down summarizer...")
