import sqlite3
from flask import Flask, jsonify, render_template, request, flash, redirect, url_for
import csv
import io
import os

DB_FILE = 'shepherd.db'

app = Flask(__name__)
# A secret key is required to use the 'flash' messaging system
app.secret_key = os.urandom(24)

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create the 'miners' table if it doesn't exist. This table holds static info.
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
        hash_rate REAL,
        temperature REAL,
        last_seen TEXT
    );
    ''')
    
    # Create the 'miner_logs' table for time-series data.
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS miner_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        miner_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        metric_key TEXT NOT NULL,
        metric_value TEXT,
        FOREIGN KEY (miner_id) REFERENCES miners (id)
    );
    ''')

    # Create an index for faster queries on the logs table
    cursor.execute('''
    CREATE INDEX IF NOT EXISTS idx_miner_logs_timestamp ON miner_logs (miner_id, timestamp);
    ''')
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def get_db_connection():
    """Establishes a connection to the database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # This allows accessing columns by name
    return conn

@app.route('/')
def index():
    """Serves the main dashboard page."""
    return render_template('index.html')

@app.route('/config')
def config():
    """Serves the configuration page."""
    return render_template('config.html')

@app.route('/upload', methods=['POST'])
def upload_csv():
    """Handles the CSV file upload and populates the database."""
    if 'file' not in request.files:
        flash('No file part in the request.', 'error')
        return redirect(url_for('config'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('No file selected for uploading.', 'error')
        return redirect(url_for('config'))
        
    if file and file.filename.endswith('.csv'):
        try:
            # Read the file content as a string and process it
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_reader = csv.reader(stream)
            next(csv_reader) # Skip the header row
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            insert_count = 0
            for row in csv_reader:
                # Use INSERT OR IGNORE to add new miners without causing errors for existing ones
                insert_sql = """
                INSERT OR IGNORE INTO miners (id, miner_id, chipset, attrs_idVendor, attrs_idProduct, attrs_serial, tty_symlink, nerdminer_rom, nerdminer_vrs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """
                cursor.execute(insert_sql, row)
                if cursor.rowcount > 0:
                    insert_count += 1
            
            conn.commit()
            conn.close()
            
            flash(f'Successfully processed CSV. Added {insert_count} new miners to the database.', 'success')
            
        except Exception as e:
            flash(f'An error occurred while processing the file: {e}', 'error')
            
        return redirect(url_for('config'))
    else:
        flash('Invalid file type. Please upload a .csv file.', 'error')
        return redirect(url_for('config'))

@app.route('/api/miners')
def get_miners_data():
    """Provides miner data as a JSON API endpoint."""
    try:
        conn = get_db_connection()
        # Query for all miners, ordering by their ID
        miners = conn.execute('SELECT * FROM miners ORDER BY id').fetchall()
        conn.close()
        # Convert the database rows to a list of dictionaries
        miners_list = [dict(miner) for miner in miners]
        return jsonify(miners_list)
    except Exception as e:
        # Provide a clear error message if the database query fails
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Initialize the database before running the app
    init_db()
    # Run the app on all available network interfaces
    # The debug=True setting allows for auto-reloading during development
    app.run(host='0.0.0.0', port=5000, debug=True)

