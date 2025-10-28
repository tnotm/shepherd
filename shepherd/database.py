# shepherd/database.py
# V.0.0.0.9
# Description: Database initialization and schema management for Shepherd.
# ADDED: mac_address column to stray_devices table.
# FIXED: Renamed unconfigured_devices to stray_devices and handle potential recreation.

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

def _table_exists(conn, table_name):
    """Checks if a table exists in the database."""
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table_name,))
    return cursor.fetchone() is not None

def _add_column_if_not_exists(conn, table_name, column_name, column_def):
    """Utility function to add a column to a table if it doesn't already exist."""
    if not _table_exists(conn, table_name):
        print(f"Table '{table_name}' does not exist. Skipping column add for '{column_name}'.")
        return # Skip if table doesn't exist

    cursor = conn.execute(f"PRAGMA table_info({table_name});")
    columns = [row['name'] for row in cursor.fetchall()]
    if column_name not in columns:
        print(f"Adding column '{column_name}' to table '{table_name}'...")
        try:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def};")
            print(f"Successfully added column '{column_name}'.") # Confirmation
        except sqlite3.Error as e:
            print(f"ERROR adding column '{column_name}' to '{table_name}': {e}") # Log error
    else:
         print(f"Column '{column_name}' already exists in table '{table_name}'.") # Added else


def init_db():
    """Initializes the database and creates/updates tables if they don't exist."""
    with get_db_connection() as conn:
        print("Verifying database tables...")
        
        # --- Miners Table ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS miners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                miner_id TEXT UNIQUE NOT NULL,
                chipset TEXT,
                dev_path TEXT, 
                port_path TEXT, 
                location_notes TEXT,
                attrs_idVendor TEXT,
                attrs_idProduct TEXT,
                attrs_serial TEXT, 
                mac_address TEXT UNIQUE, 
                nerdminer_rom TEXT, 
                nerdminer_vrs TEXT, 
                status TEXT DEFAULT 'Inactive', 
                state TEXT, 
                currency TEXT, 
                pool_url TEXT, 
                wallet_address TEXT, 
                last_seen TEXT,
                UNIQUE (port_path, attrs_serial) 
            );
        """)
        # Add columns using the helper function
        _add_column_if_not_exists(conn, 'miners', 'port_path', 'TEXT')
        _add_column_if_not_exists(conn, 'miners', 'location_notes', 'TEXT')
        _add_column_if_not_exists(conn, 'miners', 'status', 'TEXT DEFAULT \'Inactive\'')
        _add_column_if_not_exists(conn, 'miners', 'state', 'TEXT')
        _add_column_if_not_exists(conn, 'miners', 'currency', 'TEXT')
        _add_column_if_not_exists(conn, 'miners', 'pool_url', 'TEXT')
        _add_column_if_not_exists(conn, 'miners', 'wallet_address', 'TEXT')
        _add_column_if_not_exists(conn, 'miners', 'mac_address', 'TEXT UNIQUE') 

        # --- Stray Devices Table ---
        # Handle potential existence of old 'unconfigured_devices' table
        if _table_exists(conn, 'unconfigured_devices') and not _table_exists(conn, 'stray_devices'):
            print("Renaming old 'unconfigured_devices' table to 'stray_devices'...")
            try:
                # Need to drop index before renaming if it exists from old schema
                conn.execute("DROP INDEX IF EXISTS idx_unconfigured_port_path;") 
                conn.execute("ALTER TABLE unconfigured_devices RENAME TO stray_devices;")
                print("Table renamed successfully.")
            except sqlite3.Error as e:
                print(f"ERROR renaming table: {e}. Attempting to drop old and create new.")
                conn.execute("DROP TABLE IF EXISTS unconfigured_devices;") # Drop if rename failed
                conn.execute("DROP TABLE IF EXISTS stray_devices;") # Ensure clean state

        # Create stray_devices if it doesn't exist after potential rename/drop
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stray_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dev_path TEXT UNIQUE NOT NULL, 
                port_path TEXT NOT NULL, 
                vendor_id TEXT,
                product_id TEXT,
                serial_number TEXT, -- Original USB Serial or Placeholder
                mac_address TEXT, -- Captured MAC Address (Can be NULL)
                chipset TEXT, 
                discovered_at TEXT NOT NULL,
                status TEXT DEFAULT 'Initializing', 
                state TEXT DEFAULT 'Detected', 
                dumped_pool_url TEXT, 
                dumped_wallet_address TEXT, 
                dumped_firmware_version TEXT, 
                UNIQUE (port_path, serial_number) 
            );
        """)
        # Add mac_address column specifically if stray_devices table already existed
        _add_column_if_not_exists(conn, 'stray_devices', 'mac_address', 'TEXT') # Will add UNIQUE constraint if needed? No, ALTER TABLE ADD COLUMN doesn't easily support UNIQUE here. Manual addition might be needed if uniqueness is critical on strays. Let's assume non-unique for now on strays table.


        # --- Raw Logs Table ---
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
        
        # --- Summary Table ---
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
        
        # --- Pools Table ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pool_name TEXT NOT NULL UNIQUE, pool_url TEXT NOT NULL,
                pool_port INTEGER NOT NULL, pool_user TEXT NOT NULL,
                pool_pass TEXT DEFAULT 'x', is_active INTEGER DEFAULT 0
            );
        """)
        
        # --- Coin Addresses Table ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS coin_addresses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coin_ticker TEXT NOT NULL, address TEXT NOT NULL UNIQUE, label TEXT
            );
        """)
        print("Database tables verified and updated.")

