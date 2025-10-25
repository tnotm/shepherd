Project Shepherd: Design & Process Updates (Summary)
----------------------------------------------------

This document outlines the revised workflow and data capture process for integrating new miners into the Shepherd system, along with the required UI and data-handling modifications.

### 1\. New Miner Discovery & Data Capture
 
The core process for discovering a new miner is being updated to capture all available data at the point of connection, rather than in separate steps.

-   **Previous Method:** A new miner was discovered (via `dmesg`), and a separate *ingester* process would later read its serial port.
-   **New Method:** The initial **`new_miner_discovery.py` script** will be modified. When it detects a new miner, it will *immediately* perform two data-capture actions:
    1.  **OS Attributes:** Read the `dmesg` output for hardware identifiers (e.g., serial number, product ID).
    2.  **Configuration Dump:** Open the new serial port and capture the miner's boot-up *text dump*, which contains its pre-programmed configuration.

### 2\. Configuration Data & UI Changes

The data captured from the serial port dump will now *dictate* the miner's configuration, and the user interface (`config.html`) must be changed to reflect this.

-   **Locked-Down Fields:** The **Pools** and **Addresses** fields in the config UI will no longer be user-editable. These fields will be *populated* from the data read directly from the miner's serial port text dump.
-   **New User-Input Field:** A new, mandatory field must be added for each miner: **Currency**.
    -   This will likely be a drop-down menu (e.g., BTC, ETH, LTC, etc.).
    -   This is required because the currency being mined is *not* included in the serial port configuration dump.

### 3\. Revised "New Miner" Workflow

This creates a new three-step process for adding a miner:

1.  **System Discovery:** The user physically plugs in a new miner. The discovery script runs, captures both `dmesg` and serial dump data, and populates the `miners` and `attributes` tables.
2.  **UI Naming:** The `config.html` page highlights the newly discovered (but unnamed) miner.
3.  **User Configuration:** The user provides a **Name** for the miner and selects its **Currency** from the new drop-down menu. The system saves this user-provided data, finalizing the miner's setup.

### 4\. Handling Re-connections & Updates

A new state must be managed: when a *known* miner (one we have a name for) is plugged into a *different* physical port.

-   **Action:** The system must recognize the miner by its `dmesg` serial number but see that its port/connection attributes have changed.
-   **Update:** It should *automatically update* the `attributes` table with the new connection data (e.g., new `/dev/ttyUSB` path) without requiring user intervention.

### 5\. Dynamic Dashboard & API Requirements

The dashboard must be upgraded to handle the new reality of multiple miners running multiple currencies.

-   **Dynamic Currency Display:**
    -   **Current State:** The dashboard shows only the market value for Bitcoin (BTC).
    -   **Future State:** The dashboard must dynamically display the market value for *all* currencies currently being mined by the user's active miners.
    -   **UI Logic:**
        -   If only one currency is active (e.g., three miners all on BTC), it can display a single, large value for that currency.
        -   If multiple currencies are active (e.g., BTC, LTC, DOGE), it must dynamically create display boxes (e.g., up to 6) to show the current value for *each* currency.
-   **Dynamic API Calls:**
    -   **Current State:** The backend makes one API call for the BTC price.
    -   **Future State:** The backend must be aware of all unique currencies active in the user's configuration and dynamically make API calls to fetch the current market value for *each one*.