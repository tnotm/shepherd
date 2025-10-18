# shepherd/database.py
# V.0.0.0.6
# Description: Database initialization and schema management for Shepherd.

import sqlite3
import os

# --- Configuration ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
DATABASE_FILE = os.path.join(DATA_DIR, 'shepherd.db')

# --- Database & Helper Functions ---
def get_db_connection():
    """Establishes a connection to the SQLite database."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def _add_column_if_not_exists(conn, table_name, column_name, column_def):
    """Utility function to add a column to a table if it doesn't already exist."""
    cursor = conn.execute(f"PRAGMA table_info({table_name});")
    columns = [row['name'] for row in cursor.fetchall()]
    if column_name not in columns:
        print(f"Adding column '{column_name}' to table '{table_name}'...")
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def};")

def init_db():
    """Initializes the database and creates/updates tables if they don't exist."""
    with get_db_connection() as conn:
        print("Verifying database tables...")
        
        # Miners Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS miners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                miner_id TEXT UNIQUE NOT NULL,
                chipset TEXT,
                dev_path TEXT UNIQUE,
                port_path TEXT,
                location_notes TEXT,
                attrs_idVendor TEXT,
                attrs_idProduct TEXT,
                attrs_serial TEXT,
                nerdminer_rom TEXT,
                nerdminer_vrs TEXT,
                status TEXT DEFAULT 'unknown',
                last_seen TEXT
            );
        """)
        _add_column_if_not_exists(conn, 'miners', 'port_path', 'TEXT')
        _add_column_if_not_exists(conn, 'miners', 'location_notes', 'TEXT')

        # Unconfigured Devices Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS unconfigured_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dev_path TEXT UNIQUE NOT NULL,
                port_path TEXT UNIQUE,
                vendor_id TEXT,
                product_id TEXT,
                serial_number TEXT,
                discovered_at TEXT NOT NULL
            );
        """)
        _add_column_if_not_exists(conn, 'unconfigured_devices', 'port_path', 'TEXT')
        # Create a unique index separately to safely add constraint to existing tables.
        # This will only enforce uniqueness where the value is not NULL.
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unconfigured_port_path ON unconfigured_devices (port_path) WHERE port_path IS NOT NULL;")

        # Raw Logs Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS miner_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                miner_id INTEGER,
                log_key TEXT NOT NULL,
                log_value TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (miner_id) REFERENCES miners (id) ON DELETE CASCADE
            );
        """)
        
        # Summary Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS miner_summary (
                miner_id INTEGER PRIMARY KEY,
                last_updated TEXT, "KH/s" TEXT, "Temperature" TEXT,
                "Valid blocks" TEXT, "Best difficulty" TEXT, "Total MHashes" TEXT,
                "Submits" TEXT, "Shares" TEXT, "Time mining" TEXT,
                "Block templates" TEXT,
                last_mhashes_cumulative REAL, last_mhashes_timestamp TEXT,
                FOREIGN KEY (miner_id) REFERENCES miners (id) ON DELETE CASCADE
            );
        """)
        
        # Pools Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pool_name TEXT NOT NULL UNIQUE,
                pool_url TEXT NOT NULL,
                pool_port INTEGER NOT NULL,
                pool_user TEXT NOT NULL,
                pool_pass TEXT DEFAULT 'x',
                is_active INTEGER DEFAULT 0
            );
        """)
        
        # Coin Addresses Table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS coin_addresses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coin_ticker TEXT NOT NULL,
                address TEXT NOT NULL UNIQUE,
                label TEXT
            );
        """)
        print("Database tables verified and updated.")

