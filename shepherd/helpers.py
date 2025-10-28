# shepherd/helpers.py
# V.1.0.0
# Description: Contains helper functions and constants formerly in routes.py

import os
import json
import sqlite3
import socket
import subprocess
from datetime import datetime, timedelta, UTC
from .database import get_db_connection

# --- Constants ---
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

# --- Helper Functions ---

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
