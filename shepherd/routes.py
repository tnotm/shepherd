# shepherd/routes.py
# V.0.0.1.9
# Description: Main routing file for the Shepherd Flask application.

import sqlite3
import os
import io
import csv
import json
import socket
import subprocess
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from .database import get_db_connection
from datetime import datetime, UTC

try:
    import psutil
except ImportError:
    psutil = None

bp = Blueprint('main', __name__)

# --- Configuration & Helpers ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
PRICE_CACHE_FILE = os.path.join(DATA_DIR, 'btc_price.json')
SHEPHERD_SERVICES = [
    'shepherd-ingestor.service',
    'shepherd-summarizer.service',
    'shepherd-pricer.service',
    'shepherd-device-discovery.service'
]

def get_btc_price_data():
    """Reads the cached BTC price data."""
    try:
        with open(PRICE_CACHE_FILE, 'r') as f:
            data = json.load(f)
            price = float(data.get("price_usd", 0) or 0)
            change = float(data.get("change_24h", 0) or 0)
            return {"price_usd": price, "change_24h": change}
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
    """Checks the status of all shepherd-related systemd services."""
    statuses = {}
    for service in SHEPHERD_SERVICES:
        try:
            result = subprocess.run(['systemctl', 'is-active', service], capture_output=True, text=True)
            status = result.stdout.strip()
            statuses[service] = status
        except Exception:
            statuses[service] = 'error'
    return statuses

def _get_herd_data():
    """Internal function to gather all data for the unified API."""
    with get_db_connection() as conn:
        miners_query = "SELECT m.*, s.* FROM miners m LEFT JOIN miner_summary s ON m.id = s.miner_id ORDER BY m.miner_id;"
        miners = conn.execute(miners_query).fetchall()

        total_miners = len(miners)
        online_miners = sum(1 for m in miners if m['status'] == 'online')
        total_hash_khs = sum(float(m['KH/s'] or 0) for m in miners)
        total_shares = sum(int(m['Shares'] or 0) for m in miners)
        total_block_templates = sum(int(m['Block templates'] or 0) for m in miners)
        best_difficulty = max([float(m['Best difficulty'] or 0) for m in miners] or [0])
        
        btc_price_data = get_btc_price_data()

        miners_list = [dict(row) for row in miners]

        return {
            "herd_stats": {
                "total_miners": total_miners,
                "online_miners": online_miners,
                "total_hash_khs": total_hash_khs,
                "total_shares": total_shares,
                "total_block_templates": total_block_templates,
                "best_difficulty": best_difficulty
            },
            "btc_price_data": btc_price_data,
            "miners_list": miners_list
        }

# --- Main & Dashboard Routes ---
@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/kiosk') 
def kiosk():
    return render_template('kiosk.html')

@bp.route('/dashboards')
def dashboards():
    return render_template('dashboards.html')

@bp.route('/dash/health')
def dash_health():
    return render_template('dash_health.html')

@bp.route('/dash/nerdminer')
def dash_nerdminer():
     # This dashboard is mostly decorative, but we can feed it some live data
    data = _get_herd_data()
    stats = {
        'current_block': 'N/A', # This data isn't easily available
        'time_since_block': 'N/A',
        'hash_rate': f"{data['herd_stats']['total_hash_khs']:.2f}",
        'difficulty': f"{data['herd_stats']['best_difficulty']:.2f}",
        'btc_price': f"${data['btc_price_data']['price_usd']:,.2f}",
        'sats_per_dollar': f"{100_000_000 / data['btc_price_data']['price_usd'] if data['btc_price_data']['price_usd'] > 0 else 0:,.0f}",
        'market_cap': 'N/A'
    }
    return render_template('dash_nerdminer.html', stats=stats)
    
@bp.route('/dash/matrix')
def dash_matrix():
    return render_template('dash_matrix.html')

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
            cpu_temp_key = next((key for key in temps if 'core' in key or 'cpu' in key), None)
            if cpu_temp_key and temps[cpu_temp_key]:
                 stats['cpu_temp'] = f"{temps[cpu_temp_key][0].current:.1f}°C"
            else:
                stats['cpu_temp'] = 'N/A'
        except (AttributeError, IndexError, KeyError, StopIteration):
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

@bp.route('/miners/delete/<int:miner_id>', methods=['POST'])
def delete_miner(miner_id):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM miners WHERE id = ?;", (miner_id,))
    flash('Miner successfully deleted.', 'success')
    return redirect(url_for('main.config') + '#miners')
    
@bp.route('/miners/edit/<int:miner_id>', methods=['POST'])
def edit_miner(miner_id):
    form_data = request.form
    new_miner_id = form_data.get('miner_id').strip()
    new_chipset = form_data.get('chipset').strip()
    new_version = form_data.get('nerdminer_vrs').strip()
    new_location_notes = form_data.get('location_notes').strip()

    if not new_miner_id:
        flash('Miner ID cannot be empty.', 'error')
        return redirect(url_for('main.config') + '#miners')

    with get_db_connection() as conn:
        existing_miner = conn.execute(
            "SELECT id FROM miners WHERE miner_id = ? AND id != ?;",
            (new_miner_id, miner_id)
        ).fetchone()

        if existing_miner:
            flash(f"Miner ID '{new_miner_id}' is already in use.", 'error')
            return redirect(url_for('main.config') + '#miners')

        conn.execute("""
            UPDATE miners 
            SET miner_id = ?, chipset = ?, nerdminer_vrs = ?, location_notes = ?
            WHERE id = ?;
        """, (new_miner_id, new_chipset, new_version, new_location_notes, miner_id))

    flash(f"Successfully updated miner '{new_miner_id}'.", 'success')
    return redirect(url_for('main.config') + '#miners')
    
@bp.route('/miners/onboard', methods=['POST'])
def onboard_miner():
    unconfigured_id = request.form.get('unconfigured_id')
    new_miner_id = request.form.get('miner_id', '').strip()

    if not unconfigured_id or not new_miner_id:
        return jsonify({'success': False, 'message': 'Missing required information for onboarding.'}), 400

    try:
        with get_db_connection() as conn:
            with conn: 
                device = conn.execute("SELECT * FROM unconfigured_devices WHERE id = ?;", (unconfigured_id,)).fetchone()
                if not device:
                    return jsonify({'success': False, 'message': 'Device not found or already configured.'}), 404

                existing_miner = conn.execute("SELECT id FROM miners WHERE miner_id = ?;", (new_miner_id,)).fetchone()
                if existing_miner:
                    return jsonify({'success': False, 'message': f"Miner ID '{new_miner_id}' is already in use."}), 409

                conn.execute("""
                    INSERT INTO miners (miner_id, dev_path, port_path, attrs_idVendor, attrs_idProduct, attrs_serial)
                    VALUES (?, ?, ?, ?, ?, ?);
                """, (
                    new_miner_id,
                    device['dev_path'],
                    device['port_path'],
                    device['vendor_id'],
                    device['product_id'],
                    device['serial_number']
                ))

                conn.execute("DELETE FROM unconfigured_devices WHERE id = ?;", (unconfigured_id,))
        
        return jsonify({'success': True, 'message': f"Successfully onboarded '{new_miner_id}'. The page will now reload."})
    except Exception as e:
        print(f"Onboarding error: {e}")
        return jsonify({'success': False, 'message': 'A server error occurred during onboarding.'}), 500

@bp.route('/pools/add', methods=['POST'])
def add_pool():
    form_data = request.form
    user_type = form_data.get('user_type')
    pool_user = form_data.get('dynamic_user_address') if user_type == 'dynamic' else form_data.get('text_user_address')
    
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
    
# --- Service Management Routes ---
@bp.route('/service/restart/<service_name>', methods=['POST'])
def restart_service(service_name):
    if service_name in SHEPHERD_SERVICES:
        try:
            subprocess.run(['sudo', 'systemctl', 'restart', service_name], check=True)
            flash(f"Successfully restarted {service_name}.", 'success')
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            flash(f"Failed to restart {service_name}: {e}", 'error')
    else:
        flash("Invalid service name.", 'error')
    return redirect(url_for('main.config') + '#developer')

@bp.route('/service/restart/all', methods=['POST'])
def restart_all_services():
    success = True
    for service in SHEPHERD_SERVICES:
        try:
            subprocess.run(['sudo', 'systemctl', 'restart', service], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            flash(f"Failed to restart {service}.", 'error')
            success = False
    if success:
        flash("Successfully restarted all services.", 'success')
    return redirect(url_for('main.config') + '#developer')

# --- Diagnostic Routes ---
@bp.route('/raw_logs')
def raw_logs():
    with get_db_connection() as conn:
        logs = conn.execute("SELECT l.created_at, m.miner_id, l.log_key, l.log_value FROM miner_logs l JOIN miners m ON l.miner_id = m.id ORDER BY l.id DESC LIMIT 100").fetchall()
    return render_template('raw_logs.html', logs=logs)

@bp.route('/summary')
def summary():
    return render_template('summary.html')
    
# --- API Routes ---
@bp.route('/api/herd_data')
def api_herd_data():
    """The single, unified API endpoint for all dashboard data."""
    data = _get_herd_data()
    return jsonify(data)

@bp.route('/api/unconfigured_devices')
def api_unconfigured_devices():
    """API endpoint to get the list of new, unconfigured devices."""
    with get_db_connection() as conn:
        devices = conn.execute("SELECT * FROM unconfigured_devices ORDER BY discovered_at DESC;").fetchall()
        return jsonify([dict(row) for row in devices])
