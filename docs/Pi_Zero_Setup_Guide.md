Feature: Pi Zero Setup Guide & Installation Script
==================================================

1\. Overview
------------

The goal of this feature is to create a comprehensive, step-by-step guide and an accompanying installation script that allows a user to deploy the Shepherd application onto a headless Raspberry Pi Zero from a fresh OS installation. This will make the project easily reproducible and lower the barrier to entry for new users.

2\. Target Environment
----------------------

-   **Hardware:** Raspberry Pi Zero W / Raspberry Pi Zero 2 W

-   **Operating System:** Raspberry Pi OS Lite (64-bit), based on Debian "Trixie"

-   **Setup Type:** Headless (no monitor, keyboard, or mouse connected to the Pi after initial flashing).

3\. High-Level Plan
-------------------

The process will be broken down into two main deliverables:

1.  A detailed, user-facing markdown document (`INSTALL.md`) that explains every step of the process.

2.  A shell script (`install.sh`) that automates the software installation and service configuration steps.

4\. Detailed Setup Phases
-------------------------

The documentation and script will follow this logical progression:

### Phase 1: SD Card Preparation (Manual User Steps)

This phase will be documented in `INSTALL.md` for the user to perform on their main computer.

1.  **Download Raspberry Pi Imager:** Provide a link to the official tool.

2.  **Flash the OS:**

    -   Select the Pi Zero.

    -   Select Raspberry Pi OS Lite (64-bit).

    -   Use the "Advanced Options" to pre-configure:

        -   **SSH:** Enable SSH with a secure password.

        -   **Hostname:** Set the hostname (e.g., `shepherd`).

        -   **User Account:** Create the main user account (e.g., `shepherd_admin`).

        -   **Wi-Fi:** Pre-configure the Wi-Fi credentials to allow the Pi to automatically connect to the local network on first boot.

3.  **Write and Eject:** Write the image to the SD card.

### Phase 2: First Boot & System Configuration (Manual User Steps)

The user will now insert the SD card into the Pi, power it on, and connect via SSH from their main computer.

1.  **Find the Pi's IP Address:** Explain how to find the IP using a router's device list or a network scanner.

2.  **Connect via SSH:** `ssh shepherd_admin@shepherd.local`

3.  **System Updates:** Run initial system updates.

    -   `sudo apt update`

    -   `sudo apt full-upgrade -y`

4.  **Raspberry Pi Configuration Tool:**

    -   `sudo raspi-config`

    -   Instruct the user to navigate to `Advanced Options` -> `Expand Filesystem`.

    -   Instruct the user to set the correct localization and timezone options.

### Phase 3: Shepherd Installation (Automated via `install.sh`)

The user will download and execute our new installation script, which will handle the rest.

1.  **Download the Script:**

    -   `wget https://raw.githubusercontent.com/[your_repo]/shepherd/main/install.sh`

    -   `chmod +x install.sh`

2.  **Run the Script:**

    -   `./install.sh`

3.  **Script Actions:** The `install.sh` script will perform the following actions automatically:

    -   **Install Dependencies:** Install all required system packages using `apt`. This includes `git`, `python3-pip`, `python3-venv`, `libudev-dev`, and any other libraries needed by our Python dependencies.

    -   **Clone the Repository:** Clone the Shepherd project from GitHub into the user's home directory (e.g., `~/shepherd`).

    -   **Set up Python Virtual Environment:** Create a Python virtual environment (`venv`) inside the `~/shepherd` directory to isolate our project's dependencies.

    -   **Install Python Packages:** Activate the `venv` and install all required Python packages from a `requirements.txt` file (which we will also need to create). This includes `Flask`, `waitress`, `pyserial`, `pyudev`, `psutil`, etc.

    -   **Create Data Directory:** Create the `~/shepherd_data` directory for the database and price cache.

    -   **Install Systemd Services:** Copy the pre-written `.service` files from a new `services/` directory in our repository to `/etc/systemd/system/`.

    -   **Enable & Start Services:** Use `systemctl enable` and `systemctl start` to activate all the Shepherd background services (`shepherd-ingestor.service`, `shepherd-summarizer.service`, `shepherd-pricer.service`, `shepherd-device-discovery.service`) and the main web application (`shepherd-app.service`).

### Phase 4: Final Verification (Manual User Steps)

The final section of `INSTALL.md` will guide the user on how to verify the installation was successful.

1.  **Check Service Status:** Show the user how to run `systemctl status shepherd-*.service` to confirm all services are "active (running)".

2.  **Access the Web UI:** Instruct the user to open a web browser on their main computer and navigate to `http://shepherd.local:5000`.

3.  **Troubleshooting:** Provide a small section for common issues (e.g., service failed to start, can't access web UI).

5\. Required New Files
----------------------

To complete this feature, we will need to create:

-   `INSTALL.md`: The main user-facing guide.

-   `install.sh`: The automated installation script.

-   `requirements.txt`: A list of all Python package dependencies.

-   A new `services/` directory containing the `.service` files for systemd.