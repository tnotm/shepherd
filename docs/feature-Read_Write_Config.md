Feature: Read and Write Miner Configuration
===========================================

1\. Overview
------------

The goal of this feature is to provide a mechanism within the Shepherd web application to remotely read a miner's current configuration (`config.json`) and to push a new configuration to the device. This will allow for centralized management of pool settings and wallet addresses without needing physical access to each miner's console.

2\. Proposed Architecture
-------------------------

### 2.1. Backend (`shepherd/routes.py`)

-   A new Flask route (e.g., `/miners/manage/<int:miner_id>`) will be created to serve a management page for a specific miner.

-   Two new API endpoints will be created:

    -   `POST /api/miner/<int:miner_id>/get_config`: This endpoint will add an entry to a new `miner_commands` table in the database, instructing the `data_ingestor` to fetch the config for the specified miner.

    -   `POST /api/miner/<int:miner_id>/set_config`: This endpoint will accept a JSON payload with the new configuration, add it to the `miner_commands` table, and instruct the `data_ingestor` to flash the new config.

### 2.2. Database (`shepherd/database.py`)

-   A new table, `miner_commands`, will be created with fields like `id`, `miner_id`, `command` (e.g., "GET_CONFIG", "SET_CONFIG"), `payload` (for new config data), `status` (e.g., "pending", "complete", "error"), and `created_at`.

-   A new field, `last_config_json`, will be added to the `miners` table to store the most recently fetched configuration for display.

### 2.3. Data Ingestor (`data_ingestor.py`)

-   The `data_ingestor` will be modified to become a two-way communication service.

-   Each miner's dedicated monitoring thread will periodically check the `miner_commands` table for any new "pending" commands for its assigned miner.

-   **For "GET_CONFIG":** The thread will send a specific command (e.g., `'c\n'`) over the serial port. It will then enter a "capture mode," listening for the specific lines of the configuration dump, parsing them into a JSON object, and storing the result back in the `miners` table.

-   **For "SET_CONFIG":** This is a more complex, multi-step process that will be orchestrated by the ingestor thread:

    1.  Read the new configuration from the `payload` field in the `miner_commands` table.

    2.  Write this configuration to a local temporary `config.json` file.

    3.  Use an external tool like `mkspiffs` to create a binary filesystem image (`spiffs.bin`) from this file.

    4.  Send a special hardware sequence over the serial port to force the miner into bootloader (flashing) mode.

    5.  Use an external tool like `esptool.py` to flash the `spiffs.bin` file to the correct memory partition on the miner.

    6.  Send a hardware reset command to reboot the miner with its new configuration.

    7.  Update the command status to "complete" or "error" in the database.

### Investigation Log & Current Status

**Status:** More Analysis Needed

**Summary:** After extensive testing with a standalone Python script (`command_tester.py`), we have determined that reliably writing a new configuration file to the miner's SPIFFS partition is not currently feasible.

**Key Findings:**

1.  **Read-on-Reset:** The miner's configuration is reliably dumped to the serial console only during its boot sequence after a forced hardware reset (via DTR line toggle). An interactive command to retrieve the config while running is not reliable.

2.  **Bootloader Mode:** We successfully reverse-engineered the hardware signal sequence (DTR/RTS toggles) required to reliably put the device into its ROM bootloader, matching the behavior of `esptool.py`.

3.  **`mkspiffs` is Unreliable:** The core problem is the `mkspiffs` command-line utility. All attempts to create a `spiffs.bin` image file using this tool---even with correct partition geometry and metadata flags---resulted in a corrupted filesystem. Flashing this corrupted binary causes the miner to lose its configuration and revert to its initial Access Point (AP) setup mode.

4.  **In-Memory Builder Failure:** An attempt to remove the `mkspiffs` dependency by building the filesystem image byte-by-byte in Python also failed, producing the same AP-mode reset. This proves that the SPIFFS structure expected by the NerdMiner firmware has undocumented specifics that we cannot reliably replicate.

**Conclusion:** The risk of "bricking" (reverting to AP mode) miners is too high. The fact that even the official NerdMiner software can be unstable with configuration saves suggests this is a deep-seated firmware/hardware issue. This feature is **shelved** until a 100% reliable method for creating and flashing a valid SPIFFS image can be discovered.

### **New Investigation Path: AP Configuration**

**Concept:** Instead of flashing a config file, force the miner into its native AP mode. The Shepherd server (the Pi) would then programmatically disconnect from its own network, connect to the miner's AP, submit the configuration via the miner's web portal, and then switch back to the main network.

**Analysis:**

-   **Pros:** This would bypass the entire unreliable SPIFFS flashing process and use the firmware's intended configuration method.

-   **Cons & Major Risks:**

    -   **Network Disruption:** This would require the Shepherd server to disconnect from its primary network, making the entire Shepherd web UI and all its services temporarily unavailable.

    -   **High Complexity:** Requires robust scripting to manage the Pi's network interfaces (`wpa_supplicant`, `nmcli`, etc.), handle the captive portal, and make HTTP requests.

    -   **Critical Failure Point:** If the script fails to reconnect the Pi to the main network, the Shepherd server could be knocked offline permanently, requiring manual intervention.

**Current Assessment:** While technically feasible, the risk of taking the central server offline makes this approach extremely dangerous for a production system. It remains a potential, but high-risk, avenue for future investigation.