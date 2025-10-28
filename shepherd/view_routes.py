# shepherd/view_routes.py
# V.1.0.0
# Description: Handles all routes that render HTML pages for the user.

import sqlite3
import socket
from flask import Blueprint, render_template, flash, redirect, url_for
from .database import get_db_connection
from .helpers import _get_herd_data, get_btc_price_data, get_service_statuses, DEVICE_STATE_FILE

try:
    import psutil
except ImportError:
    psutil = None

# We name this blueprint 'main' to match the original 'main' in url_for() calls
bp = Blueprint('main', __name__)

# --- Main & Dashboard Routes ---
@bp.route('/')
def index(): return render_template('index.html')
@bp.route('/kiosk') 
def kiosk(): return render_template('kiosk.html')
@bp.route('/dashboards')
def dashboards(): return render_template('dashboards.html')
@bp.route('/dash/health')
def dash_health(): return render_template('dash_health.html')
@bp.route('/dash/nerdminer')
def dash_nerdminer():
    data = _get_herd_data(); stats = { 'current_block': 'N/A', 'time_since_block': 'N/A', 'hash_rate': f"{data['herd_stats']['total_hash_khs']:.2f}", 'difficulty': f"{data['herd_stats']['best_difficulty']:.2f}", 'btc_price': f"${data['btc_price_data']['price_usd']:,.2f}", 'sats_per_dollar': f"{100_000_000 / data['btc_price_data']['price_usd'] if data['btc_price_data']['price_usd'] > 0 else 0:,.0f}", 'market_cap': 'N/A' }
    return render_template('dash_nerdminer.html', stats=stats)
@bp.route('/dash/matrix')
def dash_matrix(): return render_template('dash_matrix.html')

# --- Farm Detail Routes ---
@bp.route('/details')
def details(): return render_template('details.html')
@bp.route('/details/system')
def details_system():
    stats={'psutil_installed': bool(psutil)}; 
    if psutil: stats['hostname'] = socket.gethostname(); 
    return render_template('details_system.html', stats=stats)
@bp.route('/details/miner/<int:miner_id>')
def details_miner(miner_id):
    miner = None
    conn = get_db_connection()
    if conn:
        try:
            query = "SELECT m.*, s.* FROM miners m LEFT JOIN miner_summary s ON m.id = s.miner_id WHERE m.id = ?;"
            miner = conn.execute(query, (miner_id,)).fetchone()
        except sqlite3.Error as e:
            print(f"Error fetching miner details for {miner_id}: {e}")
        finally:
            conn.close()

    if miner is None:
        flash(f"Miner with ID {miner_id} not found or a database error occurred.", "error")
        return redirect(url_for('main.index'))

    # Get the live status from the shepherd's dog state file
    live_status = "Unknown"
    try:
        with open(DEVICE_STATE_FILE, 'r') as f:
            device_state = json.load(f)
        
        devices_list = device_state.get("devices", device_state) if isinstance(device_state, dict) else device_state
        
        live_miner_data = next((d for d in devices_list if d.get('id') == miner_id), None)
        if live_miner_data:
            live_status = live_miner_data.get('display_status', 'Unknown')
    except (FileNotFoundError, json.JSONDecodeError, TypeError) as e:
        print(f"Warning: Could not read device state file for live status: {e}")

    return render_template('details_miner.html', miner=miner, live_status=live_status)

# --- Config & Management Routes ---
@bp.route('/config')
def config():
    pools = []
    addresses = []
    services = get_service_statuses()
    conn = get_db_connection()
    if conn:
        try:
            pools = conn.execute("SELECT * FROM pools ORDER BY pool_name;").fetchall()
            addresses = conn.execute("SELECT * FROM coin_addresses ORDER BY coin_ticker;").fetchall()
        except sqlite3.Error as e:
            print(f"Error fetching config data: {e}")
            flash("Error loading pool/address data from database.", "error")
        finally:
            conn.close()
    else:
        flash("Database connection failed. Could not load config data.", "error")
    return render_template('config.html', miners=[], pools=pools, addresses=addresses, services=services)

# --- Diagnostic Routes ---
@bp.route('/raw_logs')
def raw_logs():
    logs = []
    conn = get_db_connection()
    if conn:
        try:
            logs = conn.execute("SELECT l.created_at, m.miner_id, l.log_key, l.log_value FROM miner_logs l JOIN miners m ON l.miner_id = m.id ORDER BY l.id DESC LIMIT 100").fetchall()
        except sqlite3.Error as e:
            print(f"Error fetching raw logs: {e}")
            flash("Error fetching raw logs from database.", "error")
        finally:
            conn.close()
    else:
        flash("Database connection failed, could not fetch raw logs.", "error")
    return render_template('raw_logs.html', logs=logs)

@bp.route('/summary')
def summary():
    summary_data = []
    conn = get_db_connection()
    if conn:
        try:
            summary_data = conn.execute("SELECT m.miner_id, s.* FROM miner_summary s JOIN miners m ON s.miner_id = m.id ORDER BY m.miner_id;").fetchall()
        except sqlite3.Error as e:
            print(f"Error fetching summary data: {e}")
            flash("Error fetching summary data from database.", "error")
        finally:
            conn.close()
    else:
        flash("Database connection failed, could not fetch summary data.", "error")
    return render_template('summary.html', summary_data=summary_data)
