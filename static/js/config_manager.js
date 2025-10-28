// static/js/config_manager.js
// V.1.0.0
// Description: Handles all dynamic behavior for the configuration page (config.html).

// --- Global State ---
let isModalOpen = false;
let currentModalData = null;

// --- DOM Elements (cached for performance) ---
const bodyElement = document.body;
const liveIndicator = document.getElementById('live-indicator');
const deviceGrid = document.getElementById('device-grid');
const ajaxFlashContainer = document.getElementById('ajax-flash-container');
const detailsModal = document.getElementById('details-modal');
const actionsModal = document.getElementById('actions-modal');
const deleteModal = document.getElementById('delete-modal');
const editModal = document.getElementById('edit-modal');
const configureModal = document.getElementById('configure-modal');
const onboardForm = document.getElementById('onboard-form');

// --- URLs (read from data attributes) ---
const URLS = {
    apiDeviceState: bodyElement.dataset.urlApiState,
    onboardStray: onboardForm ? onboardForm.dataset.urlOnboard : null,
    runMinerAction: bodyElement.dataset.urlAction
};

// --- Pane Navigation ---
function showPane(paneId, element) {
    window.location.hash = paneId;
    document.querySelectorAll('.content-pane').forEach(pane => pane.classList.add('hidden'));
    document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'));
    
    const targetPane = document.getElementById('pane-' + paneId);
    if (targetPane) {
        targetPane.classList.remove('hidden');
    } else {
        console.error(`[showPane] Pane with ID 'pane-${paneId}' not found.`);
        // Optionally default to the miners pane if the hash is invalid
        document.getElementById('pane-miners').classList.remove('hidden');
        document.querySelector(`.nav-link[href="#miners"]`).classList.add('active');
        return;
    }

    if (element) {
        element.classList.add('active');
    } else {
        // If called without an element (e.g., on page load from hash), find the link
        const link = document.querySelector(`.nav-link[href="#${paneId}"]`);
        if (link) {
            link.classList.add('active');
        } else {
             // Fallback if link not found (shouldn't happen with valid hash)
            document.querySelector(`.nav-link[href="#miners"]`).classList.add('active');
        }
    }
}

// --- Live Data Fetching & Display ---
async function fetchDeviceData() {
    if (isModalOpen) {
        // console.log("[fetch] Skipping, modal open."); // Optional: reduce console noise
        return;
    }
    // console.log("[fetch] Starting..."); // Optional: reduce console noise
    try {
        if (liveIndicator) {
             liveIndicator.classList.remove('bg-red-500', 'bg-gray-500');
             liveIndicator.classList.add('bg-yellow-500');
        }

        if (!URLS.apiDeviceState) {
            throw new Error("API state URL not found in body data attribute.");
        }
        
        const response = await fetch(URLS.apiDeviceState);
        // console.log("[fetch] Status:", response.status); // Optional: reduce console noise
        if (!response.ok) {
            throw new Error(`Network error: ${response.status} ${response.statusText}`);
        }
        
        const responseText = await response.text();
        // console.log("[fetch] Raw text:", responseText); // Optional: reduce console noise
        let devices = [];
        let apiError = null;

        try {
            const parsedJson = JSON.parse(responseText);
            if (typeof parsedJson === 'object' && parsedJson !== null && 'error' in parsedJson && 'devices' in parsedJson) {
                apiError = parsedJson.error;
                devices = parsedJson.devices;
                console.warn("[fetch] API reported dog error:", apiError);
            } else if (Array.isArray(parsedJson)) {
                devices = parsedJson;
                // console.log("[fetch] Parsed array:", devices); // Optional: reduce console noise
            } else {
                throw new Error("Response not array or error object.");
            }
        } catch (parseError) {
            console.error("[fetch] JSON parse failed:", parseError);
            console.error("[fetch] Failed text:", responseText);
            throw new Error("Invalid JSON from API.");
        }

        if (!deviceGrid) {
             console.error("[fetch] Device grid element not found.");
             return;
        }
        deviceGrid.innerHTML = ''; // Clear current grid

        if (apiError) {
            deviceGrid.innerHTML = `<p class="text-red-400 col-span-full">Dog Error: ${apiError}. Check logs.</p>`;
        } else if (devices.length === 0) {
            deviceGrid.innerHTML = '<p class="text-gray-500 col-span-full">Dog running, no devices detected/configured.</p>';
        } else {
            devices.forEach(device => {
                const bubble = document.createElement('div');
                const classes = getStatusClass(device.display_status);
                bubble.className = classes.bubble;
                bubble.innerHTML = `<span class="text-sm font-bold block truncate w-full">${device.miner_id || device.port_path || 'Unknown'}</span> <span class="${classes.pill}">${device.display_status || 'Unknown'}</span>`;
                bubble.onclick = () => openModal(device);
                deviceGrid.appendChild(bubble);
            });
        }
        
        if (liveIndicator) {
             liveIndicator.classList.remove('bg-yellow-500');
             liveIndicator.classList.add('bg-green-500');
        }
    } catch (error) {
        console.error('[fetch] Error:', error);
        if (liveIndicator) {
             liveIndicator.classList.remove('bg-yellow-500', 'bg-green-500');
             liveIndicator.classList.add('bg-red-500');
        }
        if (deviceGrid) {
            deviceGrid.innerHTML = `<p class="text-red-400 col-span-full">Error loading data: ${error.message}. Is Dog running & API ok?</p>`;
        }
    }
}

function getStatusClass(status) {
    const lowerStatus = String(status).toLowerCase();
    const baseClasses = "h-24 p-4 rounded-lg text-white font-semibold shadow-md flex flex-col justify-between items-center text-center cursor-pointer transition-all duration-150 ease-in-out transform hover:scale-105";
    const pillBase = "text-xs font-normal block mt-1 px-2 py-0.5 rounded-full";
    if (lowerStatus === 'online') return { bubble: `${baseClasses} bg-green-700 hover:bg-green-600`, pill: `${pillBase} bg-green-200 text-green-900` };
    if (lowerStatus === 'stale') return { bubble: `${baseClasses} bg-yellow-700 hover:bg-yellow-600`, pill: `${pillBase} bg-yellow-200 text-yellow-900` };
    if (lowerStatus === 'offline') return { bubble: `${baseClasses} bg-red-800 hover:bg-red-700`, pill: `${pillBase} bg-red-200 text-red-900` };
    if (lowerStatus === 'inactive' || lowerStatus === 'synced' || lowerStatus === 'captured' || lowerStatus === 'verified' || lowerStatus === 'onboarded') return { bubble: `${baseClasses} bg-gray-700 hover:bg-gray-600 opacity-60`, pill: `${pillBase} bg-gray-300 text-gray-800` };
    if (lowerStatus === 'unconfigured' || lowerStatus === 'unconfigured (captured)') return { bubble: `${baseClasses} bg-blue-700 hover:bg-blue-600`, pill: `${pillBase} bg-blue-200 text-blue-900` };
    if (lowerStatus.includes('error') || lowerStatus.includes('failed')) return { bubble: `${baseClasses} bg-red-800 hover:bg-red-700`, pill: `${pillBase} bg-red-200 text-red-900` };
    return { bubble: `${baseClasses} bg-purple-700 hover:bg-purple-600`, pill: `${pillBase} bg-purple-200 text-purple-900` }; // Fallback
}

// --- Modal Management ---
function openModal(deviceData) {
    isModalOpen = true;
    currentModalData = deviceData;
    const status = String(deviceData.display_status).toLowerCase();

    if (deviceData.type === 'miner') {
        const isEffectivelyOnline = status === 'online';
        if (isEffectivelyOnline) {
             populateAndShowModal(detailsModal, {
                'details-miner-id': deviceData.miner_id,
                'details-status': deviceData.display_status,
                'details-pool': deviceData.pool_url || 'N/A',
                'details-wallet': deviceData.wallet_address || 'N/A',
                'details-version': deviceData.version || 'N/A',
                'details-dev-path': deviceData.dev_path || 'N/A',
                'details-port-path': deviceData.port_path || 'N/A',
                'details-serial': deviceData.serial_number || 'N/A',
                'details-location': deviceData.location_notes || 'N/A'
             });
        } else {
             populateAndShowModal(actionsModal, {
                 'actions-miner-id': deviceData.miner_id,
                 'actions-status': deviceData.display_status,
                 'actions-state': deviceData.state_msg || 'N/A',
                 'actions-dev-path': deviceData.dev_path || 'N/A',
                 'actions-port-path': deviceData.port_path || 'N/A',
                 'actions-serial': deviceData.serial_number || 'N/A',
                 'actions-location': deviceData.location_notes || 'N/A'
             });
        }
    } else if (deviceData.type === 'stray') {
         populateAndShowModal(configureModal, {
             'config-dev-path': deviceData.dev_path,
             'config-port-path': deviceData.port_path,
             'config-serial': deviceData.serial_number,
             'config-vendor': deviceData.vendor_id,
             'config-product': deviceData.product_id || 'N/A'
         });
         
         // Reset form fields
         document.getElementById('onboard_miner_id').value = '';
         document.getElementById('onboard_location_notes').value = '';
         document.getElementById('onboard_currency').value = 'BTC';

         // Show/Hide captured info and populate hidden form fields
         const capturedInfoDiv = document.getElementById('config-captured-info');
         if (deviceData.pool_url || deviceData.wallet_address || deviceData.version || deviceData.chipset || deviceData.mac_address) {
             document.getElementById('config-captured-chipset').textContent = deviceData.chipset || 'N/A';
             document.getElementById('config-captured-mac').textContent = deviceData.mac_address || 'N/A';
             document.getElementById('config-captured-pool').textContent = deviceData.pool_url || 'N/A';
             document.getElementById('config-captured-wallet').textContent = deviceData.wallet_address || 'N/A';
             document.getElementById('config-captured-version').textContent = deviceData.version || 'N/A';
             capturedInfoDiv.classList.remove('hidden');
             // Populate hidden fields
             document.getElementById('config-form-pool').value = deviceData.pool_url || '';
             document.getElementById('config-form-wallet').value = deviceData.wallet_address || '';
             document.getElementById('config-form-version').value = deviceData.version || '';
             document.getElementById('config-form-chipset').value = deviceData.chipset || '';
             document.getElementById('config-form-mac').value = deviceData.mac_address || '';
         } else {
             capturedInfoDiv.classList.add('hidden');
             // Clear hidden fields
             document.getElementById('config-form-pool').value = '';
             document.getElementById('config-form-wallet').value = '';
             document.getElementById('config-form-version').value = '';
             document.getElementById('config-form-chipset').value = '';
             document.getElementById('config-form-mac').value = '';
         }
         // Populate essential hidden fields regardless
         document.getElementById('config-form-dev-path').value = deviceData.dev_path;
         document.getElementById('config-form-port-path').value = deviceData.port_path;
         document.getElementById('config-form-serial').value = deviceData.serial_number;
         document.getElementById('config-form-vendor').value = deviceData.vendor_id;
         document.getElementById('config-form-product').value = deviceData.product_id || '';
    } else {
        console.error("Unknown device type:", deviceData);
    }
}

function populateAndShowModal(modalElement, dataMap) {
     if (!modalElement) {
         console.error("Modal element not found for population.");
         return;
     }
     for (const id in dataMap) {
         const element = modalElement.querySelector(`#${id}`);
         if (element) {
             element.textContent = dataMap[id];
         } else {
             console.warn(`Element with ID '${id}' not found in modal.`);
         }
     }
     modalElement.classList.remove('hidden');
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('hidden');
    } else {
         console.error(`[closeModal] Modal with ID '${modalId}' not found.`);
    }
    isModalOpen = false;
    currentModalData = null;
    // Fetch data slightly delayed to allow UI to settle
    setTimeout(fetchDeviceData, 50);
}

// --- AJAX Actions ---
async function onboardStray(event) {
    event.preventDefault();
    const form = event.target;
    if (!URLS.onboardStray) {
         showAjaxFlash("Onboard URL not configured.", 'error');
         return;
    }
    const formData = new FormData(form);
    const submitButton = form.querySelector('button[type="submit"]');
    if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = 'Adding...';
    }

    try {
        const response = await fetch(URLS.onboardStray, { method: 'POST', body: formData });
        const result = await response.json();
        if (response.ok && result.success) {
            showAjaxFlash(result.message, 'success');
            closeModal('configure-modal');
        } else {
            showAjaxFlash(result.message || 'Unknown error during onboard.', 'error');
        }
    } catch (error) {
        console.error('Onboard error:', error);
        showAjaxFlash('Network error during onboard.', 'error');
    } finally {
        if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = 'Add to Flock';
        }
    }
}

async function runMinerAction(actionButton) {
    console.log("[runAction] Called.");
    if (!currentModalData) {
        console.log("[runAction] No currentModalData.");
        showAjaxFlash("No device selected for action.", "error");
        return;
    }
    if (!URLS.runMinerAction) {
         showAjaxFlash("Action URL not configured.", 'error');
         return;
    }

    // Determine which modal is active to know the context
    const detailsModalActive = detailsModal && !detailsModal.classList.contains('hidden');
    const actionsModalActive = actionsModal && !actionsModal.classList.contains('hidden');
    const configureModalActive = configureModal && !configureModal.classList.contains('hidden');

    let originalButtonText = actionButton.textContent; // Store original text
    actionButton.disabled = true;
    actionButton.textContent = 'Working...';
    console.log("[runAction] Button disabled.");

    const payload = {
        action: 'reset_capture', // Currently only supports this action
        dev_path: currentModalData.dev_path,
        port_path: currentModalData.port_path,
        serial_number: currentModalData.serial_number,
        miner_db_id: currentModalData.type === 'miner' ? currentModalData.id : null
    };
    console.log("[runAction] Payload:", payload);

    try {
        console.log("[runAction] Fetching:", URLS.runMinerAction);
        const response = await fetch(URLS.runMinerAction, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        console.log("[runAction] Status:", response.status);
        
        const result = await response.json();
        console.log("[runAction] Result:", result);

        if (response.ok && result.success) {
            showAjaxFlash(result.message, 'success');

            let modalToClose = null;
            if (detailsModalActive) modalToClose = 'details-modal';
            else if (actionsModalActive) modalToClose = 'actions-modal';
            else if (configureModalActive) modalToClose = 'configure-modal';

            // Special handling for stray device capture: update data and reopen modal
            if (result.data && modalToClose === 'configure-modal') {
                console.log("[runAction] Success (stray data). Merging & reopening...");
                closeModal(modalToClose); // Close first
                // Merge new data into currentModalData before reopening
                currentModalData = { ...currentModalData, ...result.data };
                // Reopen the modal after a short delay to ensure DOM is updated
                setTimeout(() => openModal(currentModalData), 100); 
            } else {
                 // For miners or if no data returned for stray, just close the modal
                 console.log("[runAction] Success (miner or no data). Closing...");
                 if (modalToClose) closeModal(modalToClose);
            }

        } else {
            console.error("[runAction] Backend action failed:", result.message);
            showAjaxFlash(result.message || 'Action failed on the server.', 'error');
        }
    } catch (error) {
        console.error("[runAction] Network or parse error:", error);
        showAjaxFlash('Network error during action.', 'error');
    } finally {
        // Only re-enable the button if the modal wasn't immediately closed and reopened
        // This prevents re-enabling if the reopen logic is triggered
        if (!(configureModalActive && result && result.data)) {
             if (actionButton) {
                actionButton.disabled = false;
                actionButton.textContent = originalButtonText; // Restore original text
                console.log("[runAction] Finished. Button re-enabled.");
            }
        }
    }
}


// --- Flash Messages ---
function showAjaxFlash(message, category = 'success') {
    if (!ajaxFlashContainer) return;
    const alertDiv = document.createElement('div');
    const bgColor = category === 'error' ? 'bg-red-800' : 'bg-green-800';
    const textColor = category === 'error' ? 'text-red-200' : 'text-green-200';
    alertDiv.className = `flex items-center justify-between p-4 mb-4 text-sm rounded-lg ${bgColor} ${textColor} transition-opacity duration-500`;
    alertDiv.setAttribute('role', 'alert');
    alertDiv.innerHTML = `
        <span>${message}</span>
        <button type="button" onclick="this.parentElement.style.opacity = '0'; setTimeout(() => this.parentElement.remove(), 500);" class="ml-4 -mr-1.5 -my-1.5 bg-transparent rounded-lg p-1.5 inline-flex items-center justify-center text-current hover:bg-white/20">
            <svg class="w-3 h-3" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 14 14"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/></svg>
        </button>
    `;
    ajaxFlashContainer.appendChild(alertDiv);

    // Auto-dismiss after 5 seconds
    setTimeout(() => {
        alertDiv.style.opacity = '0';
        setTimeout(() => alertDiv.remove(), 500); // Remove from DOM after fade out
    }, 5000);
}

// --- Legacy Functions (Pools, Addresses - unchanged logic, now standalone) ---
function openDeleteModal(deleteUrl, itemType) { /* ... Logic unchanged ... */ }
function updateUserTypeVisibility() { /* ... Logic unchanged ... */ }

// --- Page Initializer ---
document.addEventListener('DOMContentLoaded', function() {
    // Set initial pane based on hash or default to 'miners'
    const hash = window.location.hash.substring(1);
    if (hash) {
        showPane(hash);
    } else {
        showPane('miners');
    }

    // Initial setup for legacy pool/address forms (if they exist)
    const dynamicRadio = document.getElementById('user_type_dynamic'); 
    updateUserTypeVisibility(); 
    if(dynamicRadio) {
        dynamicRadio.addEventListener('change', updateUserTypeVisibility);
    }
    // Add event listeners for other form elements if needed...

    // Start fetching live device data
    fetchDeviceData();
    setInterval(fetchDeviceData, 3000); // Refresh every 3 seconds

    // Auto-dismiss initial flash messages from Flask
    const flashMessages = document.querySelectorAll('[id^="flash-message-"]');
    flashMessages.forEach(function(message) {
        setTimeout(function() {
            message.style.opacity = '0';
            setTimeout(function() {
                message.style.display = 'none';
            }, 500); // Wait for fade out
        }, 5000); // Start fade out after 5 seconds
    });
});

// Add event listeners globally if needed, e.g., for modals
// Make sure these functions are defined before being assigned if needed outside initializer
// Example for closing modals by clicking outside (optional)
// [detailsModal, actionsModal, deleteModal, editModal, configureModal].forEach(modal => {
//     if (modal) {
//         modal.addEventListener('click', (event) => {
//             if (event.target === modal) { // Clicked on the background overlay
//                 closeModal(modal.id);
//             }
//         });
//     }
// });
