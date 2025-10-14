import sqlite3
import os
import csv
import io
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.urandom(24)

# --- Configuration ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
DATABASE_FILE = os.path.join(DATA_DIR, 'shepherd.db')

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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS miner_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                miner_id INTEGER,
                log_key TEXT NOT NULL,
                log_value TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (miner_id) REFERENCES miners (id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS miner_summary (
                miner_id INTEGER PRIMARY KEY,
                last_updated TEXT,
                "KH/s" TEXT,
                "Temperature" TEXT,
                "Valid blocks" TEXT,
                "Best difficulty" TEXT,
                "Total MHashes" TEXT,
                last_mhashes_cumulative REAL DEFAULT 0.0,
                last_mhashes_timestamp TEXT,
                FOREIGN KEY (miner_id) REFERENCES miners (id)
            );
        """)
        print("Database tables verified.")

# --- Flask Routes ---
@app.route('/')
def index():
    conn = get_db_connection()
    miners_data = conn.execute("""
        SELECT 
            m.miner_id, m.status, m.tty_symlink, m.nerdminer_vrs,
            s.last_updated, s."KH/s", s."Temperature", s."Valid blocks", s."Best difficulty"
        FROM miners m
        LEFT JOIN miner_summary s ON m.id = s.miner_id
        ORDER BY m.miner_id;
    """).fetchall()
    conn.close()
    return render_template('index.html', miners=miners_data)

@app.route('/config', methods=['GET'])
def config():
    return render_template('config.html')

@app.route('/raw_logs')
def raw_logs():
    conn = get_db_connection()
    logs = conn.execute("""
        SELECT l.created_at, m.miner_id, l.log_key, l.log_value 
        FROM miner_logs l
        JOIN miners m ON l.miner_id = m.id
        ORDER BY l.id DESC LIMIT 30
    """).fetchall()
    conn.close()
    return render_template('raw_logs.html', logs=logs)

@app.route('/summary')
def summary():
    conn = get_db_connection()
    summary_data = conn.execute("""
        SELECT m.miner_id, s.*
        FROM miner_summary s
        JOIN miners m ON s.miner_id = m.id
        ORDER BY m.miner_id
    """).fetchall()
    conn.close()
    return render_template('summary.html', summary_data=summary_data)


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
                flash('CSV file is empty or malformed.', 'error')
                return redirect(url_for('config'))

            conn = get_db_connection()
            cursor = conn.cursor()

            for miner in miners_to_upsert:
                cursor.execute('''
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
            conn.close()
            flash(f'Successfully uploaded and processed {len(miners_to_upsert)} miners.', 'success')

        except Exception as e:
            flash(f'An error occurred: {e}', 'error')

        return redirect(url_for('config'))
    else:
        flash('Invalid file type. Please upload a .csv file.', 'error')
        return redirect(url_for('config'))


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)

