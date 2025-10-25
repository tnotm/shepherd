Planning Doc: Miner Discovery & Database Updates
================================================

1\. Objective
-------------

To adapt our database schema to support the new "smarter" device discovery process. This involves capturing the miner's configuration (Pool, Wallet, Version) directly from its serial boot-up text dump and, most critically, **managing the miner's state to prevent port conflicts** between different Shepherd services.

2\. New State-Machine Model
---------------------------

This plan introduces a formal state machine, managed by `device_discovery.py` and respected by all other services.

### Status Field (The "Traffic Cop")

This field controls which service "owns" the miner.

-   **`Inactive`**: The miner is not connected. `data_ingestor` and `summarizer` will **ignore** it.

-   **`Initializing`**: The miner is plugged in, but `device_discovery.py` **owns the port** and is listening for the boot-up handshake. `data_ingestor` and `summarizer` will **ignore** it.

-   **`Active`**: `device_discovery.py` has confirmed the miner is fully connected to the pool (it saw "Mining Authorize") and has **released the port**. `data_ingestor` and `summarizer` will **now monitor** this miner.

### State Field (The Granular Step)

This field tracks the *sub-state* of the `Initializing` status, based on the log output.

-   `Booting` (Default state when plugged in)

-   `WORKER Started`

-   `MINER HW Task Started`

-   `CONNECTED IP`

-   `DNS Resolved`

-   `Mining Subscribe`

-   `Mining Authorize` (The final step before becoming `Active`)

3\. Proposed Table Definitions
------------------------------

Here is how we'll adapt our tables to manage this new state machine.

**`unconfigured_devices` (The Staging Table)** This table holds newly-plugged-in devices *before* they are officially named and added to the "flock."

-   `id` (INTEGER): Primary Key

-   `dev_path` (TEXT): The OS path (e.g., `/dev/ttyACM0`)

-   `port_path` (TEXT): The physical USB port path (e.g., `1-1.2`)

-   `vendor_id` (TEXT)

-   `product_id` (TEXT)

-   `serial_number` (TEXT): The device's unique hardware serial.

-   `discovered_at` (TEXT)

-   **`status` (TEXT):** (NEW) Will be set to `Initializing`.

-   **`state` (TEXT):** (NEW) Will track the handshake steps (e.g., "Booting", "DNS Resolved").

-   **`dumped_pool_url` (TEXT):** (NEW) To store the Pool URL from the serial dump.

-   **`dumped_wallet_address` (TEXT):** (NEW) To store the Wallet Address from the serial dump.

-   **`dumped_firmware_version` (TEXT):** (NEW) To store the firmware version (if found).

**`miners` (The Permanent "Flock" Table)** This table holds all known, named miners and their current status.

-   `id` (INTEGER): Primary Key

-   `miner_id` (TEXT): The user-given friendly name (e.g., "MINER_001")

-   `chipset` (TEXT): (User-provided)

-   `dev_path` (TEXT): The *last known* OS path.

-   `port_path` (TEXT): The *last known* physical port path.

-   `location_notes` (TEXT): (User-provided)

-   `attrs_idVendor` (TEXT)

-   `attrs_idProduct` (TEXT)

-   `attrs_serial` (TEXT): **This is now the unique key for the** ***miner***.

-   **`status` (TEXT):** (NEW) `Inactive`, `Initializing`, or `Active`. Default: `Inactive`.

-   **`state` (TEXT):** (NEW) Tracks the handshake steps for re-connecting miners.

-   `last_seen` (TEXT)

-   **`currency` (TEXT):** (NEW) The mandatory field the user must select (e.g., "BTC", "LTC").

-   **`pool_url` (TEXT):** (NEW) Copied from `dumped_pool_url` on onboarding.

-   **`wallet_address` (TEXT):** (NEW) Copied from `dumped_wallet_address`.

-   `nerdminer_vrs` (This will now be populated from `dumped_firmware_version`)

-   `nerdminer_rom` (This field may no longer be necessary).

4\. New Discovery & Onboarding Logic (Process Flow)
---------------------------------------------------

This is the new "hand-off" process that solves our race condition.

### A. The "Smart Discovery" Process (in `device_discovery.py`)

1.  **Device "Add" Event:** A new device is plugged in. `pyudev` detects it.

2.  The script gets the `dev_path`, `port_path`, and `serial_number`.

3.  **Key Check:** The script queries the `miners` table: `SELECT id FROM miners WHERE attrs_serial = ?`

4.  **IF (Miner Not Found):** This is a **New Device**.

    -   The script runs: `INSERT INTO unconfigured_devices (serial_number, dev_path, port_path, status, state, ...)`

    -   The `status` is set to `Initializing` and `state` is set to `Booting`.

    -   The script **holds the port open**, listens to the serial dump, and:

        -   Parses the Config JSON and `UPDATE`s the `dumped_...` fields.

        -   Listens for the handshake lines. As each is found, it runs: `UPDATE unconfigured_devices SET state = '...' WHERE id = ?`

        -   When it sees `"Mining Authorize"`, it stops. It does **NOT** set to `Active`. It leaves the miner in the "Discovered" list for the user to configure.

    -   The script **closes the port** and continues monitoring for other new devices.

5.  **IF (Miner Found):** This is a **Re-connection**.

    -   The script runs: `UPDATE miners SET dev_path = ?, port_path = ?, status = 'Initializing', state = 'Booting' WHERE attrs_serial = ?`

    -   The script **holds the port open**, just like with a new device, listening for the handshake.

    -   As it sees each step, it runs: `UPDATE miners SET state = '...' WHERE attrs_serial = ?`

    -   When it finally sees `"Mining Authorize"`, it runs its final command: `UPDATE miners SET status = 'Active', state = 'Mining' WHERE attrs_serial = ?`

    -   The script **closes the port**. The `data_ingestor` will now pick up this "Active" miner on its next cycle.

### B. The "Device Remove" Process (in `device_discovery.py`)

1.  **Device "Remove" Event:** A miner is unplugged. `pyudev` detects it.

2.  The script gets the `dev_path` of the removed device.

3.  The script runs: `UPDATE miners SET status = 'Inactive', state = 'Not Connected', dev_path = NULL, port_path = NULL WHERE dev_path = ?`

4.  This instantly and safely removes the miner from the `data_ingestor`'s and `summarizer`'s query pool, preventing errors.

### C. The "New Onboarding" Process (in `config.html` / `routes.py`)

1.  User goes to the Config page. They see the new device (from `unconfigured_devices`) listed, along with its read-only Pool and Wallet.

2.  The UI has two required fields: **Miner Name** and **Currency**. (We can pre-fill the name from the `.btcString` if we want).

3.  User fills in "MINER_010," selects "BTC," and clicks "Onboard."

4.  The backend route (`onboard_miner`) now does the following:

    -   It reads the `unconfigured_devices` row.

    -   It runs: `INSERT INTO miners (miner_id, currency, attrs_serial, dev_path, port_path, pool_url, wallet_address, nerdminer_vrs, status, state, ...)` by copying *all* the relevant data.

    -   The `status` is set to `Inactive` (as the device is no longer being actively monitored by discovery). The next time it's plugged in, it will be treated as a "Re-connection."

    -   It runs: `DELETE FROM unconfigured_devices WHERE id = ?`

    -   The miner is now fully part of the "flock."