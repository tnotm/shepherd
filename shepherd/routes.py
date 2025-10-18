# shepherd/routes.py
# V.0.0.1.3
# Description: Main routing file for the Shepherd Flask application.

import sqlite3
import os
import csv
import io
import json
import socket
import subprocess
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
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
SHEPHERD_SERVICES = [
    'shepherd-app.service',
    'shepherd-ingestor.service',
    'shepherd-summarizer.service',
    'shepherd-pricer.service'
]

def get_btc_price_data():
    """Reads the cached BTC price data, ensuring numeric types."""
    try:
        with open(PRICE_CACHE_FILE, 'r') as f:
            data = json.load(f)
            # Ensure values are numeric, default to 0 if not
            price = data.get("price_usd", 0)
            change = data.get("change_24h", 0)
            return {
                "price_usd": float(price) if price is not None else 0,
                "change_24h": float(change) if change is not None else 0.0
            }
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return {"price_usd": 0, "change_24h": 0.0}

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

def get_service_statuses():
    """Checks the status of predefined systemd services."""
    statuses = {}
    for service in SHEPHERD_SERVICES:
        try:
            result = subprocess.run(['systemctl', 'is-active', service], capture_output=True, text=True)
            status = result.stdout.strip()
            statuses[service] = status
        except FileNotFoundError:
            statuses[service] = 'not_found'
        except Exception:
            statuses[service] = 'error'
    return statuses

# NEW: Unified private function to get all herd data
def _get_herd_data():
    """Private helper to fetch and structure all data for the API."""
    with get_db_connection() as conn:
        # Get individual miner details
        miner_query = """
            SELECT m.id, m.miner_id, m.nerdminer_vrs, m.status, s."KH/s", s.Temperature,
                   s.Shares, s."Best difficulty", s."Block templates", s.last_updated
            FROM miners m
            LEFT JOIN miner_summary s ON m.id = s.miner_id
            ORDER BY m.miner_id;
        """
        miners_list = [dict(row) for row in conn.execute(miner_query).fetchall()]

        # Calculate herd summary stats from the detailed list
        total_miners = len(miners_list)
        online_miners = sum(1 for m in miners_list if m['status'] == 'online')
        total_hash_khs = sum(float(m['KH/s'] or 0) for m in miners_list)
        total_shares = sum(int(m['Shares'] or 0) for m in miners_list)
        total_block_templates = sum(int(m['Block templates'] or 0) for m in miners_list)
        best_difficulty = max([float(m['Best difficulty'] or 0) for m in miners_list] or [0])

        herd_stats = {
            "total_miners": total_miners,
            "online_miners": online_miners,
            "total_hash_khs": total_hash_khs,
            "total_shares": total_shares,
            "total_block_templates": total_block_templates,
            "best_difficulty": best_difficulty
        }

        btc_price_data = get_btc_price_data()

        return {
            "herd_stats": herd_stats,
            "btc_price_data": btc_price_data,
            "miners_list": miners_list
        }

# --- Main Application Routes ---

@bp.route('/')
def index():
    # Page now renders statically; data is fetched by JavaScript.
    return render_template('index.html')

@bp.route('/kiosk')
def kiosk():
    # Page now renders statically
    return render_template('kiosk.html')

@bp.route('/dashboards')
def dashboards():
    return render_template('dashboards.html')

@bp.route('/dash/health')
def dash_health():
    # Page now renders statically
    return render_template('dash_health.html')

@bp.route('/dash/nerdminer')
def dash_nerdminer():
    # This is placeholder, needs real data source
    stats = {
        'current_block': '812345', 'time_since_block': '5m 12s',
        'hash_rate': '78.45', 'difficulty': '52.3T', 'btc_price': '68,123',
        'market_cap': '1.34T', 'sats_per_dollar': '1,468'
    }
    return render_template('dash_nerdminer.html', stats=stats)

@bp.route('/dash/matrix')
def dash_matrix():
    # Page now renders statically
    return render_template('dash_matrix.html')

# --- NEW: UNIFIED API ENDPOINT ---
@bp.route('/api/herd_data')
def api_herd_data():
    """The single endpoint for all dynamic dashboard data."""
    data = _get_herd_data()
    return jsonify(data)

# --- Farm Detail Routes ---
@bp.route('/details')
def details():
    return render_template('details.html')

@bp.route('/details/system')
def details_system():
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
    with get_db_connection() as conn:
        miners = conn.execute("SELECT * FROM miners ORDER BY miner_id;").fetchall()
        pools = conn.execute("SELECT * FROM pools ORDER BY pool_name;").fetchall()
        addresses = conn.execute("SELECT * FROM coin_addresses ORDER BY coin_ticker;").fetchall()
    services = get_service_statuses()
    return render_template('config.html', miners=miners, pools=pools, addresses=addresses, services=services)

# ... (all other config routes remain the same) ...
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
    user_type = form_data.get('user_type') 
    pool_user = form_data.get('dynamic_user_address') if user_type == 'dynamic' else form_data.get('text_user_address')

    if user_type == 'dynamic' and pool_user:
        final_user = f"{pool_user}.{{miner_id}}"
    else:
        final_user = pool_user

    with get_db_connection() as conn:
        conn.execute("INSERT INTO pools (pool_name, pool_url, pool_port, pool_user, pool_pass) VALUES (?, ?, ?, ?, ?);", 
                     (form_data['pool_name'], form_data['pool_url'], form_data['pool_port'], final_user, form_data.get('pool_pass', 'x')))
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

@bp.route('/dev/service/restart/<service_name>', methods=['POST'])
def restart_service(service_name):
    # Security check: ensure the service is in our allowed list
    if service_name not in SHEPHERD_SERVICES:
        flash(f"Error: '{service_name}' is not a valid service.", 'error')
        return redirect(url_for('main.config') + '#developer')
    
    try:
        result = subprocess.run(['sudo', 'systemctl', 'restart', service_name], check=True, capture_output=True, text=True)
        flash(f"Successfully sent restart command to {service_name}.", 'success')
    except subprocess.CalledProcessError as e:
        flash(f"Error restarting {service_name}: {e.stderr}", 'error')
    except FileNotFoundError:
        flash("Error: 'sudo' or 'systemctl' command not found. This feature requires a systemd-based Linux environment.", 'error')
    except Exception as e:
        flash(f"An unexpected error occurred: {e}", 'error')
        
    return redirect(url_for('main.config') + '#developer')

@bp.route('/dev/service/restart_all', methods=['POST'])
def restart_all_services():
    success = True
    for service in SHEPHERD_SERVICES:
        try:
            subprocess.run(['sudo', 'systemctl', 'restart', service], check=True, capture_output=True, text=True)
        except Exception:
            success = False
            flash(f"Failed to restart {service}. See system logs for details.", 'error')
    
    if success:
        flash("Successfully sent restart command to all services.", 'success')
    
    return redirect(url_for('main.config') + '#developer')


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

