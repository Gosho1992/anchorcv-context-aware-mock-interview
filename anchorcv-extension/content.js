// ============================================================================
// Content Script for AnchorCV Extension
// Injected into all pages to auto-fill content
// ============================================================================

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'fill') {
    handleFillRequest(request.text, sendResponse);
    return true;
  }
  if (request.action === 'extractJD') {
    handleExtractJD(sendResponse);
    return true;
  }
});

function handleExtractJD(sendResponse) {
  // Site-specific selectors (most reliable first)
  const siteSelectors = [
    // LinkedIn
    '.jobs-description__content',
    '.jobs-box__html-content',
    '.job-view-layout .jobs-description',
    // Indeed
    '#jobDescriptionText',
    '.jobsearch-jobDescriptionText',
    // JobsDB / JobStreet
    '.job-description-container',
    '[data-automation="jobAdDetails"]',
    '.sx2jih0',
    // Glassdoor
    '.jobDescriptionContent',
    '[class*="JobDetails_jobDescription"]',
    // Greenhouse
    '#content .job-post',
    // Lever
    '.section-wrapper .content',
    // Workday
    '[data-automation-id="jobPostingDescription"]',
    // Generic fallbacks
    '[class*="job-description"]',
    '[class*="jobDescription"]',
    '[id*="job-description"]',
    '[id*="jobDescription"]',
    'article',
  ];

  for (const selector of siteSelectors) {
    const el = document.querySelector(selector);
    if (el) {
      const text = el.innerText.trim();
      if (text.length > 100) {
        sendResponse({ success: true, text: text.slice(0, 4000) });
        return;
      }
    }
  }

  sendResponse({ success: false, message: 'No job description found. Try selecting the text and using right-click → Use as Job Description.' });
}

// Attempt to fill the provided text into a textarea/contenteditable field
function handleFillRequest(text, sendResponse) {
  // List of selectors to try, in order of specificity
  const selectors = [
    'textarea[name*="cover"]',
    'textarea[id*="cover"]',
    'textarea[name*="letter"]',
    'textarea[id*="letter"]',
    'textarea[name*="essay"]',
    'textarea[id*="essay"]',
    'textarea[name*="message"]',
    'textarea[id*="message"]',
    'div[contenteditable="true"][aria-label*="cover"]',
    'div[contenteditable="true"][aria-label*="letter"]',
    '.cover-letter-input textarea',
    'textarea.application-answer',
    'textarea' // Last resort: first textarea on page
  ];

  let targetElement = null;

  // Try each selector in order
  for (const selector of selectors) {
    const element = document.querySelector(selector);
    if (element && isVisible(element)) {
      targetElement = element;
      break;
    }
  }

  // If no element found, respond with failure
  if (!targetElement) {
    sendResponse({
      success: false,
      message: 'Could not find input field on this page. Please paste manually.'
    });
    return;
  }

  // Attempt to fill the element
  try {
    if (targetElement.tagName === 'TEXTAREA') {
      // For textarea elements
      targetElement.value = text;

      // Trigger input and change events to notify any listeners
      targetElement.dispatchEvent(new Event('input', { bubbles: true }));
      targetElement.dispatchEvent(new Event('change', { bubbles: true }));

      // For React/Vue/Angular apps, also try to update via property
      triggerReactChange(targetElement, text);

      sendResponse({
        success: true,
        message: 'Content inserted successfully!'
      });
    } else if (targetElement.contentEditable === 'true') {
      // For contenteditable divs
      targetElement.textContent = text;

      // Trigger input event
      targetElement.dispatchEvent(new Event('input', { bubbles: true }));
      targetElement.dispatchEvent(new Event('change', { bubbles: true }));

      sendResponse({
        success: true,
        message: 'Content inserted successfully!'
      });
    } else {
      sendResponse({
        success: false,
        message: 'Found field but could not fill it.'
      });
    }
  } catch (error) {
    sendResponse({
      success: false,
      message: `Error: ${error.message}`
    });
  }
}

// Check if element is visible
function isVisible(element) {
  if (!element) return false;

  const style = window.getComputedStyle(element);
  return style.display !== 'none' &&
         style.visibility !== 'hidden' &&
         style.opacity !== '0' &&
         element.offsetParent !== null;
}

// Trigger React/Vue/Angular change handlers
function triggerReactChange(element, value) {
  // Try to find and update React fiber
  const fiberKey = Object.keys(element).find(key => key.startsWith('__react'));
  if (fiberKey) {
    const fiber = element[fiberKey];
    if (fiber && fiber.memoizedProps && fiber.memoizedProps.onChange) {
      fiber.memoizedProps.onChange({ target: { value } });
    }
  }

  // For Vue.js applications
  const vueKey = Object.keys(element).find(key => key.startsWith('__vue'));
  if (vueKey) {
    const vueInstance = element[vueKey];
    if (vueInstance && vueInstance._data) {
      // This is a heuristic; specific apps may need different handling
      element.value = value;
    }
  }
}
