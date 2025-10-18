# shepherd/routes.py -- V.0.0.0.9
import sqlite3
import os
import csv
import io
import json
import socket
from flask import Blueprint, render_template, request, redirect, url_for, flash
from .database import get_db_connection
from datetime import datetime

try:
    import psutil
except ImportError:
    psutil = None

bp = Blueprint('main', __name__)

# --- Configuration & Helpers ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
PRICE_CACHE_FILE = os.path.join(DATA_DIR, 'btc_price.json')

def get_btc_price_data():
    """Reads the cached BTC price data."""
    try:
        with open(PRICE_CACHE_FILE, 'r') as f:
            data = json.load(f)
            return {"price_usd": data.get("price_usd", 0), "change_24h": data.get("change_24h", 0)}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"price_usd": "N/A", "change_24h": 0.0}

def format_uptime(seconds):
    """Formats a duration in seconds into a human-readable string."""
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d > 0: parts.append(f"{int(d)}d")
    if h > 0: parts.append(f"{int(h)}h")
    if m > 0: parts.append(f"{int(m)}m")
    return " ".join(parts) if parts else f"{int(s)}s"

# --- Main & Desktop Routes ---
@bp.route('/')
def index():
    with get_db_connection() as conn:
        query = "SELECT m.id, m.miner_id, m.nerdminer_vrs, m.status, s.* FROM miners m LEFT JOIN miner_summary s ON m.id = s.miner_id ORDER BY m.miner_id;"
        miners = conn.execute(query).fetchall()
        total_miners = len(miners)
        online_miners = sum(1 for m in miners if m['status'] == 'online')
        total_hash_khs = sum(float(m['KH/s'] or 0) for m in miners)
        total_shares = sum(int(m['Shares'] or 0) for m in miners)
        # ENHANCEMENT: Calculate total block templates for the header
        total_block_templates = sum(int(m['Block templates'] or 0) for m in miners)
        best_difficulty = max([float(m['Best difficulty'] or 0) for m in miners] or [0])
        herd_stats = {
            "total_miners": total_miners, "online_miners": online_miners,
            "total_hash_khs": total_hash_khs, "total_shares": total_shares,
            "best_difficulty": best_difficulty,
            "total_block_templates": total_block_templates, # ENHANCEMENT: Added to dictionary
            "btc_price_data": get_btc_price_data()
        }
    return render_template('index.html', miners=miners, herd_stats=herd_stats)

# --- Kiosk & Dashboard Routes ---
@bp.route('/kiosk') 
def kiosk():
    with get_db_connection() as conn:
        query = "SELECT m.miner_id, m.status, s.* FROM miners m LEFT JOIN miner_summary s ON m.id = s.miner_id ORDER BY m.miner_id;"
        miners = conn.execute(query).fetchall()
        total_miners = len(miners)
        online_miners = sum(1 for m in miners if m['status'] == 'online')
        total_hash_khs = sum(float(m['KH/s'] or 0) for m in miners)
        total_shares = sum(int(m['Shares'] or 0) for m in miners)
        total_block_templates = sum(int(m['Block templates'] or 0) for m in miners)
        btc_data = get_btc_price_data()
        herd_stats = {
            "total_miners": total_miners, "online_miners": online_miners,
            "total_hash_khs": total_hash_khs, "total_shares": total_shares,
            "total_block_templates": total_block_templates,
            "btc_price": f"{btc_data['price_usd']:.2f}" if isinstance(btc_data['price_usd'], (int, float)) else "N/A",
            "btc_change": btc_data['change_24h']
        }
    return render_template('kiosk.html', miners=miners, herd_stats=herd_stats)

@bp.route('/dashboards')
def dashboards():
    return render_template('dashboards.html')

@bp.route('/dash/health')
def dash_health():
    # ... (code for this route is correct)
    with get_db_connection() as conn:
        query = "SELECT m.id, m.miner_id, m.status, s.'KH/s', s.Shares, s.'Block templates' FROM miners m LEFT JOIN miner_summary s ON m.id = s.miner_id ORDER BY m.miner_id;"
        miners = conn.execute(query).fetchall()
        total_hash_khs = sum(float(m['KH/s'] or 0) for m in miners)
        total_shares = sum(int(m['Shares'] or 0) for m in miners)
        total_block_templates = sum(int(m['Block templates'] or 0) for m in miners)
        btc_data = get_btc_price_data()
        herd_stats = {
            "total_hash_khs": total_hash_khs, "total_shares": total_shares,
            "total_block_templates": total_block_templates,
            "btc_price": f"{btc_data['price_usd']:.2f}" if isinstance(btc_data['price_usd'], (int, float)) else "N/A",
            "btc_change": btc_data['change_24h']
        }
    return render_template('dash_health.html', miners=miners, herd_stats=herd_stats)

@bp.route('/dash/nerdminer')
def dash_nerdminer():
    # Using placeholder data as per our last implementation
    stats = {
        'current_block': '812345',
        'time_since_block': '5m 12s',
        'hash_rate': '78.45',
        'difficulty': '52.3T'
    }
    return render_template('dash_nerdminer.html', stats=stats)

@bp.route('/dash/matrix')
def dash_matrix():
    with get_db_connection() as conn:
        query = "SELECT m.status, s.* FROM miners m LEFT JOIN miner_summary s ON m.id = s.miner_id;"
        miners = conn.execute(query).fetchall()
        
        total_hash_khs = sum(float(m['KH/s'] or 0) for m in miners)
        total_shares = sum(int(m['Shares'] or 0) for m in miners)
        total_block_templates = sum(int(m['Block templates'] or 0) for m in miners)
        btc_data = get_btc_price_data()
        
        herd_stats = {
            "total_hash_khs": total_hash_khs,
            "total_shares": total_shares,
            "total_block_templates": total_block_templates,
            "btc_price_data": btc_data
        }
    return render_template('dash_matrix.html', herd_stats=herd_stats)

# --- Farm Detail Routes ---
@bp.route('/details')
def details():
    return render_template('details.html')

@bp.route('/details/system')
def details_system():
    # ... (code for this route is correct)
    stats = {'psutil_installed': bool(psutil)}
    if psutil:
        stats['hostname'] = socket.gethostname()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80)); stats['ip_address'] = s.getsockname()[0]; s.close()
        except Exception:
            stats['ip_address'] = 'N/A'
        stats['cpu_percent'] = psutil.cpu_percent(interval=1)
        svmem = psutil.virtual_memory()
        stats['ram_percent'] = svmem.percent
        swap = psutil.swap_memory()
        stats['swap_percent'] = swap.percent
        disk = psutil.disk_usage('/')
        stats['disk_percent'] = disk.percent
        try:
            boot_time_timestamp = psutil.boot_time()
            uptime_seconds = datetime.now().timestamp() - boot_time_timestamp
            stats['uptime'] = format_uptime(uptime_seconds)
        except Exception:
            stats['uptime'] = 'N/A'
        try:
            temps = psutil.sensors_temperatures()
            if 'cpu_thermal' in temps:
                stats['cpu_temp'] = f"{temps['cpu_thermal'][0].current:.1f}°C"
            else:
                stats['cpu_temp'] = 'N/A'
        except (AttributeError, IndexError, KeyError):
             stats['cpu_temp'] = 'N/A'
    return render_template('details_system.html', stats=stats)

@bp.route('/details/miner/<int:miner_id>')
def details_miner(miner_id):
    # ... (code for this route is correct)
    with get_db_connection() as conn:
        query = "SELECT m.*, s.* FROM miners m LEFT JOIN miner_summary s ON m.id = s.miner_id WHERE m.id = ?;"
        miner = conn.execute(query, (miner_id,)).fetchone()
    if miner is None:
        flash(f"Miner with ID {miner_id} not found.", "error")
        return redirect(url_for('main.index'))
    return render_template('details_miner.html', miner=miner)

# --- Config & Management Routes ---
@bp.route('/config')
def config():
    # ... (code for this route is correct)
    with get_db_connection() as conn:
        miners = conn.execute("SELECT * FROM miners ORDER BY miner_id;").fetchall()
        pools = conn.execute("SELECT * FROM pools ORDER BY pool_name;").fetchall()
        addresses = conn.execute("SELECT * FROM coin_addresses ORDER BY coin_ticker;").fetchall()
    return render_template('config.html', miners=miners, pools=pools, addresses=addresses)

@bp.route('/miners/upload', methods=['POST'])
def upload_miners():
    if 'miner_file' not in request.files:
        flash('No file part', 'error'); return redirect(url_for('main.config') + '#miners')
    file = request.files['miner_file']
    if file.filename == '':
        flash('No selected file', 'error'); return redirect(url_for('main.config') + '#miners')
    if file and file.filename.endswith('.csv'):
        try:
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_reader = csv.DictReader(stream)
            miners_to_upsert = [row for row in csv_reader]
            with get_db_connection() as conn:
                for miner in miners_to_upsert:
                     conn.execute('INSERT INTO miners (miner_id, chipset, attrs_idVendor, attrs_idProduct, attrs_serial, tty_symlink, nerdminer_rom, nerdminer_vrs) VALUES (:miner_id, :chipset, :attrs_idVendor, :attrs_idProduct, :attrs_serial, :tty_symlink, :nerdminer_rom, :nerdminer_vrs) ON CONFLICT(miner_id) DO UPDATE SET chipset=excluded.chipset, attrs_idVendor=excluded.attrs_idVendor, attrs_idProduct=excluded.attrs_idProduct, attrs_serial=excluded.attrs_serial, tty_symlink=excluded.tty_symlink, nerdminer_rom=excluded.nerdminer_rom, nerdminer_vrs=excluded.nerdminer_vrs;', miner)
            flash(f'Successfully processed {len(miners_to_upsert)} miners.', 'success')
        except Exception as e:
            flash(f'An error occurred: {e}', 'error')
    return redirect(url_for('main.config') + '#miners')


@bp.route('/miners/delete/<int:miner_id>', methods=['POST'])
def delete_miner(miner_id):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM miners WHERE id = ?;", (miner_id,))
    flash('Miner successfully deleted.', 'success')
    return redirect(url_for('main.config') + '#miners')

@bp.route('/pools/add', methods=['POST'])
def add_pool():
    form_data = request.form
    user_type = form_data.get('pool_user_type')
    pool_user = form_data.get('pool_user_dynamic') if user_type == 'dynamic' else form_data.get('pool_user_static')
    with get_db_connection() as conn:
        conn.execute("INSERT INTO pools (pool_name, pool_url, pool_port, pool_user, pool_pass) VALUES (?, ?, ?, ?, ?);", 
                     (form_data['pool_name'], form_data['pool_url'], form_data['pool_port'], pool_user, form_data.get('pool_pass', 'x')))
    flash('New pool successfully added.', 'success')
    return redirect(url_for('main.config') + '#pools')

@bp.route('/pools/delete/<int:pool_id>', methods=['POST'])
def delete_pool(pool_id):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM pools WHERE id = ?;", (pool_id,))
    flash('Pool successfully deleted.', 'success')
    return redirect(url_for('main.config') + '#pools')

@bp.route('/pools/set_active/<int:pool_id>', methods=['POST'])
def set_active_pool(pool_id):
    with get_db_connection() as conn:
        conn.execute("UPDATE pools SET is_active = 0;")
        conn.execute("UPDATE pools SET is_active = 1 WHERE id = ?;", (pool_id,))
    flash('Active pool has been updated.', 'success')
    return redirect(url_for('main.config') + '#pools')

@bp.route('/addresses/add', methods=['POST'])
def add_address():
    form_data = request.form
    with get_db_connection() as conn:
        conn.execute("INSERT INTO coin_addresses (coin_ticker, address, label) VALUES (?, ?, ?);", 
                     (form_data['coin_ticker'], form_data['address'], form_data['label']))
    flash('New address successfully added.', 'success')
    return redirect(url_for('main.config') + '#addresses')

@bp.route('/addresses/delete/<int:address_id>', methods=['POST'])
def delete_address(address_id):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM coin_addresses WHERE id = ?;", (address_id,))
    flash('Address successfully deleted.', 'success')
    return redirect(url_for('main.config') + '#addresses')

# --- Diagnostic Routes ---
@bp.route('/raw_logs')
def raw_logs():
    with get_db_connection() as conn:
        logs = conn.execute("SELECT l.created_at, m.miner_id, l.log_key, l.log_value FROM miner_logs l JOIN miners m ON l.miner_id = m.id ORDER BY l.id DESC LIMIT 30").fetchall()
    return render_template('raw_logs.html', logs=logs)

@bp.route('/summary')
def summary():
    with get_db_connection() as conn:
        summary_data = conn.execute("SELECT m.miner_id, s.* FROM miner_summary s JOIN miners m ON s.miner_id = m.id ORDER BY m.miner_id").fetchall()
    return render_template('summary.html', summary_data=summary_data)

