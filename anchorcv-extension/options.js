// ============================================================================
// Options Page Script for AnchorCV Extension
// ============================================================================

const API_BASE = 'https://app.anchorcv.com';

// Load settings when page loads
document.addEventListener('DOMContentLoaded', loadSettings);

// ============================================================================
// Load and Display Settings
// ============================================================================

async function loadSettings() {
  const data = await chrome.storage.local.get([
    'isLoggedIn',
    'userEmail',
    'cvStored',
    'cvFilename',
    'usageCount'
  ]);

  const isLoggedIn = data.isLoggedIn || false;
  const userEmail = data.userEmail || null;
  const cvStored = data.cvStored || false;
  const cvFilename = data.cvFilename || null;
  const usageCount = data.usageCount || 0;

  // Update UI
  updateUserInfo(userEmail, isLoggedIn);
  updateCVStatus(cvStored, cvFilename);
  updateUsageStats(usageCount);
  setupEventListeners();
}

// Update user email display
function updateUserInfo(email, isLoggedIn) {
  const emailEl = document.getElementById('user-email');
  const logoutBtn = document.getElementById('logout-button');

  if (isLoggedIn && email) {
    emailEl.textContent = email;
  } else {
    emailEl.textContent = 'Not logged in';
    logoutBtn.textContent = 'Go to Login';
  }
}

// Update CV status display
function updateCVStatus(cvStored, cvFilename) {
  const statusDesc = document.getElementById('cv-status-desc');
  const statusBadge = document.getElementById('cv-status-badge');
  const fileDisplay = document.getElementById('cv-filename-display');
  const filenameEl = document.getElementById('cv-filename');
  const uploadBtn = document.getElementById('upload-cv-button');
  const replaceBtn = document.getElementById('replace-cv-button');

  if (cvStored) {
    statusDesc.textContent = 'CV uploaded and ready to use';
    statusBadge.textContent = 'Uploaded';
    statusBadge.classList.remove('inactive');
    statusBadge.classList.add('active');
    fileDisplay.style.display = 'block';
    filenameEl.textContent = cvFilename || 'CV';
    uploadBtn.textContent = 'Upload Another CV';
    replaceBtn.style.display = 'block';
  } else {
    statusDesc.textContent = 'No CV uploaded yet';
    statusBadge.textContent = 'Not Uploaded';
    statusBadge.classList.remove('active');
    statusBadge.classList.add('inactive');
    fileDisplay.style.display = 'none';
    uploadBtn.textContent = 'Upload Your CV';
    replaceBtn.style.display = 'none';
  }
}

// Update usage stats display
function updateUsageStats(count) {
  const remaining = Math.max(0, 3 - count);

  document.getElementById('usage-count').textContent = count;
  document.getElementById('usage-remaining').textContent = remaining;
  document.getElementById('usage-remaining-text').textContent = remaining;
}

// ============================================================================
// Event Listeners
// ============================================================================

function setupEventListeners() {
  const logoutBtn = document.getElementById('logout-button');
  const uploadBtn = document.getElementById('upload-cv-button');
  const replaceBtn = document.getElementById('replace-cv-button');
  const fileInput = document.getElementById('cv-file-input');

  logoutBtn.addEventListener('click', handleLogout);
  uploadBtn.addEventListener('click', () => fileInput.click());
  replaceBtn.addEventListener('click', handleReplaceCVClick);
  fileInput.addEventListener('change', handleFileSelect);
}

// Handle logout
async function handleLogout() {
  const data = await chrome.storage.local.get('isLoggedIn');

  if (!data.isLoggedIn) {
    // Not logged in, redirect to login
    chrome.tabs.create({ url: 'https://app.anchorcv.com/login' });
    return;
  }

  // Clear all storage
  await chrome.storage.local.clear();

  // Show success message
  showSuccessMessage('Logged out successfully');

  // Reload settings
  setTimeout(() => {
    location.reload();
  }, 1000);
}

// Handle CV file selection
async function handleFileSelect(e) {
  const file = e.target.files[0];
  if (!file) return;

  const uploadBtn = document.getElementById('upload-cv-button');
  uploadBtn.disabled = true;
  uploadBtn.textContent = 'Uploading...';

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
        // Not authenticated
        await chrome.storage.local.clear();
        showErrorMessage('Session expired. Please login again.');
        setTimeout(() => {
          chrome.tabs.create({ url: 'https://app.anchorcv.com/login' });
        }, 1000);
        return;
      }
      throw new Error('Failed to upload CV');
    }

    // Update storage
    await chrome.storage.local.set({
      cvStored: true,
      cvFilename: file.name
    });

    showSuccessMessage('CV uploaded successfully!');

    // Reload settings
    setTimeout(() => {
      location.reload();
    }, 1000);
  } catch (error) {
    showErrorMessage('Error: ' + error.message);
    uploadBtn.disabled = false;
    uploadBtn.textContent = 'Upload Your CV';
  }
}

// Handle replace CV click
function handleReplaceCVClick() {
  document.getElementById('cv-file-input').click();
}

// Show success message
function showSuccessMessage(msg) {
  const msgEl = document.getElementById('success-message');
  msgEl.textContent = msg;
  msgEl.style.display = 'block';

  setTimeout(() => {
    msgEl.style.display = 'none';
  }, 4000);
}

// Show error message (using success element styled for errors)
function showErrorMessage(msg) {
  const msgEl = document.getElementById('success-message');
  msgEl.textContent = msg;
  msgEl.style.display = 'block';
  msgEl.style.background = '#7f1d1d';
  msgEl.style.color = '#fca5a5';
  msgEl.style.borderColor = '#991b1b';

  setTimeout(() => {
    msgEl.style.display = 'none';
    msgEl.style.background = '#14532d';
    msgEl.style.color = '#86efac';
    msgEl.style.borderColor = '#15803d';
  }, 4000);
}
