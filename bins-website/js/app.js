/**
 * UK Bin Collection Lookup - Main Application
 *
 * Client-side JavaScript for looking up bin collection schedules.
 * No framework dependencies - vanilla JavaScript only.
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

// IMPORTANT: Update this URL after deploying your Cloudflare Worker
const CORS_PROXY_URL = 'https://your-worker.your-subdomain.workers.dev';

// ============================================================================
// STATE
// ============================================================================

let councilsData = null; // All council configurations
let addressesData = []; // Addresses from postcode lookup
let selectedAddress = null;
let selectedUPRN = null;
let selectedCouncil = null;

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/**
 * Validate UK postcode format
 */
function validatePostcode(postcode) {
  const regex = /^[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}$/i;
  return regex.test(postcode.trim());
}

/**
 * Normalize postcode format (uppercase, with space)
 */
function normalizePostcode(postcode) {
  const clean = postcode.toUpperCase().replace(/\s/g, '');
  // Insert space before last 3 characters
  return `${clean.slice(0, -3)} ${clean.slice(-3)}`;
}

/**
 * Normalize address for comparison
 */
function normalizeAddress(address) {
  return address.replace(/[^a-z0-9]/gi, '').toLowerCase();
}

/**
 * Normalize council name (convert display name to config key)
 */
function normalizeCouncilName(councilDisplayName) {
  // Remove common suffixes and join words
  return councilDisplayName
    .replace(/\s+(City|Borough|District|County|Metropolitan|Unitary)\s+Council$/i, 'Council')
    .replace(/\s+Council$/i, 'Council')
    .replace(/\s+/g, '')
    .replace(/['-]/g, '');
}

/**
 * Show loading indicator
 */
function showLoading() {
  document.getElementById('loading').style.display = 'block';
}

/**
 * Hide loading indicator
 */
function hideLoading() {
  document.getElementById('loading').style.display = 'none';
}

/**
 * Display error message
 */
function showError(elementId, message) {
  const errorDiv = document.getElementById(elementId);
  errorDiv.textContent = message;
  errorDiv.style.display = 'block';
}

/**
 * Hide error message
 */
function hideError(elementId) {
  const errorDiv = document.getElementById(elementId);
  errorDiv.textContent = '';
  errorDiv.style.display = 'none';
}

// ============================================================================
// API CALLS
// ============================================================================

/**
 * Load council configurations from JSON file
 */
async function loadCouncilsData() {
  if (councilsData) return councilsData;

  try {
    const response = await fetch('data/councils-data.json');
    if (!response.ok) {
      throw new Error('Failed to load council configurations');
    }
    councilsData = await response.json();
    console.log(`Loaded ${Object.keys(councilsData).length} council configurations`);
    return councilsData;
  } catch (error) {
    console.error('Error loading councils data:', error);
    throw new Error('Failed to load council data. Please refresh the page.');
  }
}

/**
 * Look up addresses for a postcode
 */
async function lookupUPRN(postcode) {
  const url = `https://forms.north-norfolk.gov.uk/xforms/AddressSearch/GetAddressList?postcode=${encodeURIComponent(postcode)}`;

  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const items = await response.json();

    // Filter out invalid entries
    return items
      .filter((item) => item.value && item.value !== '0')
      .map((item) => ({
        address: item.text,
        uprn: item.value,
      }));
  } catch (error) {
    console.error('UPRN lookup error:', error);
    throw new Error(
      'Failed to find addresses for this postcode. Please check the postcode and try again.',
    );
  }
}

/**
 * Look up local authority for a postcode and address
 */
async function lookupCouncil(postcode, userAddress) {
  const url = `https://www.gov.uk/api/local-authority?postcode=${encodeURIComponent(postcode)}`;

  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();

    // Case 1: Single authority
    if (data.local_authority) {
      return {
        name: data.local_authority.name,
        url: data.local_authority.homepage_url,
        tier: data.local_authority.tier,
      };
    }

    // Case 2: Multiple authorities (need to match address)
    if (data.addresses) {
      if (!userAddress) {
        throw new Error('Multiple councils found - address required');
      }

      const normalizedTarget = normalizeAddress(userAddress);
      const match = data.addresses.find(
        (addr) => normalizeAddress(addr.address) === normalizedTarget,
      );

      if (match) {
        // Fetch specific authority by slug
        const slugUrl = `https://www.gov.uk/api/local-authority/${match.slug}`;
        const slugResponse = await fetch(slugUrl);
        if (!slugResponse.ok) {
          throw new Error(`HTTP ${slugResponse.status}`);
        }
        const slugData = await slugResponse.json();
        return {
          name: slugData.local_authority.name,
          url: slugData.local_authority.homepage_url,
          tier: slugData.local_authority.tier,
        };
      }

      throw new Error('Could not match address to council');
    }

    throw new Error('No council data returned');
  } catch (error) {
    console.error('Council lookup error:', error);
    throw new Error('Failed to identify your local council. Please try again.');
  }
}

/**
 * Build request configuration from council YAML config
 */
function buildCouncilRequest(councilConfig, inputs) {
  // Fill URL template
  let url = councilConfig.api_urls[0];
  for (const [key, value] of Object.entries(inputs)) {
    url = url.replace(`{${key}}`, encodeURIComponent(value));
  }

  // Prepare headers
  const headers = { ...councilConfig.api_headers };

  // Extract headers from description if present
  if (councilConfig.api_description) {
    const ocpMatch = councilConfig.api_description.match(
      /Ocp-Apim-Subscription-Key.*?['"]([a-f0-9]+)['"]/i,
    );
    if (ocpMatch) {
      headers['Ocp-Apim-Subscription-Key'] = ocpMatch[1];
    }
  }

  // Add default User-Agent if not present
  if (!headers['User-Agent']) {
    headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36';
  }

  const method = councilConfig.api_methods[0];

  // Prepare body for POST requests
  let body = null;
  if (method === 'POST') {
    const responseFormat = councilConfig.response_format;
    if (
      responseFormat === 'json' ||
      councilConfig.api_description?.toLowerCase().includes('json')
    ) {
      body = inputs;
      headers['Content-Type'] = 'application/json';
    } else {
      // Form data
      body = inputs;
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
    }
  }

  return { url, method, headers, body };
}

/**
 * Fetch bin collection data via CORS proxy
 */
async function fetchBinData(councilConfig, inputs) {
  const request = buildCouncilRequest(councilConfig, inputs);

  try {
    const response = await fetch(CORS_PROXY_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      throw new Error(`CORS proxy returned HTTP ${response.status}`);
    }

    const contentType = response.headers.get('Content-Type');
    if (contentType?.includes('application/json')) {
      return await response.json();
    }
    return await response.text();
  } catch (error) {
    console.error('Bin data fetch error:', error);
    throw new Error('Failed to fetch bin collection data from council. Please try again.');
  }
}

// ============================================================================
// UI EVENT HANDLERS
// ============================================================================

/**
 * Handle: Find Addresses button
 */
async function handleFindAddresses() {
  hideError('postcode-error');

  const postcodeInput = document.getElementById('postcode');
  const postcode = postcodeInput.value.trim();

  // Validate postcode
  if (!postcode) {
    showError('postcode-error', 'Please enter a postcode');
    return;
  }

  if (!validatePostcode(postcode)) {
    showError('postcode-error', 'Please enter a valid UK postcode (e.g., SW1A 1AA)');
    return;
  }

  showLoading();

  try {
    // Normalize postcode
    const normalizedPostcode = normalizePostcode(postcode);

    // Fetch addresses
    addressesData = await lookupUPRN(normalizedPostcode);

    if (addressesData.length === 0) {
      hideLoading();
      showError(
        'postcode-error',
        'No addresses found for this postcode. Please check and try again.',
      );
      return;
    }

    // Populate address datalist
    const datalist = document.getElementById('addresses');
    datalist.innerHTML = '';
    for (const addr of addressesData) {
      const option = document.createElement('option');
      option.value = addr.address;
      datalist.appendChild(option);
    }

    // Update UI
    document.getElementById('address-count').textContent =
      `${addressesData.length} address${addressesData.length === 1 ? '' : 'es'} found`;
    document.getElementById('address-section').style.display = 'block';
    document.getElementById('address-input').focus();

    hideLoading();
  } catch (error) {
    hideLoading();
    showError('postcode-error', error.message);
  }
}

/**
 * Handle: Find Bin Collections button
 */
async function handleFindBins() {
  hideError('address-error');

  const addressInput = document.getElementById('address-input');
  const address = addressInput.value.trim();

  if (!address) {
    showError('address-error', 'Please select an address from the list');
    return;
  }

  // Find matching address
  const match = addressesData.find((addr) => addr.address === address);
  if (!match) {
    showError('address-error', 'Please select a valid address from the dropdown list');
    return;
  }

  selectedAddress = match.address;
  selectedUPRN = match.uprn;

  showLoading();

  try {
    // Load council data if not already loaded
    await loadCouncilsData();

    // Get postcode
    const postcode = normalizePostcode(document.getElementById('postcode').value);

    // Lookup council
    const councilInfo = await lookupCouncil(postcode, selectedAddress);
    console.log('Council info:', councilInfo);

    // Find matching council config
    const normalizedName = normalizeCouncilName(councilInfo.name);
    console.log('Looking for council config:', normalizedName);

    // Try to find council in our data
    let councilConfig = councilsData[normalizedName];

    // Try alternative matching
    if (!councilConfig) {
      const keys = Object.keys(councilsData);
      const fuzzyMatch = keys.find(
        (key) =>
          key.toLowerCase().includes(normalizedName.toLowerCase()) ||
          normalizedName.toLowerCase().includes(key.toLowerCase()),
      );
      if (fuzzyMatch) {
        councilConfig = councilsData[fuzzyMatch];
        console.log('Fuzzy matched to:', fuzzyMatch);
      }
    }

    if (!councilConfig) {
      hideLoading();
      showError(
        'address-error',
        `Sorry, ${councilInfo.name} is not yet supported. We support 306 councils with API-based lookups.`,
      );
      return;
    }

    selectedCouncil = councilInfo;

    // Prepare inputs for the council API
    const inputs = { uprn: selectedUPRN };
    // Add any other required inputs from config
    if (councilConfig.required_user_input) {
      for (const input of councilConfig.required_user_input) {
        if (input === 'postcode' && !inputs.postcode) {
          inputs.postcode = postcode.replace(/\s/g, '');
        }
      }
    }

    // Fetch bin data
    const binData = await fetchBinData(councilConfig, inputs);

    // Display results
    displayResults(councilInfo, binData);

    hideLoading();
  } catch (error) {
    hideLoading();
    showError('address-error', error.message);
  }
}

/**
 * Display bin collection results
 */
function displayResults(councilInfo, binData) {
  // Hide previous sections
  document.getElementById('postcode-section').style.display = 'none';
  document.getElementById('address-section').style.display = 'none';

  // Show results section
  const resultsSection = document.getElementById('results');
  resultsSection.style.display = 'block';

  // Display council info
  const councilInfoDiv = document.getElementById('council-info');
  councilInfoDiv.innerHTML = `
    <p>
      <strong>Council:</strong> ${councilInfo.name}<br>
      <strong>Address:</strong> ${selectedAddress}<br>
      <strong>UPRN:</strong> ${selectedUPRN}
    </p>
  `;

  // Display bin data
  const binDataDiv = document.getElementById('bin-data');

  if (typeof binData === 'string') {
    // HTML response
    binDataDiv.innerHTML = `<div style="overflow-x: auto;">${binData}</div>`;
  } else if (typeof binData === 'object') {
    // JSON response - format nicely
    binDataDiv.innerHTML = `<pre style="white-space: pre-wrap; word-wrap: break-word;">${JSON.stringify(binData, null, 2)}</pre>`;
  } else {
    binDataDiv.textContent = binData;
  }
}

/**
 * Handle: Start Over button
 */
function handleStartOver() {
  // Reset state
  addressesData = [];
  selectedAddress = null;
  selectedUPRN = null;
  selectedCouncil = null;

  // Reset form
  document.getElementById('postcode').value = '';
  document.getElementById('address-input').value = '';
  document.getElementById('addresses').innerHTML = '';

  // Hide all sections except postcode
  document.getElementById('address-section').style.display = 'none';
  document.getElementById('results').style.display = 'none';
  document.getElementById('postcode-section').style.display = 'block';

  // Hide errors
  hideError('postcode-error');
  hideError('address-error');

  // Focus postcode input
  document.getElementById('postcode').focus();
}

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize the application
 */
function init() {
  console.log('UK Bin Lookup initialized');

  // Pre-load council data
  loadCouncilsData().catch((error) => {
    console.error('Failed to pre-load council data:', error);
  });

  // Attach event listeners
  document.getElementById('find-addresses').addEventListener('click', handleFindAddresses);
  document.getElementById('find-bins').addEventListener('click', handleFindBins);
  document.getElementById('start-over').addEventListener('click', handleStartOver);

  // Allow Enter key to submit
  document.getElementById('postcode').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      handleFindAddresses();
    }
  });

  document.getElementById('address-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      handleFindBins();
    }
  });

  // Focus postcode input
  document.getElementById('postcode').focus();
}

// Run init when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
