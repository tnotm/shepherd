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
                attrs_idVendor TEXT,
                attrs_idProduct TEXT,
                attrs_serial TEXT,
                tty_symlink TEXT,
                nerdminer_rom TEXT,
                nerdminer_vrs TEXT,
                status TEXT DEFAULT 'unknown',
                last_seen TEXT
            );
        """)
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
                last_mhashes_cumulative REAL, last_mhashes_timestamp TEXT,
                FOREIGN KEY (miner_id) REFERENCES miners (id) ON DELETE CASCADE
            );
        """)
        # --- NEW: Pools Table ---
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
        # --- NEW: Coin Addresses Table ---
        conn.execute("""
            CREATE TABLE IF NOT EXISTS coin_addresses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coin_ticker TEXT NOT NULL,
                address TEXT NOT NULL UNIQUE,
                label TEXT
            );
        """)
        print("Database tables verified.")

