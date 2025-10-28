# shepherd/api_routes.py
# V.1.0.0
# Description: Handles all data-only API endpoints (e.g., /api/...)

import os
from flask import Blueprint, jsonify, send_from_directory
from .helpers import _get_herd_data, DATA_DIR, DEVICE_STATE_FILE

bp = Blueprint('api', __name__, url_prefix='/api')

@bp.route('/herd_data')
def api_herd_data(): 
    data = _get_herd_data()
    return jsonify(data)

@bp.route('/device_state')
def api_device_state():
    if not os.path.exists(DEVICE_STATE_FILE): 
        print(f"[API] ERROR: File not found: {DEVICE_STATE_FILE}")
        return jsonify([]) 
    try:
        file_size = os.path.getsize(DEVICE_STATE_FILE)
        if file_size == 0: 
            print(f"[API] Warning: File empty ({DEVICE_STATE_FILE}).")
            return jsonify([])
        response = send_from_directory(DATA_DIR, 'device_state.json', mimetype='application/json')
        return response
    except Exception as e: 
        print(f"[API] ERROR serving file {DEVICE_STATE_FILE}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Could not read file: {e}'}), 500