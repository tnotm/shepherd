Feature: Unified Data API
=========================

1\. Overview
------------

The goal of this feature is to refactor the backend to provide a single, comprehensive API endpoint that serves all the necessary data for the various dashboards and the main index page. This will eliminate redundant code, improve performance, and create a clear separation between the data layer (backend) and the presentation layer (frontend).

2\. The Problem
---------------

Currently, the application has multiple, ad-hoc methods for fetching data for real-time updates:

-   `dash_matrix.html` calls `/api/dash/matrix`.

-   `dash_health.html` calls `/api/dash/health`.

-   `index.html` and `kiosk.html` re-fetch their entire HTML content, which is highly inefficient.

-   Some API routes were pre-formatting data (e.g., numbers to strings), which violates the principle of keeping the API data-only.

3\. The Solution: A Single Endpoint
-----------------------------------

A new, unified API endpoint `/api/herd_data` will be created. This endpoint will be the single source of truth for all live data displays.

### 3.1. API JSON Structure

The `/api/herd_data` endpoint will return a JSON object with the following structure, containing raw, unformatted data:

```
{
  "herd_stats": {
    "total_miners": 10,
    "online_miners": 8,
    "total_hash_khs": 750.55,
    "total_shares": 12345,
    "total_block_templates": 56,
    "best_difficulty": 1234567.89
  },
  "btc_price_data": {
    "price_usd": 68000.50,
    "change_24h": -1.25
  },
  "miners_list": [
    {
      "id": 1,
      "miner_id": "MINER_001",
      "nerdminer_vrs": "1.8.3",
      "status": "online",
      "KH/s": 78.50,
      "Temperature": 65.1,
      "Shares": 123,
      "Best difficulty": 12345.67,
      "Block templates": 5,
      "last_updated": "2025-10-18T14:30:00Z"
    },
    { ... }
  ]
}

```

### 3.2. Backend Refactoring (`routes.py`)

-   A new private helper function, `_get_herd_data()`, will be created to perform all database queries and assemble the comprehensive data object defined above. This function will be responsible for ensuring all returned data is in its raw format (integers, floats, etc.).

-   The new public route `/api/herd_data` will call `_get_herd_data()` and return its result as a JSON response.

-   The old API routes (`/api/dash/health`, `/api/dash/matrix`) will be removed.

-   The routes that render the initial HTML pages (`/`, `/kiosk`, `/dash/health`, `/dash/matrix`) will be simplified. They will no longer need to fetch data themselves; they will only render the static page structure. The data will be populated entirely by JavaScript.

### 3.3. Frontend Refactoring (HTML & JS)

-   **`dash_matrix.html`**: The `fetch` call will be changed from `/api/dash/matrix` to `/api/herd_data`. The `refreshData` function will be updated to parse the new, unified JSON structure.

-   **`dash_health.html`**: The `fetch` call will be changed from `/api/dash/health` to `/api/herd_data`. The `refreshData` function will be updated to parse the new JSON structure.

-   **`index.html`**: The inefficient `fetch(window.location.href)` logic will be completely replaced. A new `<script>` block will be added to call `/api/herd_data` on an interval and update the DOM elements (header stats and miner table rows) dynamically, just like the other dashboards.

-   **`kiosk.html`**: Same as `index.html`, its refresh logic will be converted to use the new API endpoint for efficient updates.