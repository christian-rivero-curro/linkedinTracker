// background.js - Service Worker for JobAutoFill

// Helper to update action icon badge based on active state
function updateExtensionBadge(isEnabled) {
  if (chrome.action && chrome.action.setBadgeText) {
    if (isEnabled) {
      chrome.action.setBadgeText({ text: '' });
    } else {
      chrome.action.setBadgeText({ text: 'OFF' });
      if (chrome.action.setBadgeBackgroundColor) {
        chrome.action.setBadgeBackgroundColor({ color: '#64748b' });
      }
    }
  }
}

// Setup on install
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    // Open options page on first installation
    chrome.runtime.openOptionsPage();
  }

  // Create context menu for right click
  chrome.contextMenus.create({
    id: 'jobautofill-fill-page',
    title: '⚡ Rellenar oferta con JobAutoFill',
    contexts: ['page', 'editable']
  });

  // Check initial state
  chrome.storage.local.get(['job_autofill_enabled'], (res) => {
    updateExtensionBadge(res?.job_autofill_enabled !== false);
  });
});

// Update badge when enabled state changes in storage
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.job_autofill_enabled !== undefined) {
    updateExtensionBadge(changes.job_autofill_enabled.newValue !== false);
  }
});

// Context menu click listener
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === 'jobautofill-fill-page' && tab && tab.id) {
    triggerAutofillOnTab(tab.id);
  }
});

// Keyboard shortcut listener (Alt+Shift+F)
chrome.commands.onCommand.addListener((command) => {
  if (command === 'autofill_job') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0] && tabs[0].id) {
        triggerAutofillOnTab(tabs[0].id);
      }
    });
  }
});

// Helper to trigger autofill on a specific tab
function triggerAutofillOnTab(tabId) {
  chrome.storage.local.get(['job_autofill_profile', 'job_autofill_enabled'], (result) => {
    const isEnabled = result?.job_autofill_enabled !== false;
    if (!isEnabled) {
      console.log('[JobAutoFill] Extensión desactivada temporalmente, autofill omitido.');
      return;
    }

    const profile = result?.job_autofill_profile;
    
    chrome.tabs.sendMessage(tabId, { action: 'AUTOFILL', profile }, (response) => {
      if (chrome.runtime.lastError) {
        // Content script might need manual injection
        chrome.scripting.executeScript({
          target: { tabId },
          files: ['scripts/content.js']
        }, () => {
          chrome.scripting.insertCSS({
            target: { tabId },
            files: ['scripts/content.css']
          }, () => {
            chrome.tabs.sendMessage(tabId, { action: 'AUTOFILL', profile });
          });
        });
      }
    });
  });
}
