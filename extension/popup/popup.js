// popup.js - JobAutoFill Popup Action Controller

let currentProfile = null;

document.addEventListener('DOMContentLoaded', () => {
  initPopup();
});

function initPopup() {
  loadProfile();

  // Button Listeners
  document.getElementById('btn-open-options').addEventListener('click', openOptions);
  document.getElementById('btn-edit-profile').addEventListener('click', openOptions);
  document.getElementById('btn-autofill-now').addEventListener('click', triggerAutofill);
  document.getElementById('btn-copy-cv-path').addEventListener('click', copyCVPath);
  document.getElementById('btn-download-cv').addEventListener('click', downloadCV);
}

function openOptions() {
  if (chrome.runtime.openOptionsPage) {
    chrome.runtime.openOptionsPage();
  } else {
    window.open(chrome.runtime.getURL('options/options.html'));
  }
}

function loadProfile() {
  chrome.storage.local.get(['job_autofill_profile'], (result) => {
    if (result && result.job_autofill_profile) {
      currentProfile = result.job_autofill_profile;
      renderProfileUI(currentProfile);
    } else {
      renderEmptyProfileUI();
    }
  });
}

function renderProfileUI(profile) {
  const name = profile.full_name || `${profile.first_name || ''} ${profile.last_name || ''}`.trim() || 'Sin nombre';
  const email = profile.email || 'Sin correo configurado';

  document.getElementById('profile-name').textContent = name;
  document.getElementById('profile-email').textContent = email;

  // Avatar initials
  const initials = getInitials(name);
  document.getElementById('profile-avatar').textContent = initials;

  // CV pill
  const pill = document.getElementById('cv-pill');
  const pillText = document.getElementById('cv-status-text');

  if (profile.cv_file && profile.cv_file.name) {
    pill.classList.remove('warning');
    pillText.textContent = `CV: ${profile.cv_file.name}`;
  } else if (profile.cv_path) {
    pill.classList.remove('warning');
    pillText.textContent = `Ruta CV configurada`;
  } else {
    pill.classList.add('warning');
    pillText.textContent = 'Sin CV configurado';
  }
}

function renderEmptyProfileUI() {
  document.getElementById('profile-name').textContent = 'Perfil no configurado';
  document.getElementById('profile-email').textContent = 'Haz clic abajo para rellenar tus datos';
  document.getElementById('profile-avatar').textContent = '⚠️';

  const pill = document.getElementById('cv-pill');
  const pillText = document.getElementById('cv-status-text');
  pill.classList.add('warning');
  pillText.textContent = 'Faltan tus datos de contacto';
}

function getInitials(name) {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase() || 'CV';
}

async function triggerAutofill() {
  setStatus('Analizando formulario de la página...', '🔍');

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) {
    setStatus('No se encontró una pestaña activa', '⚠️');
    return;
  }

  // Ensure content script is ready
  try {
    const response = await sendMessageToTab(tab.id, {
      action: 'AUTOFILL',
      profile: currentProfile
    });

    if (response && response.success) {
      const count = response.filledCount || 0;
      setStatus(`¡${count} campo(s) rellenado(s) con éxito!`, '🎉');
    } else {
      setStatus(response?.message || 'No se detectaron campos rellenables', 'ℹ️');
    }
  } catch (err) {
    // If content script was not loaded yet on this tab, inject it and retry
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['scripts/content.js']
      });
      await chrome.scripting.insertCSS({
        target: { tabId: tab.id },
        files: ['scripts/content.css']
      });

      // Retry sending message
      const response = await sendMessageToTab(tab.id, {
        action: 'AUTOFILL',
        profile: currentProfile
      });

      if (response && response.success) {
        setStatus(`¡${response.filledCount} campo(s) rellenado(s)!`, '🎉');
      } else {
        setStatus(response?.message || 'Formulario analizado', 'ℹ️');
      }
    } catch (injectErr) {
      console.error(injectErr);
      setStatus('No se puede ejecutar en esta página (ej: página interna de Chrome)', '❌');
    }
  }
}

function sendMessageToTab(tabId, message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        reject(chrome.runtime.lastError);
      } else {
        resolve(response);
      }
    });
  });
}

function copyCVPath() {
  if (!currentProfile || !currentProfile.cv_path) {
    setStatus('No has guardado la ruta a tu CV todavía', '⚠️');
    return;
  }
  navigator.clipboard.writeText(currentProfile.cv_path).then(() => {
    setStatus('Ruta de CV copiada al portapapeles', '📋');
  }).catch(() => {
    setStatus('Error al copiar al portapapeles', '❌');
  });
}

function downloadCV() {
  if (!currentProfile || !currentProfile.cv_file || !currentProfile.cv_file.dataUrl) {
    setStatus('No has subido un archivo de CV a la extensión', '⚠️');
    return;
  }

  const a = document.createElement('a');
  a.href = currentProfile.cv_file.dataUrl;
  a.download = currentProfile.cv_file.name || 'CV_Christian_Rivero.pdf';
  a.click();
  setStatus('Descargando archivo CV...', '⬇️');
}

let statusTimer = null;
function setStatus(text, icon = 'ℹ️') {
  const box = document.getElementById('status-message');
  const textEl = document.getElementById('status-text');
  const iconEl = document.getElementById('status-icon');

  textEl.textContent = text;
  iconEl.textContent = icon;
  box.classList.remove('hidden');

  if (statusTimer) clearTimeout(statusTimer);
  statusTimer = setTimeout(() => {
    box.classList.add('hidden');
  }, 4000);
}
