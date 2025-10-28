# shepherd/routes.py
# V.0.0.3.4
# Description: Main routing file for the Shepherd Flask application.

import sqlite3
import os
import io
import csv
import json
import socket
import subprocess
import serial 
import time 
import re 
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from .database import get_db_connection
from datetime import datetime, timedelta, UTC 

try:
    import psutil
except ImportError:
    psutil = None

bp = Blueprint('main', __name__)

# --- Configuration & Helpers ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
PRICE_CACHE_FILE = os.path.join(DATA_DIR, 'btc_price.json')
DEVICE_STATE_FILE = os.path.join(DATA_DIR, 'device_state.json') 
SHEPHERD_SERVICES = [
    'shepherd-ingestor.service',
    'shepherd-summarizer.service',
    'shepherd-pricer.service',
    'shepherds-dog.service' 
]
INGESTOR_SERVICE_NAME = 'shepherd-ingestor.service' 
INGESTOR_POLL_INTERVAL = 15 

def get_btc_price_data():
    """Reads the cached BTC price data."""
    try:
        with open(PRICE_CACHE_FILE, 'r') as f:
            data = json.load(f)
            price = float(data.get("price_usd", 0) or 0)
            change = float(data.get("change_24h", 0) or 0)
            return {"price_usd": price, "change_24h": change}
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        print(f"Warning: Could not read or parse {PRICE_CACHE_FILE}")
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
            active_result = subprocess.run(['systemctl', 'is-active', service], capture_output=True, text=True)
            failed_result = subprocess.run(['systemctl', 'is-failed', service], capture_output=True, text=True)
            
            status = active_result.stdout.strip()
            if status == 'inactive' and failed_result.stdout.strip() == 'failed':
                 status = 'failed'
                 
            statuses[service] = status
        except Exception as e:
            print(f"Error checking status for {service}: {e}")
            statuses[service] = 'error'
    return statuses



def _get_herd_data():
    """Internal function to gather all data for the unified API."""
    herd_data = {
        "herd_stats": {
            "total_miners": 0, "online_miners": 0, "total_hash_khs": 0.0,
            "total_shares": 0, "total_block_templates": 0, "best_difficulty": 0.0
        },
        "btc_price_data": get_btc_price_data(),
        "miners_list": []
    }
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise sqlite3.Error("DB connect fail")

        miners = conn.execute("SELECT m.*, s.* FROM miners m LEFT JOIN miner_summary s ON m.id = s.miner_id ORDER BY m.miner_id;").fetchall()
        herd_data["miners_list"] = [dict(row) for row in miners]
        herd_data["herd_stats"]["total_miners"] = len(miners)
        herd_data["herd_stats"]["total_hash_khs"] = sum(float(m['KH/s'] or 0) for m in miners)
        herd_data["herd_stats"]["total_shares"] = sum(int(m['Shares'] or 0) for m in miners)
        herd_data["herd_stats"]["total_block_templates"] = sum(int(m['Block templates'] or 0) for m in miners)
        herd_data["herd_stats"]["best_difficulty"] = max([float(m['Best difficulty'] or 0) for m in miners] or [0])

        try:
            with open(DEVICE_STATE_FILE, 'r') as f:
                device_state = json.load(f)
            devices_list = device_state.get("devices", device_state) if isinstance(device_state, dict) else device_state
            online_miners = sum(1 for d in devices_list if d.get('type') == 'miner' and d.get('display_status', '').lower() == 'online')
            herd_data["herd_stats"]["online_miners"] = online_miners
        except Exception as e: print(f"Warn: Read {DEVICE_STATE_FILE} fail: {e}"); herd_data["herd_stats"]["online_miners"] = sum(1 for m in miners if m['status'] == 'Active') 
    except sqlite3.Error as e: print(f"Error fetching herd data: {e}")
    except Exception as e: print(f"Unexpected error in _get_herd_data: {e}")
    finally:
         if conn: conn.close()
    return herd_data



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

@bp.route('/miners/delete/<int:miner_id>', methods=['POST'])
def delete_miner(miner_id):
    conn = get_db_connection()
    if not conn:
        flash("Database connection failed.", "error")
        return redirect(url_for('main.config') + '#miners')
    try:
        with conn:
            conn.execute("DELETE FROM miners WHERE id = ?;", (miner_id,))
        flash('Miner deleted successfully.', 'success')
    except sqlite3.Error as e:
        print(f"Error deleting miner {miner_id}: {e}")
        flash(f"Database error on delete: {e}", "error")
    finally:
        conn.close()
    return redirect(url_for('main.config') + '#miners')
    
@bp.route('/miners/edit/<int:miner_id>', methods=['POST'])
def edit_miner(miner_id):
    form_data = request.form
    new_miner_id = form_data.get('miner_id', '').strip()
    new_chipset = form_data.get('chipset', '').strip()
    new_version = form_data.get('nerdminer_vrs', '').strip()
    new_location_notes = form_data.get('location_notes', '').strip()

    if not new_miner_id:
        flash('Miner ID cannot be empty.', 'error')
        return redirect(url_for('main.config') + '#miners')

    conn = get_db_connection()
    if not conn:
        flash("Database connection failed.", "error")
        return redirect(url_for('main.config') + '#miners')

    try:
        with conn:
            existing = conn.execute("SELECT id FROM miners WHERE miner_id = ? AND id != ?;", (new_miner_id, miner_id)).fetchone()
            if existing:
                flash(f"Miner ID '{new_miner_id}' is already in use.", 'error')
                return redirect(url_for('main.config') + '#miners')
            conn.execute("UPDATE miners SET miner_id=?, chipset=?, nerdminer_vrs=?, location_notes=? WHERE id=?;", (new_miner_id, new_chipset, new_version, new_location_notes, miner_id))
        flash(f"Updated '{new_miner_id}'.", 'success')
    except sqlite3.Error as e:
        print(f"Error editing miner {miner_id}: {e}")
        flash(f"Database error on edit: {e}", "error")
    finally:
        conn.close()
    return redirect(url_for('main.config') + '#miners')
    
# Onboard Stray Route
@bp.route('/miners/onboard_stray', methods=['POST'])
def onboard_stray_miner():
    form_data = request.form; miner_id = form_data.get('miner_id').strip(); currency = form_data.get('currency'); dev_path = form_data.get('dev_path'); port_path = form_data.get('port_path'); attrs_serial = form_data.get('serial_number'); vendor_id = form_data.get('vendor_id'); product_id = form_data.get('product_id'); location_notes = form_data.get('location_notes', '').strip(); pool_url = form_data.get('pool_url'); wallet_address = form_data.get('wallet_address'); version = form_data.get('version'); mac_address = form_data.get('mac_address'); chipset = form_data.get('chipset') 
    initial_status = 'Active' if (pool_url or wallet_address or version or mac_address or chipset) else 'Inactive'
    initial_state = 'Onboarded (Active)' if initial_status == 'Active' else 'Onboarded (Inactive)'
    if not all([miner_id, currency, dev_path, port_path, attrs_serial]): return jsonify({'success': False, 'message': 'Missing required info.'}), 400
    conn = get_db_connection(); 
    if not conn: return jsonify({'success': False, 'message': 'DB fail.'}), 500
    try:
        with conn: 
            existing_by_id = conn.execute("SELECT id FROM miners WHERE miner_id = ?;", (miner_id,)).fetchone()
            if existing_by_id: return jsonify({'success': False, 'message': f"ID '{miner_id}' exists."}), 409
            existing_by_device = conn.execute("SELECT miner_id FROM miners WHERE port_path = ? AND attrs_serial = ?;", (port_path, attrs_serial)).fetchone()
            if existing_by_device: return jsonify({'success': False, 'message': f"Device {port_path}/{attrs_serial} exists as '{existing_by_device['miner_id']}'."}), 409
            if mac_address:
                existing_by_mac = conn.execute("SELECT miner_id FROM miners WHERE mac_address = ?;", (mac_address,)).fetchone()
                if existing_by_mac: return jsonify({'success': False, 'message': f"MAC '{mac_address}' exists ('{existing_by_mac['miner_id']}')."}), 409
            print(f"[Onboard] Inserting '{miner_id}', Status: {initial_status}") 
            conn.execute("""INSERT INTO miners (miner_id, currency, dev_path, port_path, attrs_serial, mac_address, attrs_idVendor, attrs_idProduct, location_notes, chipset, pool_url, wallet_address, nerdminer_vrs, status, state, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?); """, (miner_id, currency, dev_path, port_path, attrs_serial, mac_address, vendor_id, product_id, location_notes, chipset, pool_url, wallet_address, version, initial_status, initial_state, datetime.now(UTC).isoformat()))
            print(f"[Onboard] Deleting stray ({port_path}, {attrs_serial})") 
            cursor = conn.execute("DELETE FROM stray_devices WHERE port_path = ? AND serial_number = ?;", (port_path, attrs_serial))
            if cursor.rowcount == 0:
                 if mac_address:
                      print(f"[Onboard] Trying delete stray with MAC key ({port_path}, {mac_address})")
                      cursor = conn.execute("DELETE FROM stray_devices WHERE port_path = ? AND mac_address = ?;", (port_path, mac_address))
                      if cursor.rowcount == 0: print(f"[Onboard] WARN: Delete stray failed for both keys.")
                 else: print(f"[Onboard] WARN: Delete stray failed for key ({port_path}, {attrs_serial}).") 
        return jsonify({'success': True, 'message': f"Added '{miner_id}'. Status: '{initial_status}'."})
    except sqlite3.IntegrityError as e:
         message = f"DB Integrity Error: {e}"; 
         if 'miners.mac_address' in str(e): message = f"MAC '{mac_address}' exists."
         elif 'miners.miner_id' in str(e): message = f"ID '{miner_id}' exists."
         elif 'miners.port_path, miners.attrs_serial' in str(e): message = f"Device {port_path}/{attrs_serial} exists."
         return jsonify({'success': False, 'message': message}), 409 
    except Exception as e: print(f"Onboard error: {e}"); import traceback; traceback.print_exc(); return jsonify({'success': False, 'message': 'Server error.'}), 500
    finally:
         if conn: conn.close()


@bp.route('/pools/add', methods=['POST'])
def add_pool():
    form_data = request.form
    user_type = form_data.get('user_type')
    pool_user = form_data.get('dynamic_user_address') if user_type == 'dynamic' else form_data.get('text_user_address')

    conn = get_db_connection()
    if not conn:
        flash("Database connection error.", "error")
        return redirect(url_for('main.config') + '#pools')

    try:
        with conn:
            conn.execute(
                "INSERT INTO pools (pool_name, pool_url, pool_port, pool_user, pool_pass) VALUES (?, ?, ?, ?, ?);",
                (form_data['pool_name'], form_data['pool_url'], form_data['pool_port'], pool_user, form_data.get('pool_pass', 'x'))
            )
        flash('New pool added successfully.', 'success')
    except Exception as e:
        print(f"Error adding pool: {e}")
        flash(f"Error adding pool: {e}", "error")
    finally:
        if conn:
            conn.close()
    return redirect(url_for('main.config') + '#pools')

@bp.route('/service/restart/<service_name>', methods=['POST'])
def restart_service(service_name):
     if service_name in SHEPHERD_SERVICES:
         try: subprocess.run(['sudo', 'systemctl', 'restart', service_name], check=True); flash(f"Restarted {service_name}.", 'success')
         except Exception as e: flash(f"Failed to restart {service_name}: {e}", 'error')
     else: flash("Invalid service name.", 'error')
     return redirect(url_for('main.config') + '#developer')

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


# --- Miner Action Route ---
@bp.route('/miners/action', methods=['POST'])
def run_miner_action():
    """Handles user-triggered actions like 'reset_capture'."""
    data = request.json; action = data.get('action'); dev_path = data.get('dev_path'); port_path = data.get('port_path'); original_usb_serial = data.get('serial_number'); miner_db_id = data.get('miner_db_id') 
    print(f"[Action] Received '{action}' for {dev_path}, port:{port_path}, serial:{original_usb_serial}, db_id:{miner_db_id}") 
    if not all([dev_path, port_path, original_usb_serial]): return jsonify({'success': False, 'message': f"Missing identifiers."}), 400
    
    if action == 'reset_capture':
        print(f"[Action] Executing reset_capture on {dev_path}...")
        captured_data=None; chipset_info=None; mac_address=None; ser=None; original_status=None; reset_capture_success=False
        
        # --- Phase 1: Update DB Status and Wait ---
        try:
            print(f"[Action] Setting status='Resetting'...")
            conn = get_db_connection(); 
            if not conn: raise Exception("DB connection failed pre-reset")
            with conn:
                 if miner_db_id: 
                     cursor = conn.execute("SELECT status FROM miners WHERE id = ?", (miner_db_id,)); result = cursor.fetchone(); original_status = result['status'] if result else None
                     conn.execute("UPDATE miners SET status = 'Resetting', state = 'Awaiting Reset' WHERE id = ?;", (miner_db_id,))
                 else:
                     conn.execute("UPDATE stray_devices SET state = 'Awaiting Reset' WHERE port_path = ? AND serial_number = ?;", (port_path, original_usb_serial))
                     original_status = 'Inactive' 
            conn.close()
            wait_time = INGESTOR_POLL_INTERVAL + 1; print(f"[Action] Waiting {wait_time}s..."); time.sleep(wait_time)
        except Exception as e: print(f"[Action] ERROR pre-reset: {e}"); return jsonify({'success': False, 'message': f"Error preparing reset: {e}"}), 500
        
        # --- Phase 2: Run esptool and Capture ---
        try: 
            try: # --- esptool ---
                print(f"[Action] Running esptool read_mac..."); command = ['esptool.py', '--port', dev_path, '-a', 'hard-reset', 'read_mac']; reset_result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=True) 
                print(f"[Action] esptool success."); print(f"[Action] Output:\n{reset_result.stdout}\n{reset_result.stderr}") 
                for line in reset_result.stdout.splitlines():
                     if line.startswith("Chip type:"): chipset_info = line.split(":", 1)[1].strip(); print(f"[Action] Chipset: {chipset_info}") 
                     elif line.startswith("MAC:"): mac_address = line.split(":", 1)[1].strip(); print(f"[Action] MAC: {mac_address}") 
                if not mac_address: print("[Action] WARNING: MAC not found."); mac_address = None 
                time.sleep(1.5) 
            except Exception as e: raise Exception(f"esptool.py failed: {e}") from e
            
            try:
                print(f"[Action] Opening port for capture..."); ser = serial.Serial(dev_path, 115200, timeout=1.0); print(f"[Action] Port open.")
                start_time=time.time(); capture_duration=30; lines=[]; json_buffer=""; parsing_state="SCANNING"; config_found=False
                print(f"[Action] Capture loop ({capture_duration}s)...") 
                while time.time() - start_time < capture_duration:
                    line_bytes = ser.readline(); 
                    if not line_bytes: time.sleep(0.01); continue 
                    try:
                        line = line_bytes.decode('utf-8', errors='ignore').strip(); 
                        if not line: continue; lines.append(line) 
                        if parsing_state=="SCANNING" and line.strip()=="{": parsing_state="IN_JSON"; json_buffer="{" 
                        elif parsing_state=="IN_JSON":
                            json_buffer+=line+"\n"; 
                            if line.strip()=="}":
                                parsing_state="PARSED_JSON"; 
                                try:
                                    clean_buffer = re.sub(r",\s*}","}",json_buffer); clean_buffer = re.sub(r",\s*]"," ]",clean_buffer); 
                                    parsed_config = json.loads(clean_buffer); 
                                    captured_data = {"pool_url":parsed_config.get("poolString"), "wallet_address":parsed_config.get("btcString"), "version":parsed_config.get("nmVersion", parsed_config.get("FirmwareVersion"))}
                                    if not captured_data["pool_url"] or not captured_data["wallet_address"]: print("[Action] JSON missing fields."); parsing_state="SCANNING"; json_buffer=""; continue 
                                    config_found=True; print(f"[Action] Parsed config: {captured_data}"); break 
                                except json.JSONDecodeError as json_e: print(f"[Action] JSON parse failed: {json_e}"); parsing_state="SCANNING"; json_buffer="" 
                            elif len(json_buffer)>4096: print("[Action] JSON buffer exceeded."); parsing_state="SCANNING"; json_buffer=""
                    except UnicodeDecodeError: continue 
                    except serial.SerialException as read_e: print(f"[Action] Serial read error: {read_e}."); break
                    except Exception as loop_e: print(f"[Action] Capture loop error: {loop_e}"); import traceback; traceback.print_exc(); break
                print(f"[Action] Capture loop finished.")
            finally:
                if ser and ser.is_open:
                    try:
                        ser.close()
                        print(f"[Action] Port closed after capture.")
                    except Exception as e:
                        print(f"[Action] Error closing serial port after capture: {e}")
                ser = None
                
            # --- DB Update ---
            print("[Action] Updating DB...")
            conn = get_db_connection()
            if not conn: raise Exception("DB connection failed post-capture")
            with conn:
                 if miner_db_id:
                     update_fields={'mac_address': mac_address, 'chipset': chipset_info, 'status': 'Active' if config_found else original_status, 'state': 'Synced' if config_found else 'Capture Failed', 'last_seen': datetime.now(UTC).isoformat()}
                     if config_found and captured_data: update_fields.update({'pool_url': captured_data.get('pool_url'), 'wallet_address': captured_data.get('wallet_address'), 'nerdminer_vrs': captured_data.get('version')})
                     set_clauses = [f"{field} = ?" for field in update_fields.keys()]; values = list(update_fields.values()) + [miner_db_id]
                     sql = f"UPDATE miners SET {', '.join(set_clauses)} WHERE id = ?;"; print(f"[Action] SQL: {sql} Vals: {values}") 
                     conn.execute(sql, values); print(f"[Action] Miner {miner_db_id} DB updated.") 
                     reset_capture_success = True 
                 else:
                     print(f"[Action] Updating stray (Key: {port_path}/{original_usb_serial}). Storing MAC: {mac_address}")
                     conn.execute("""
                         UPDATE stray_devices 
                         SET chipset = ?, mac_address = ?, dumped_pool_url = ?, 
                             dumped_wallet_address = ?, dumped_firmware_version = ?, 
                             status = ?, state = ?, discovered_at = ? 
                         WHERE port_path = ? AND serial_number = ?;
                     """, (
                         chipset_info, mac_address, 
                         captured_data.get('pool_url') if config_found else None, 
                         captured_data.get('wallet_address') if config_found else None, 
                         captured_data.get('version') if config_found else None, 
                         'Inactive', 'Captured' if config_found else 'Capture Failed', 
                         datetime.now(UTC).isoformat(),
                         port_path, original_usb_serial
                     ))
                     if conn.changes() == 0:
                          print(f"[Action] WARN: Update failed for stray {port_path}/{original_usb_serial}. Row might not exist?")
                     else:
                         print(f"[Action] Stray device DB updated.")

                     if not captured_data: captured_data = {} 
                     captured_data.update({'mac_address': mac_address, 'chipset': chipset_info, 
                                           'serial_number': original_usb_serial})
                     reset_capture_success = True 
            conn.close() 

            if reset_capture_success:
                 message = f"Reset {dev_path}, captured MAC/Chipset."; status_code = 200
                 if config_found: message += " Config found."
                 elif mac_address or chipset_info: message += " Failed to capture Config."
                 else: message = f"Reset {dev_path}, failed capture."; status_code = 500
                 return jsonify({ 'success': (config_found or mac_address or chipset_info), 'message': message, 'data': captured_data or {} }), status_code
            else: return jsonify({'success': False, 'message': f"Failed before DB update."}), 500
            
        except Exception as e:
            error_message = f"Error: {e}"; status_code = 500
            if isinstance(e, FileNotFoundError): error_message = "'esptool.py' not found..."
            elif isinstance(e, subprocess.TimeoutExpired): error_message = f"Reset/Read MAC timed out..."
            elif isinstance(e, subprocess.CalledProcessError): error_message = f"esptool failed: {e.stderr}"
            elif isinstance(e, serial.SerialException): error_message = f"Serial error after reset: {e}."
            elif "Port still busy" in str(e): error_message = str(e); status_code=409 
            print(f"[Action] Overall Error: {error_message}") 
            conn = get_db_connection()
            if conn:
                try:
                    with conn:
                        state_to_set = 'Action Error'; 
                        if 'Serial error' in error_message: state_to_set = 'Capture Serial Error'
                        if 'timed out' in error_message: state_to_set = 'Action Timeout'
                        if 'busy' in error_message: state_to_set = 'Port Busy Error' 
                        if miner_db_id: conn.execute("UPDATE miners SET state = ?, mac_address = ?, chipset = ? WHERE id = ?;", (state_to_set, mac_address, chipset_info, miner_db_id))
                        else: conn.execute("UPDATE stray_devices SET state = ?, chipset = ?, mac_address = ? WHERE port_path = ? AND serial_number = ?;", (state_to_set, chipset_info, mac_address, port_path, original_usb_serial)) # Use original key
                except Exception as db_e: print(f"[Action] Failed state update after error: {db_e}")
                finally: conn.close()
            return jsonify({'success': False, 'message': error_message}), status_code
            
        finally:
             conn = get_db_connection()
             if conn:
                 try:
                     if miner_db_id and original_status is not None:
                          final_status = 'Active' if reset_capture_success and config_found else original_status
                          final_state = 'Synced' if reset_capture_success and config_found else ('Capture Failed' if reset_capture_success else 'Action Error') 
                          print(f"[Action] Finalizing status for miner {miner_db_id} to '{final_status}' ('{final_state}')...")
                          with conn: conn.execute("UPDATE miners SET status = ?, state = ? WHERE id = ? AND status = 'Resetting';", (final_status, final_state, miner_db_id))
                     elif not miner_db_id:
                          final_state = 'Captured' if reset_capture_success and config_found else ('Capture Failed' if reset_capture_success else 'Action Error')
                          print(f"[Action] Finalizing state for stray {port_path}/{original_usb_serial} to '{final_state}'...")
                          with conn: conn.execute("UPDATE stray_devices SET state = ? WHERE port_path = ? AND serial_number = ?;", (final_state, port_path, original_usb_serial)) # Use original key
                 except Exception as db_e: print(f"[Action] ERROR finalizing DB status/state: {db_e}")
                 finally: conn.close()
             else: print("[Action] ERROR: Could not connect to DB to finalize status.")

    else: return jsonify({'success': False, 'message': f"Unknown action: {action}"}), 400
    
# --- API Routes ---
@bp.route('/api/herd_data')
def api_herd_data(): data = _get_herd_data(); return jsonify(data)

@bp.route('/api/device_state')
def api_device_state():
    if not os.path.exists(DEVICE_STATE_FILE): print(f"[API] ERROR: File not found: {DEVICE_STATE_FILE}"); return jsonify([]) 
    try:
        file_size = os.path.getsize(DEVICE_STATE_FILE); 
        if file_size == 0: print(f"[API] Warning: File empty ({DEVICE_STATE_FILE})."); return jsonify([])
        response = send_from_directory(DATA_DIR, 'device_state.json', mimetype='application/json')
        return response
    except Exception as e: print(f"[API] ERROR serving file {DEVICE_STATE_FILE}: {e}"); import traceback; traceback.print_exc(); return jsonify({'error': f'Could not read file: {e}'}), 500
