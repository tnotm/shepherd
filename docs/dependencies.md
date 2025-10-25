Shepherd Project Dependencies
=============================

This document outlines all external dependencies required to run the core Shepherd application. This list does not include tools used only for testing or diagnostics (e.g., `esptool.py`, `mkspiffs`).

1\. Python Libraries (pip)
--------------------------

These are the Python packages that must be installed, typically via `pip install -r requirements.txt`.

-   **`flask`**

    -   **Purpose:** The core web framework used to build and serve the entire web UI and the `/api/herd_data` endpoint.

    -   **Used In:** `shepherd/__init__.py`, `shepherd/routes.py`

-   **`waitress`**

    -   **Purpose:** A production-grade WSGI server. This is what we use to run the Flask application instead of the less stable built-in development server.

    -   **Used In:** `run.py`

-   **`pyserial`**

    -   **Purpose:** The essential library for communicating with the miners. It allows Python to read the data coming from the USB serial ports.

    -   **Used In:** `data_ingestor.py`

-   **`pyudev`**

    -   **Purpose:** Used to monitor the Linux `udev` subsystem. This is how the `device_discovery.py` service "listens" for new USB devices being plugged in.

    -   **Used In:** `device_discovery.py`

-   **`requests`**

    -   **Purpose:** A simple HTTP library used to fetch the current BTC price from the CoinCodex external API.

    -   **Used In:** `price_updater.py`

-   **`psutil`**

    -   **Purpose:** (Optional) Used to read the Pi's system health (CPU, RAM, disk usage) for the "System Health" details page.

    -   **Used In:** `shepherd/routes.py`

2\. System Tools (OS-level)
---------------------------

These are external command-line programs that the Shepherd application executes using `subprocess.run()`. These must be installed on the host operating system (Raspberry Pi OS).

-   **`systemctl`**

    -   **Purpose:** The standard Linux tool for controlling `systemd` services. The web app uses this to restart the background services from the "Developer Options" page.

    -   **Used In:** `shepherd/routes.py`

-   **`sudo`**

    -   **Purpose:** Used to grant root privileges to the `systemctl` commands. This is necessary because restarting system services requires administrator permissions.

    -   **Used In:** `shepherd/routes.py`