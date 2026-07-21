// ============================================================================
// Background Service Worker for AnchorCV Extension
// ============================================================================

// Create context menu on extension install/update
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'sendToAnchorCV',
    title: 'Use as Job Description in AnchorCV',
    contexts: ['selection']
  });
});

// Handle context menu clicks
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'sendToAnchorCV') {
    handleContextMenuClick(info.selectionText, tab);
  }
});

// Store selected text and open popup
async function handleContextMenuClick(selectedText, tab) {
  // Store the selected job description text
  await chrome.storage.local.set({
    selectedJD: selectedText
  });

  // Open the popup
  // Note: The popup will open when the user clicks the extension icon
  // We can't directly open it, but the text will be ready when they do
}

// Listen for messages from popup or content scripts
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'getSelectedJD') {
    chrome.storage.local.get('selectedJD', (data) => {
      sendResponse({ jd: data.selectedJD || null });
    });
    return true; // Keep channel open for async response
  }
});
