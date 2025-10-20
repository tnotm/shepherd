# The Shepherd Project

**The Shepherd** is a comprehensive management and monitoring dashboard for a "flock" of microcontroller-based Bitcoin lottery miners (e.g., NerdMiners). It provides a full-featured web interface and several kiosk-style dashboard views to monitor the health, performance, and statistics of an entire mining farm in real-time.

The primary goal of this project is to centralize the management of many small mining devices into a single, cohesive, and easy-to-use application.

## Key Features

* **Unified Web Dashboard**: A main dashboard displaying a list of all miners, their status, hash rate, temperature, shares, and other key statistics.
* **Multiple Dashboard Views**: Several purpose-built dashboard modes for different display needs:
    * **Kiosk/Clock View**: A large clock, BTC price, and summary stats.
    * **Herd Health**: A compact grid showing the online/offline status of all miners at a glance.
    * **NerdMiner Homage**: A retro-style dashboard inspired by the classic NerdMiner display.
    * **Digital Stream**: A "Matrix-style" dynamic data visualization.
* **Centralized Configuration**: A settings page to manage miner configurations, mining pools, and wallet addresses.
* **Auto-Discovery & Onboarding**: A service automatically detects new USB miners when they are plugged in, allowing them to be easily named and added to the farm.
* **Real-time Price Tracking**: A background service fetches and caches the current BTC price and 24-hour change.

## Architecture Overview

Shepherd is a Python-based application built on a service-oriented architecture. It consists of a central web application and several independent background services that work together.

### 1. Core Application

* **Web Interface (Flask)**: A Flask application (run with `waitress`) serves all HTML pages and the main data API.
* **Unified API**: A single endpoint (`/api/herd_data`) provides all necessary real-time data to the frontend dashboards.
* **Frontend**: The frontend is built with simple, server-rendered HTML templates (using Jinja) and styled with **TailwindCSS**. Vanilla JavaScript is used to periodically fetch data from the unified API and dynamically update the content on all dashboards.

### 2. Background Services

These are standalone Python scripts intended to run continuously (e.g., as systemd services) to collect and process data.

* **`data_ingestor.py`**: The "collector." It connects to each configured miner via its USB serial port, reads its log output line by line, parses the data, and writes the raw logs to the database.
* **`summarizer.py`**: The "aggregator." It periodically reads the raw logs from the `data_ingestor.py` and calculates summary statistics (like average hash rate, total shares, etc.). This summary data is stored in a separate table for fast dashboard loading.
* **`price_updater.py`**: The "pricer." It fetches the current BTC price from an external API (CoinCodex) and caches it in a local JSON file for use by the web application.
* **`device_discovery.py`**: The "onboarder." It uses `pyudev` to listen for new USB TTY devices being plugged in. When a new device is found, it's added to an `unconfigured_devices` table so it can be officially onboarded via the web UI.

### 3. Data Layer

* **SQLite Database (`shepherd.db`)**: A central SQLite database is used to store all persistent data, including:
    * `miners`: The list of configured miners and their settings.
    * `unconfigured_devices`: A temporary holding table for newly discovered devices.
    * `miner_logs`: A high-volume table for all raw log output from the miners.
    * `miner_summary`: The aggregated summary data used to power the dashboards.
    * `pools` & `coin_addresses`: Tables for managing pool and wallet configurations.
* **JSON Cache (`btc_price.json`)**: A simple JSON file used to cache price data, reducing external API calls.

## (In-Progress)
* Installation
* Usage

---
## A Note on "Winning" a block with ESP32 Miners

This project is a fantastic tool for managing a farm of "lottery miners."

However, a word to the wise from one who sees the numbers: the odds of one of these micro-miners *actually* solving a block are... well, "astronomical" is an understatement.

Consider this a fun, educational hobby and a great way to learn about the Bitcoin network. Don't consider it a financial plan. 😅

- J