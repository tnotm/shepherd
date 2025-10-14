import sqlite3
import os
import csv
import io
import json
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Configuration ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
DATABASE_FILE = os.path.join(DATA_DIR, 'shepherd.db')
PRICE_CACHE_FILE = os.path.join(DATA_DIR, 'btc_price.json')

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
        # Summary Table - Updated with all new fields
        conn.execute("""
            CREATE TABLE IF NOT EXISTS miner_summary (
                miner_id INTEGER PRIMARY KEY,
                last_updated TEXT,
                "KH/s" TEXT,
                "Temperature" TEXT,
                "Valid blocks" TEXT,
                "Best difficulty" TEXT,
                "Total MHashes" TEXT,
                "Submits" TEXT,
                "Shares" TEXT,
                "Time mining" TEXT,
                last_mhashes_cumulative REAL,
                last_mhashes_timestamp TEXT,
                FOREIGN KEY (miner_id) REFERENCES miners (id) ON DELETE CASCADE
            );
        """)
        print("Database tables verified.")
        
def get_btc_price_data():
    """Reads the cached BTC price data from the local JSON file."""
    try:
        with open(PRICE_CACHE_FILE, 'r') as f:
            data = json.load(f)
            return {
                "price_usd": data.get("price_usd", 0),
                "change_24h": data.get("change_24h", 0)
            }
    except (FileNotFoundError, json.JSONDecodeError):
        # Return a default placeholder if the file doesn't exist or is invalid
        return {
            "price_usd": "N/A",
            "change_24h": 0.0
        }

# --- Flask Routes ---

@app.route('/')
def index():
    with get_db_connection() as conn:
        # This query now joins miners with the summary table to get all data at once
        query = """
            SELECT 
                m.miner_id, m.nerdminer_vrs, m.status,
                s.* FROM miners m
            LEFT JOIN miner_summary s ON m.id = s.miner_id
            ORDER BY m.miner_id;
        """
        miners = conn.execute(query).fetchall()

        # Calculate Herd Stats
        total_miners = len(miners)
        online_miners = 0
        total_hash_khs = 0.0
        total_shares = 0
        best_difficulty = 0.0

        for miner in miners:
            if miner['status'] == 'online':
                online_miners += 1
            try:
                if miner['KH/s']:
                    total_hash_khs += float(miner['KH/s'])
            except (ValueError, TypeError):
                pass
            try:
                if miner['Shares']:
                    total_shares += int(miner['Shares'])
            except (ValueError, TypeError):
                pass
            try:
                if miner['Best difficulty'] and float(miner['Best difficulty']) > best_difficulty:
                    best_difficulty = float(miner['Best difficulty'])
            except (ValueError, TypeError):
                pass

        herd_stats = {
            "total_miners": total_miners,
            "online_miners": online_miners,
            "total_hash_khs": total_hash_khs,
            "total_shares": total_shares,
            "best_difficulty": best_difficulty,
            "btc_price_data": get_btc_price_data()
        }

    return render_template('index.html', miners=miners, herd_stats=herd_stats)

@app.route('/kiosk')
def kiosk():
    # This route reuses the same logic as the main index page for herd stats
    with get_db_connection() as conn:
        query = "SELECT m.miner_id, m.nerdminer_vrs, m.status, s.* FROM miners m LEFT JOIN miner_summary s ON m.id = s.miner_id ORDER BY m.miner_id;"
        miners = conn.execute(query).fetchall()

        total_miners = len(miners)
        online_miners = sum(1 for m in miners if m['status'] == 'online')
        total_hash_khs = sum(float(m['KH/s'] or 0) for m in miners)
        total_shares = sum(int(m['Shares'] or 0) for m in miners)
        best_difficulty = max([float(m['Best difficulty'] or 0) for m in miners] or [0])
        
        btc_data = get_btc_price_data()

        herd_stats = {
            "total_miners": total_miners,
            "online_miners": online_miners,
            "total_hash_khs": total_hash_khs,
            "total_shares": total_shares,
            "best_difficulty": best_difficulty,
            "btc_price": f"{btc_data['price_usd']:.2f}" if isinstance(btc_data['price_usd'], (int, float)) else "N/A",
            "btc_change": btc_data['change_24h']
        }
    return render_template('kiosk.html', miners=miners, herd_stats=herd_stats)

@app.route('/config')
def config():
    return render_template('config.html')

@app.route('/upload_miners', methods=['POST'])
def upload_miners():
    if 'miner_file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('config'))
    
    file = request.files['miner_file']
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('config'))

    if file and file.filename.endswith('.csv'):
        try:
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_reader = csv.DictReader(stream)
            miners_to_upsert = [row for row in csv_reader]

            if not miners_to_upsert:
                flash('CSV file is empty or headers are incorrect.', 'error')
                return redirect(url_for('config'))

            with get_db_connection() as conn:
                for miner in miners_to_upsert:
                    conn.execute('''
                        INSERT INTO miners (miner_id, chipset, attrs_idVendor, attrs_idProduct, attrs_serial, tty_symlink, nerdminer_rom, nerdminer_vrs)
                        VALUES (:miner_id, :chipset, :attrs_idVendor, :attrs_idProduct, :attrs_serial, :tty_symlink, :nerdminer_rom, :nerdminer_vrs)
                        ON CONFLICT(miner_id) DO UPDATE SET
                            chipset=excluded.chipset,
                            attrs_idVendor=excluded.attrs_idVendor,
                            attrs_idProduct=excluded.attrs_idProduct,
                            attrs_serial=excluded.attrs_serial,
                            tty_symlink=excluded.tty_symlink,
                            nerdminer_rom=excluded.nerdminer_rom,
                            nerdminer_vrs=excluded.nerdminer_vrs;
                    ''', miner)
                conn.commit()
            flash(f'Successfully uploaded and processed {len(miners_to_upsert)} miners.', 'success')
        except Exception as e:
            flash(f'An error occurred: {e}', 'error')
        return redirect(url_for('config'))
    else:
        flash('Invalid file type. Please upload a .csv file.', 'error')
        return redirect(url_for('config'))

@app.route('/raw_logs')
def raw_logs():
    with get_db_connection() as conn:
        logs = conn.execute("""
            SELECT l.created_at, m.miner_id, l.log_key, l.log_value 
            FROM miner_logs l
            JOIN miners m ON l.miner_id = m.id
            ORDER BY l.id DESC LIMIT 30
        """).fetchall()
    return render_template('raw_logs.html', logs=logs)

@app.route('/summary')
def summary():
    with get_db_connection() as conn:
        summary_data = conn.execute("""
            SELECT m.miner_id, s.*
            FROM miner_summary s
            JOIN miners m ON s.miner_id = m.id
            ORDER BY m.miner_id
        """).fetchall()
    return render_template('summary.html', summary_data=summary_data)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)

