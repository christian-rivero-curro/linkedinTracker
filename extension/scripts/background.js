// background.js - Service Worker for JobAutoFill

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
  chrome.storage.local.get(['job_autofill_profile'], (result) => {
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
