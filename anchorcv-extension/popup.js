// ============================================================================
// State Management
// ============================================================================

const API_BASE = 'https://app.anchorcv.com';

// Guard — prevents duplicate event listeners when loadMainScreen() is called multiple times
let mainListenersAttached = false;

// Get current state from storage
async function getState() {
  const data = await chrome.storage.local.get([
    'isLoggedIn',
    'userEmail',
    'cvStored',
    'cvFilename',
    'usageCount'
  ]);
  return {
    isLoggedIn: data.isLoggedIn || false,
    userEmail: data.userEmail || null,
    cvStored: data.cvStored || false,
    cvFilename: data.cvFilename || null,
    usageCount: data.usageCount || 0
  };
}

// Update state in storage
async function setState(updates) {
  await chrome.storage.local.set(updates);
}

// ============================================================================
// Helper Functions
// ============================================================================

// Show a specific screen and hide others
function showScreen(screenId) {
  document.querySelectorAll('.screen').forEach(el => {
    el.classList.remove('active');
  });
  const screen = document.getElementById(screenId);
  if (screen) {
    screen.classList.add('active');
  }
}

// Show error message in the appropriate container
function showError(msg, screenId = 'main') {
  const errorId = `${screenId}-error`;
  const errorEl = document.getElementById(errorId);
  if (errorEl) {
    errorEl.innerHTML = `<div class="error">${escapeHtml(msg)}</div>`;
    // Auto-hide after 5 seconds
    setTimeout(() => {
      errorEl.innerHTML = '';
    }, 5000);
  }
}

// Show success message
function showSuccess(msg, screenId = 'main') {
  const successId = `${screenId}-success`;
  const successEl = document.getElementById(successId);
  if (successEl) {
    successEl.innerHTML = `<div class="success">${escapeHtml(msg)}</div>`;
    setTimeout(() => {
      successEl.innerHTML = '';
    }, 5000);
  }
}

// Show feedback message on result screen
function showFeedback(msg, isError = false) {
  const feedbackEl = document.getElementById('result-feedback');
  if (feedbackEl) {
    const className = isError ? 'error' : 'success';
    feedbackEl.innerHTML = `<div class="${className}">${escapeHtml(msg)}</div>`;
  }
}

// Toggle button loading state
function showLoading(buttonId, isLoading) {
  const button = document.getElementById(buttonId);
  if (!button) return;

  if (isLoading) {
    button.disabled = true;
    button.dataset.originalText = button.textContent;
    button.innerHTML = '<span class="spinner"></span>Loading...';
  } else {
    button.disabled = false;
    button.textContent = button.dataset.originalText || 'Generate';
  }
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// API wrapper with error handling and credentials
async function apiFetch(url, options = {}) {
  const defaultOptions = {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  };

  const finalOptions = { ...defaultOptions, ...options };
  if (options.headers) {
    finalOptions.headers = { ...defaultOptions.headers, ...options.headers };
  }

  try {
    const response = await fetch(API_BASE + url, finalOptions);

    if (!response.ok) {
      // Handle specific error codes
      if (response.status === 401) {
        // Unauthorized - need to login again
        await setState({ isLoggedIn: false, userEmail: null });
        showScreen('screen-login');
        throw new Error('Session expired. Please login again.');
      }
      if (response.status === 429) {
        throw new Error('Daily limit reached. Please try again tomorrow.');
      }
      if (response.status === 402) {
        throw new Error('This feature requires a Premium subscription. Visit anchorcv.com to upgrade.');
      }
      if (response.status === 400) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || 'Invalid request. Please check your inputs.');
      }

      throw new Error(`API error: ${response.status} ${response.statusText}`);
    }

    return await response.json();
  } catch (error) {
    throw error;
  }
}

// ============================================================================
// Screen Navigation & Initialization
// ============================================================================

async function initializePopup() {
  const state = await getState();

  if (state.isLoggedIn) {
    await loadMainScreen(state);

    // If there's a saved result, go straight to result screen
    const saved = await chrome.storage.local.get('savedResult');
    if (saved.savedResult) {
      displayResult(saved.savedResult);
      showScreen('screen-result');
    } else {
      showScreen('screen-main');
    }
  } else {
    showScreen('screen-login');
    setupLoginListeners();
  }
}

async function loadMainScreen(state) {
  // Set user email
  document.getElementById('main-user-email').textContent = state.userEmail || '';

  // Set CV status
  const cvUploadArea = document.getElementById('cv-upload-area');
  const cvReadyArea = document.getElementById('cv-ready-area');

  if (state.cvStored) {
    cvUploadArea.style.display = 'none';
    cvReadyArea.style.display = 'block';
    document.getElementById('cv-filename').textContent = state.cvFilename || 'CV';
  } else {
    cvUploadArea.style.display = 'block';
    cvReadyArea.style.display = 'none';
  }

  // Set usage counter
  updateUsageCounter(state.usageCount);

  // Restore persisted JD (survives tab switches)
  const persisted = await chrome.storage.local.get(['selectedJD', 'savedJD']);
  const jdToRestore = persisted.selectedJD || persisted.savedJD || '';
  if (jdToRestore) {
    document.getElementById('jd-textarea').value = jdToRestore;
    if (persisted.selectedJD) chrome.storage.local.remove('selectedJD');
  }

  // Only attach listeners once — prevents duplicate handler bug
  if (!mainListenersAttached) {
    setupMainListeners();
    mainListenersAttached = true;
  }
}

// Update usage counter display
function updateUsageCounter(count) {
  const counterEl = document.getElementById('usage-counter');
  if (counterEl) counterEl.style.display = 'none';
}

// ============================================================================
// Login Screen Listeners
// ============================================================================

function setupLoginListeners() {
  const emailInput = document.getElementById('login-email');
  const passwordInput = document.getElementById('login-password');
  const loginButton = document.getElementById('login-button');

  loginButton.addEventListener('click', handleLogin);

  // Allow Enter key to submit
  emailInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleLogin();
  });
  passwordInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') handleLogin();
  });
}

async function handleLogin() {
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  const loginButton = document.getElementById('login-button');

  if (!email || !password) {
    showError('Please enter email and password', 'login');
    return;
  }

  showLoading('login-button', true);

  try {
    const response = await apiFetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password })
    });

    if (response.error) {
      showError(response.error, 'login');
      showLoading('login-button', false);
      return;
    }

    // Save login state
    await setState({
      isLoggedIn: true,
      userEmail: email,
      cvStored: false,
      cvFilename: null,
      usageCount: 0
    });

    // Check if CV already exists
    try {
      const cvStatus = await apiFetch('/api/extension/cv');
      if (cvStatus.filename) {
        await setState({
          cvStored: true,
          cvFilename: cvStatus.filename
        });
      }
    } catch (e) {
      // CV doesn't exist yet, that's fine
    }

    const state = await getState();
    await loadMainScreen(state);
    showScreen('screen-main');
    showLoading('login-button', false);
  } catch (error) {
    showError(error.message, 'login');
    showLoading('login-button', false);
  }
}

// ============================================================================
// Main Screen Listeners
// ============================================================================

function setupMainListeners() {
  // Logout button
  document.getElementById('logout-button').addEventListener('click', handleLogout);

  // CV Upload
  document.getElementById('cv-upload-button').addEventListener('click', handleCVUpload);
  document.getElementById('replace-cv-link').addEventListener('click', handleReplaceCVClick);
  document.getElementById('cv-file-input').addEventListener('change', handleCVFileSelect);

  // Generate buttons
  document.getElementById('generate-cover-letter-button').addEventListener('click', () => {
    handleGenerate('Cover Letter');
  });
  document.getElementById('generate-email-button').addEventListener('click', () => {
    handleGenerate('Email to Professor');
  });

  // Extract JD from page
  document.getElementById('extract-jd-button').addEventListener('click', handleExtractJD);

  // Clear all
  document.getElementById('clear-button').addEventListener('click', handleClearAll);

  // Persist JD as user types
  document.getElementById('jd-textarea').addEventListener('input', () => {
    const val = document.getElementById('jd-textarea').value;
    chrome.storage.local.set({ savedJD: val });
  });

  // Result screen buttons
  document.getElementById('back-button').addEventListener('click', handleBackButton);
  document.getElementById('copy-button').addEventListener('click', handleCopyToClipboard);
  document.getElementById('insert-button').addEventListener('click', handleInsertIntoPage);
}

async function handleLogout() {
  await setState({
    isLoggedIn: false,
    userEmail: null,
    cvStored: false,
    cvFilename: null,
    usageCount: 0
  });

  // Clear form fields
  document.getElementById('login-email').value = '';
  document.getElementById('login-password').value = '';
  document.getElementById('jd-textarea').value = '';
  document.getElementById('login-error').innerHTML = '';

  showScreen('screen-login');
  setupLoginListeners();
}

async function handleCVUpload() {
  const fileInput = document.getElementById('cv-file-input');
  const file = fileInput.files[0];

  if (!file) {
    showError('Please select a file', 'main');
    return;
  }

  showLoading('cv-upload-button', true);

  try {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(API_BASE + '/api/extension/cv', {
      method: 'POST',
      credentials: 'include',
      body: formData
    });

    if (!response.ok) {
      if (response.status === 401) {
        await setState({ isLoggedIn: false, userEmail: null });
        showScreen('screen-login');
        throw new Error('Session expired. Please login again.');
      }
      throw new Error('Failed to upload CV');
    }

    const data = await response.json();

    await setState({
      cvStored: true,
      cvFilename: file.name
    });

    showSuccess('CV uploaded successfully!', 'main');
    fileInput.value = '';

    const state = await getState();
    await loadMainScreen(state);
    showLoading('cv-upload-button', false);
  } catch (error) {
    showError(error.message, 'main');
    showLoading('cv-upload-button', false);
  }
}

function handleReplaceCVClick() {
  document.getElementById('cv-file-input').value = '';
  document.getElementById('cv-upload-area').style.display = 'block';
  document.getElementById('cv-ready-area').style.display = 'none';
}

function handleCVFileSelect() {
  const fileInput = document.getElementById('cv-file-input');
  if (fileInput.files.length > 0) {
    handleCVUpload();
  }
}

async function handleGenerate(outputType) {
  const state = await getState();

  // Check if CV is stored
  if (!state.cvStored) {
    showError('Please upload your CV first', 'main');
    return;
  }

  const jdText = document.getElementById('jd-textarea').value.trim();
  if (!jdText) {
    showError('Please paste a job description or requirements', 'main');
    return;
  }

  const buttonId = outputType === 'Cover Letter'
    ? 'generate-cover-letter-button'
    : 'generate-email-button';

  showLoading(buttonId, true);

  try {
    const response = await apiFetch('/api/extension/analyse', {
      method: 'POST',
      body: JSON.stringify({
        requirement_text: jdText,
        output_type: outputType
      })
    });

    if (!response.text) {
      throw new Error('No result returned from server');
    }

    // Track usage count from server response
    const newCount = response.usage_count || 0;
    await setState({ usageCount: newCount });

    // Persist and display result
    await chrome.storage.local.set({ savedResult: response.text });
    displayResult(response.text);
    showScreen('screen-result');
    showLoading(buttonId, false);
  } catch (error) {
    showError(error.message, 'main');
    showLoading(buttonId, false);
  }
}

// ============================================================================
// Result Screen Functions
// ============================================================================

function displayResult(text) {
  document.getElementById('result-text').textContent = text;
  document.getElementById('result-error').innerHTML = '';
  document.getElementById('result-feedback').innerHTML = '';
}

function handleBackButton() {
  showScreen('screen-main');
  const state = getState();
  state.then(s => updateUsageCounter(s.usageCount));
}

async function handleCopyToClipboard() {
  const text = document.getElementById('result-text').textContent;

  try {
    await navigator.clipboard.writeText(text);
    showFeedback('Copied to clipboard!', false);
  } catch (error) {
    showFeedback('Failed to copy to clipboard', true);
  }
}

async function handleInsertIntoPage() {
  const text = document.getElementById('result-text').textContent;

  try {
    // Get the active tab
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tabs[0]) {
      showFeedback('Could not identify active tab', true);
      return;
    }

    // Send message to content script
    chrome.tabs.sendMessage(tabs[0].id, {
      action: 'fill',
      text: text
    }, (response) => {
      if (chrome.runtime.lastError) {
        showFeedback('Could not inject into this page. Copy manually instead.', true);
        return;
      }

      if (response && response.success) {
        showFeedback(response.message, false);
      } else {
        showFeedback(response?.message || 'Could not find input field on page', true);
      }
    });
  } catch (error) {
    showFeedback(error.message, true);
  }
}

// ============================================================================
// Extract JD from page
// ============================================================================

async function handleExtractJD() {
  const btn = document.getElementById('extract-jd-button');
  btn.textContent = 'Extracting...';
  btn.disabled = true;

  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tabs[0]) throw new Error('No active tab');

    chrome.tabs.sendMessage(tabs[0].id, { action: 'extractJD' }, (response) => {
      btn.textContent = '⚡ Extract from Page';
      btn.disabled = false;

      if (chrome.runtime.lastError || !response) {
        showError('Could not extract from this page. Paste manually.', 'main');
        return;
      }
      if (response.success && response.text) {
        document.getElementById('jd-textarea').value = response.text;
        chrome.storage.local.set({ savedJD: response.text });
        showSuccess('Job description extracted!', 'main');
      } else {
        showError(response.message || 'Could not find job description on this page.', 'main');
      }
    });
  } catch (e) {
    btn.textContent = '⚡ Extract from Page';
    btn.disabled = false;
    showError(e.message, 'main');
  }
}

// ============================================================================
// Clear All
// ============================================================================

async function handleClearAll() {
  document.getElementById('jd-textarea').value = '';
  document.getElementById('result-text').textContent = '';
  await chrome.storage.local.remove(['savedJD', 'savedResult']);
  showSuccess('Cleared!', 'main');
}

// ============================================================================
// Initialize on popup load
// ============================================================================

document.addEventListener('DOMContentLoaded', initializePopup);
