// static/js/config_manager.js
// V.1.0.2 - Refactored modal open/close logic to prevent state-clearing bug

// --- Global State & Pane Navigation (unchanged) ---
let isModalOpen = false;
let currentModalData = null;
const liveIndicator = document.getElementById('live-indicator');
const ajaxFlashContainer = document.getElementById('ajax-flash-container');
const deviceGrid = document.getElementById('device-grid'); // Cache grid element
const allModalIDs = [
    'details-modal', 'actions-modal', 'configure-modal',
    'delete-modal', 'edit-modal'
];

function showPane(paneId, element) {
    window.location.hash = paneId;
    document.querySelectorAll('.content-pane').forEach(pane => pane.classList.add('hidden'));
    document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'));
    document.getElementById('pane-' + paneId).classList.remove('hidden');
    if (element) { element.classList.add('active'); }
    else { document.querySelector(`.nav-link[href="#${paneId}"]`).classList.add('active'); }
}

// --- Live Data Fetching (unchanged) ---
async function fetchDeviceData() {
    if (isModalOpen) {
        // console.log("[fetch] Skipping, modal open."); // Less verbose log
        return;
    }
    // console.log("[fetch] Starting..."); // DEBUG
    try {
        liveIndicator.classList.remove('bg-red-500', 'bg-gray-500'); liveIndicator.classList.add('bg-yellow-500');
        const apiUrl = document.body.dataset.urlApiDeviceState;
        if (!apiUrl) throw new Error("API URL data attribute not found on body.");

        const response = await fetch(apiUrl);
        // console.log(`[fetch] Status: ${response.status}`); // DEBUG
        if (!response.ok) { throw new Error(`Network error: ${response.status} ${response.statusText}`); }

        const responseText = await response.text();
        // console.log("[fetch] Raw text received (first 100 chars):", responseText.substring(0, 100)); // DEBUG

        let devices = [];
        let apiError = null;

        if (!responseText || responseText.trim() === '') {
            // console.warn("[fetch] API returned empty response."); // DEBUG
        } else {
            try {
                const parsedJson = JSON.parse(responseText);
                // console.log("[fetch] Parsed JSON:", parsedJson); // DEBUG

                if (typeof parsedJson === 'object' && parsedJson !== null && 'error' in parsedJson && 'devices' in parsedJson) {
                    apiError = parsedJson.error; devices = parsedJson.devices;
                    console.warn("[fetch] API reported dog error:", apiError);
                } else if (Array.isArray(parsedJson)) {
                    devices = parsedJson;
                    // console.log(`[fetch] Parsed array with ${devices.length} devices.`); // DEBUG
                } else {
                    throw new Error("Parsed JSON was not an array or expected error object.");
                }
            } catch (parseError) {
                console.error("[fetch] JSON parse failed:", parseError);
                console.error("[fetch] Failed text:", responseText); // Log the text again on failure
                throw new Error("Invalid JSON received from API.");
            }
        }

        // --- Rendering Logic ---
        deviceGrid.innerHTML = ''; // Clear previous content

        if (apiError) {
            deviceGrid.innerHTML = `<p class="text-red-400 col-span-full">Dog Service Error: ${apiError}. Check service logs.</p>`;
        } else if (devices.length === 0) {
            deviceGrid.innerHTML = '<p class="text-gray-500 col-span-full">Dog running, no devices currently detected or configured.</p>';
        } else {
            // console.log("[fetch] Starting to render device bubbles..."); // DEBUG
            devices.forEach((device, index) => {
                if (!device || typeof device !== 'object') {
                    console.error(`[fetch] Invalid device data at index ${index}. Skipping.`);
                    return; // Skip this iteration
                }
                const deviceStatus = device.display_status || 'Unknown';
                // console.log(`[fetch]   Device status: ${deviceStatus}`); // DEBUG

                const bubble = document.createElement('div');
                const classes = getStatusClass(deviceStatus);
                // console.log(`[fetch]   Calculated classes:`, classes); // DEBUG

                bubble.className = classes.bubble;
                bubble.innerHTML = `<span class="text-sm font-bold block truncate w-full">${device.miner_id || device.port_path || 'Unknown'}</span> <span class="${classes.pill}">${deviceStatus}</span>`;
                bubble.onclick = () => openModal(device);

                try {
                     deviceGrid.appendChild(bubble);
                     // console.log(`[fetch]   Successfully appended bubble for device ${index}.`); // DEBUG
                } catch (appendError) {
                     console.error(`[fetch]   ERROR appending bubble for device ${index}:`, appendError);
                     console.error(`[fetch]   Problematic device data:`, device);
                }
            });
            // console.log("[fetch] Finished rendering bubbles."); // DEBUG
        }
        liveIndicator.classList.remove('bg-yellow-500'); liveIndicator.classList.add('bg-green-500');

    } catch (error) {
        // --- Catch block ---
        console.error('[fetch] Main fetch/render error:', error); // Log the main error
        liveIndicator.classList.remove('bg-yellow-500', 'bg-green-500'); liveIndicator.classList.add('bg-red-500');
        deviceGrid.innerHTML = `<p class="text-red-400 col-span-full">Error loading/displaying data: ${error.message}. Check browser console & Dog logs.</p>`;
    }
}


// --- getStatusClass (unchanged) ---
function getStatusClass(status) {
    const lowerStatus = String(status || '').toLowerCase();
    const baseClasses = "h-24 p-4 rounded-lg text-white font-semibold shadow-md flex flex-col justify-between items-center text-center cursor-pointer transition-all duration-150 ease-in-out transform hover:scale-105";
    const pillBase = "text-xs font-normal block mt-1 px-2 py-0.5 rounded-full";
    if (lowerStatus === 'online') return { bubble: `${baseClasses} bg-green-700 hover:bg-green-600`, pill: `${pillBase} bg-green-200 text-green-900` };
    if (lowerStatus === 'stale') return { bubble: `${baseClasses} bg-yellow-700 hover:bg-yellow-600`, pill: `${pillBase} bg-yellow-200 text-yellow-900` };
    if (lowerStatus === 'offline') return { bubble: `${baseClasses} bg-red-800 hover:bg-red-700`, pill: `${pillBase} bg-red-200 text-red-900` };
    if (lowerStatus === 'inactive' || lowerStatus === 'synced' || lowerStatus === 'captured' || lowerStatus === 'verified' || lowerStatus === 'onboarded' || lowerStatus === 'detected') return { bubble: `${baseClasses} bg-gray-700 hover:bg-gray-600 opacity-60`, pill: `${pillBase} bg-gray-300 text-gray-800` };
    if (lowerStatus === 'unconfigured' || lowerStatus === 'unconfigured (captured)') return { bubble: `${baseClasses} bg-blue-700 hover:bg-blue-600`, pill: `${pillBase} bg-blue-200 text-blue-900` };
    if (lowerStatus.includes('error') || lowerStatus.includes('failed') || lowerStatus === 'capture failed') return { bubble: `${baseClasses} bg-red-800 hover:bg-red-700`, pill: `${pillBase} bg-red-200 text-red-900` };
    console.warn(`[getStatusClass] Unknown status encountered: '${status}'`);
    return { bubble: `${baseClasses} bg-purple-700 hover:bg-purple-600`, pill: `${pillBase} bg-purple-200 text-purple-900` };
}

// --- *** NEW MODAL LOGIC *** ---

/**
 * Closes all visible modals and resets the global state.
 * This is the single function to call when closing *any* modal.
 */
function closeModal() {
    allModalIDs.forEach(id => {
        const modal = document.getElementById(id);
        if (modal) {
            modal.classList.add('hidden');
        }
    });
    // Reset state *after* all modals are hidden
    isModalOpen = false;
    currentModalData = null;
    // console.log("[closeModal] All modals closed, state reset."); // DEBUG
    setTimeout(fetchDeviceData, 150); // Fetch new data
}

/**
 * Opens a modal based on the device data provided.
 * This function now handles all state and visibility logic.
 */
function openModal(deviceData) {
    if (!deviceData) {
        console.error("openModal called with invalid deviceData");
        return;
    }

    // 1. Set global state IMMEDIATELY
    isModalOpen = true;
    currentModalData = deviceData;
    const status = String(deviceData.display_status || '').toLowerCase();
    // console.log("[openModal] State set for:", deviceData); // DEBUG

    // 2. Hide all modals *without* resetting state
    allModalIDs.forEach(id => {
        const modal = document.getElementById(id);
        if (modal) modal.classList.add('hidden');
    });

    // 3. Populate modal content
    let modalIdToShow = null;

    if (deviceData.type === 'miner') {
        const isEffectivelyOnline = status === 'online' || status === 'stale';

        // Populate Details Modal
        document.getElementById('details-miner-id').textContent = deviceData.miner_id || 'N/A';
        document.getElementById('details-status').textContent = deviceData.display_status || 'N/A';
        document.getElementById('details-pool').textContent = deviceData.pool_url || 'N/A';
        document.getElementById('details-wallet').textContent = deviceData.wallet_address || 'N/A';
        document.getElementById('details-version').textContent = deviceData.version || 'N/A';
        document.getElementById('details-dev-path').textContent = deviceData.dev_path || 'N/A';
        document.getElementById('details-port-path').textContent = deviceData.port_path || 'N/A';
        document.getElementById('details-serial').textContent = deviceData.serial_number || 'N/A';
        document.getElementById('details-mac').textContent = deviceData.mac_address || 'N/A';
        document.getElementById('details-chipset').textContent = deviceData.chipset || 'N/A';
        document.getElementById('details-location').textContent = deviceData.location_notes || 'N/A';

        // Populate Actions Modal
        document.getElementById('actions-miner-id').textContent = deviceData.miner_id || 'N/A';
        document.getElementById('actions-status').textContent = deviceData.display_status || 'N/A';
        document.getElementById('actions-state').textContent = deviceData.state_msg || 'N/A';
        document.getElementById('actions-dev-path').textContent = deviceData.dev_path || 'N/A';
        document.getElementById('actions-port-path').textContent = deviceData.port_path || 'N/A';
        document.getElementById('actions-serial').textContent = deviceData.serial_number || 'N/A';
        document.getElementById('actions-mac').textContent = deviceData.mac_address || 'N/A';
        document.getElementById('actions-chipset').textContent = deviceData.chipset || 'N/A';
        document.getElementById('actions-location').textContent = deviceData.location_notes || 'N/A';

        // Decide which modal to show
        modalIdToShow = isEffectivelyOnline ? 'details-modal' : 'actions-modal';

    } else if (deviceData.type === 'stray') {
        // Populate Configure Modal
        document.getElementById('config-dev-path').textContent = deviceData.dev_path || 'N/A';
        document.getElementById('config-port-path').textContent = deviceData.port_path || 'N/A';
        document.getElementById('config-serial').textContent = deviceData.serial_number || 'N/A';
        document.getElementById('config-vendor').textContent = deviceData.vendor_id || 'N/A';
        document.getElementById('config-product').textContent = deviceData.product_id || 'N/A';

        // Reset form fields
        document.getElementById('onboard_miner_id').value = '';
        document.getElementById('onboard_location_notes').value = '';
        document.getElementById('onboard_currency').value = 'BTC';

        // Populate captured info section
        const capturedInfoDiv = document.getElementById('config-captured-info');
        const hasCapturedData = deviceData.pool_url || deviceData.wallet_address || deviceData.version || deviceData.chipset || deviceData.mac_address;
        document.getElementById('config-captured-chipset').textContent = deviceData.chipset || 'N/A';
        document.getElementById('config-captured-mac').textContent = deviceData.mac_address || 'N/A';
        document.getElementById('config-captured-pool').textContent = deviceData.pool_url || 'N/A';
        document.getElementById('config-captured-wallet').textContent = deviceData.wallet_address || 'N/A';
        document.getElementById('config-captured-version').textContent = deviceData.version || 'N/A';
        capturedInfoDiv.classList.toggle('hidden', !hasCapturedData);

        // Populate hidden form fields
        document.getElementById('config-form-dev-path').value = deviceData.dev_path || '';
        document.getElementById('config-form-port-path').value = deviceData.port_path || '';
        document.getElementById('config-form-serial').value = deviceData.serial_number || '';
        document.getElementById('config-form-vendor').value = deviceData.vendor_id || '';
        document.getElementById('config-form-product').value = deviceData.product_id || '';
        document.getElementById('config-form-pool').value = deviceData.pool_url || '';
        document.getElementById('config-form-wallet').value = deviceData.wallet_address || '';
        document.getElementById('config-form-version').value = deviceData.version || '';
        document.getElementById('config-form-chipset').value = deviceData.chipset || '';
        document.getElementById('config-form-mac').value = deviceData.mac_address || '';

        modalIdToShow = 'configure-modal';

    } else {
         console.error("openModal called with unknown device type:", deviceData.type);
         isModalOpen = false; // Reset state
         currentModalData = null;
         return; // Don't show any modal
    }

    // 4. Show the correct modal
    if (modalIdToShow) {
        const modal = document.getElementById(modalIdToShow);
        if (modal) {
            modal.classList.remove('hidden');
            // console.log(`[openModal] Successfully opened: ${modalIdToShow}`); // DEBUG
        } else {
            console.error(`[openModal] Modal ID to show was not found: ${modalIdToShow}`);
            isModalOpen = false; // Reset state
            currentModalData = null;
        }
    }
}


// Add event listener to close modals when clicking outside
document.addEventListener('click', (event) => {
    // If a modal is open AND the click was *not* inside a modal panel
    if (isModalOpen && !event.target.closest('.bg-gray-800.rounded-lg')) {
        // console.log("[ClickOutside] Click detected, closing modal."); // DEBUG
        closeModal(); // Call the single, simple close function
    }
});


function showEditForm() {
    if (!currentModalData || currentModalData.type !== 'miner') return;
    // Populate edit form
    document.getElementById('edit_miner_id').value = currentModalData.miner_id || '';
    document.getElementById('edit_chipset').value = currentModalData.chipset || '';
    document.getElementById('edit_nerdminer_vrs').value = currentModalData.version || '';
    document.getElementById('edit_location_notes').value = currentModalData.location_notes || '';
    // Set form action URL
    const editForm = document.getElementById('edit-form');
    editForm.action = `/miners/edit/${currentModalData.id}`;

    // Hide actions modal, show edit modal
    document.getElementById('actions-modal').classList.add('hidden');
    document.getElementById('edit-modal').classList.remove('hidden');
    isModalOpen = true; // Ensure modal state is kept
}

function showDeleteForm() {
    if (!currentModalData || currentModalData.type !== 'miner') return;
    // Populate delete confirmation text
    document.getElementById('delete-miner-name').textContent = currentModalData.miner_id || 'this miner';
    // Set form action URL
    const deleteForm = document.getElementById('delete-form');
    deleteForm.action = `/miners/delete/${currentModalData.id}`;

    // Hide actions modal, show delete modal
    document.getElementById('actions-modal').classList.add('hidden');
    document.getElementById('delete-modal').classList.remove('hidden');
    isModalOpen = true; // Ensure modal state is kept
}


// --- AJAX Actions (Unchanged from V.1.0.1) ---
async function onboardStray(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);
    const submitButton = form.querySelector('button[type="submit"]');
    submitButton.disabled = true; submitButton.textContent = 'Adding...';

    const onboardUrl = document.body.dataset.urlOnboardStray; // Get URL from body

    try {
        const response = await fetch(onboardUrl, { method: 'POST', body: formData });
        const result = await response.json();
        if (response.ok && result.success) {
            showAjaxFlash(result.message, 'success');
            closeModal(); // Close and trigger refresh
        } else {
            showAjaxFlash(result.message || 'Onboarding failed.', 'error');
        }
    } catch (error) {
        console.error('Onboard error:', error);
        showAjaxFlash('Network error during onboarding.', 'error');
    } finally {
        if (submitButton) { submitButton.disabled = false; submitButton.textContent = 'Add to Flock'; }
    }
}

async function runMinerAction(actionButton) {
    console.log("[runAction] Called.");
    if (!currentModalData) { console.error("[runAction] No currentModalData."); return; } // This was the error

    const actionUrl = document.body.dataset.urlMinerAction; // Get URL from body
    if (!actionUrl) { console.error("[runAction] No action URL found on body."); return; }

    let originalButtonText = actionButton.textContent;
    actionButton.disabled = true; actionButton.textContent = 'Working...';
    // console.log("[runAction] Button disabled."); // DEBUG

    const payload = {
        action: 'reset_capture',
        dev_path: currentModalData.dev_path,
        port_path: currentModalData.port_path,
        serial_number: currentModalData.serial_number,
        miner_db_id: currentModalData.type === 'miner' ? currentModalData.id : null
    };
    console.log("[runAction] Payload:", payload);

    try {
        // console.log("[runAction] Fetching:", actionUrl); // DEBUG
        const response = await fetch(actionUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        // console.log("[runAction] Status:", response.status); // DEBUG

        const result = await response.json();
        console.log("[runAction] Result:", result);

        if (response.ok && result.success) {
            showAjaxFlash(result.message, 'success');

            // Special handling for stray config capture: update data and reopen modal
            if (result.data && currentModalData.type === 'stray') {
                // console.log("[runAction] Success (stray data capture). Merging & reopening..."); // DEBUG
                // Merge new data into currentModalData
                currentModalData = { ...currentModalData, ...result.data };
                // We don't call closeModal(), just re-populate and re-show
                openModal(currentModalData); // Re-run openModal with *new* data
                // Re-enable the button in the *newly* opened modal
                setTimeout(() => {
                     const newButton = document.querySelector('#configure-modal button[onclick*="runMinerAction"]');
                     if (newButton) {
                          newButton.disabled = false;
                          newButton.textContent = originalButtonText;
                          // console.log("[runAction] Button re-enabled in reopened modal."); // DEBUG
                     }
                }, 150);
            } else {
                 // console.log("[runAction] Success (miner action or non-stray capture). Closing modal..."); // DEBUG
                 closeModal(); // Close and trigger refresh
            }

        } else {
            console.error("[runAction] Backend action failed:", result.message);
            showAjaxFlash(result.message || 'Action failed.', 'error');
            actionButton.disabled = false; // Re-enable on failure
            actionButton.textContent = originalButtonText;
        }
    } catch (error) {
        console.error("[runAction] Network/parse error:", error);
        showAjaxFlash('Network error during action.', 'error');
        actionButton.disabled = false; // Re-enable on failure
        actionButton.textContent = originalButtonText;
    }
}


// --- showAjaxFlash (unchanged) ---
function showAjaxFlash(message, category = 'success') {
    const flashDiv = document.createElement('div');
    const bgColor = category === 'error' ? 'bg-red-800' : 'bg-green-800';
    const textColor = category === 'error' ? 'text-red-200' : 'text-green-200';
    flashDiv.className = `flex items-center justify-between p-4 mb-4 text-sm rounded-lg ${bgColor} ${textColor} transition-opacity duration-500`;
    flashDiv.innerHTML = `
        <span>${message}</span>
        <button type="button" onclick="this.parentElement.style.opacity='0'; setTimeout(() => this.parentElement.remove(), 500)" class="ml-4 -mr-1.5 -my-1.5 bg-transparent rounded-lg p-1.5 inline-flex items-center justify-center text-current hover:bg-white/20">
            <svg class="w-3 h-3" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 14 14"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/></svg>
        </button>
    `;
    ajaxFlashContainer.appendChild(flashDiv);
    setTimeout(() => {
        flashDiv.style.opacity = '0';
        setTimeout(() => flashDiv.remove(), 500);
    }, 5000);
}

// --- Legacy Functions (Pools, Addresses - unchanged) ---
function openDeleteModal(deleteUrl, itemType, itemName) {
    const modal = document.getElementById('delete-modal');
    document.getElementById('delete-item-type').textContent = itemType;
    document.getElementById('delete-item-name').textContent = itemName;
    modal.querySelector('form').action = deleteUrl;
    
    // Hide other modals, show this one
    allModalIDs.forEach(id => document.getElementById(id)?.classList.add('hidden'));
    modal.classList.remove('hidden');
    isModalOpen = true; // Set modal state
}

// --- Page Initializer (unchanged) ---
document.addEventListener('DOMContentLoaded', function() {
    const hash = window.location.hash.substring(1);
    if (hash && document.getElementById('pane-' + hash)) {
        showPane(hash);
    } else {
        showPane('miners');
    }

    const dynamicRadio = document.getElementById('user_type_dynamic');
    const textRadio = document.getElementById('user_type_text');
    function updateUserTypeVisibility() {
        const dynamicUserDiv = document.getElementById('dynamic_user_address_div');
        const textUserDiv = document.getElementById('text_user_address_div');
        if (!dynamicRadio || !textRadio || !dynamicUserDiv || !textUserDiv) return;
        if (dynamicRadio.checked) {
            dynamicUserDiv.classList.remove('hidden'); textUserDiv.classList.add('hidden');
        } else {
            dynamicUserDiv.classList.add('hidden'); textUserDiv.classList.remove('hidden');
        }
    }
    if(dynamicRadio) dynamicRadio.addEventListener('change', updateUserTypeVisibility);
    if(textRadio) textRadio.addEventListener('change', updateUserTypeVisibility);
    updateUserTypeVisibility();

    fetchDeviceData();
    setInterval(fetchDeviceData, 3000);

    const flashMessages = document.querySelectorAll('[id^="flash-message-"]');
    flashMessages.forEach(function(message) {
        setTimeout(function() {
            message.style.opacity = '0';
            setTimeout(function() { message.style.display = 'none'; }, 500);
        }, 5000);
    });
});

