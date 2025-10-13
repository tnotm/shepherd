import sqlite3
import os
import csv
import io
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Needed for flashing messages

DATABASE_FILE = 'shepherd.db'

# --- Database Functions ---

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Create the main miners table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS miners (
                id INTEGER PRIMARY KEY,
                miner_id TEXT NOT NULL UNIQUE,
                chipset TEXT,
                attrs_idVendor TEXT,
                attrs_idProduct TEXT,
                attrs_serial TEXT,
                tty_symlink TEXT,
                nerdminer_rom TEXT,
                nerdminer_vrs TEXT,
                status TEXT DEFAULT 'unknown',
                last_seen TIMESTAMP
            );
        ''')
        # Create the logs table for real-time data
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS miner_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                miner_id INTEGER NOT NULL,
                log_key TEXT NOT NULL,
                log_value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (miner_id) REFERENCES miners (id)
            );
        ''')
        # Create an index for faster lookups
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_miner_logs_created_at
            ON miner_logs (created_at);
        ''')
        conn.commit()
    print("Database initialized successfully.")

def get_db_connection():
    """Establishes a connection to the SQLite database with a timeout."""
    conn = sqlite3.connect(DATABASE_FILE, timeout=10) # 10-second timeout for concurrency
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;') # Enable Write-Ahead Logging
    return conn

# --- Flask Routes ---

@app.route('/')
def index():
    """Main dashboard view."""
    conn = get_db_connection()
    miners = conn.execute('SELECT * FROM miners ORDER BY miner_id;').fetchall()
    conn.close()
    return render_template('index.html', miners=miners)

@app.route('/config')
def config():
    """Configuration page view."""
    return render_template('config.html')

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    """Handles the CSV upload for miner configuration."""
    if 'miner_file' not in request.files:
        flash('No file part in the request.', 'error')
        return redirect(url_for('config'))

    file = request.files['miner_file']
    if file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('config'))

    if file and file.filename.endswith('.csv'):
        try:
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_reader = csv.DictReader(stream)
            
            miners_to_upsert = []
            for row in csv_reader:
                miners_to_upsert.append(row)

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

