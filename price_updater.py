import requests
import json
import time
import os
from datetime import datetime, UTC

# --- Configuration ---
DATA_DIR = os.path.expanduser('~/shepherd_data')
CACHE_FILE = os.path.join(DATA_DIR, 'btc_price.json')
API_URL = "https://coincodex.com/api/coincodex/get_coin/BTC"
POLL_INTERVAL_SECONDS = 60 * 20 # 20 minutes

def fetch_and_cache_price():
    """Fetches the latest BTC price from CoinCodex and caches it to a local file."""
    print(f"[{datetime.now(UTC).isoformat()}] Fetching BTC price from CoinCodex...")
    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status() # Raises an HTTPError for bad responses (4xx or 5xx)
        
        data = response.json()
        
        price_data = {
            "price_usd": float(data.get("last_price_usd", 0)),
            "change_24h": float(data.get("percent_change_24h", 0)),
            "last_updated": datetime.now(UTC).isoformat()
        }
        
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(price_data, f)
            
        print(f"[{datetime.now(UTC).isoformat()}] Successfully updated price cache: ${price_data['price_usd']:.2f} ({price_data['change_24h']:.2f}%)")

    except requests.exceptions.RequestException as e:
        print(f"[{datetime.now(UTC).isoformat()}] Error fetching data from CoinCodex API: {e}")
    except json.JSONDecodeError as e:
        print(f"[{datetime.now(UTC).isoformat()}] Error parsing JSON response: {e}")
    except Exception as e:
        print(f"[{datetime.now(UTC).isoformat()}] An unexpected error occurred: {e}")


if __name__ == "__main__":
    print("Starting The Shepherd BTC Price Updater...")
    try:
        while True:
            fetch_and_cache_price()
            print(f"[{datetime.now(UTC).isoformat()}] Sleeping for {POLL_INTERVAL_SECONDS / 60} minutes...")
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nShutting down BTC price updater...")
