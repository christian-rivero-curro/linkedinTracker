// options.js - JobAutoFill Configuration Logic

const DEFAULT_PROFILE = {
  first_name: '',
  last_name: '',
  full_name: '',
  email: '',
  phone_prefix: '+34',
  phone: '',
  id_document: '',
  address: '',
  city: '',
  postal_code: '',
  state: '',
  country: 'España',
  current_role: '',
  current_company: '',
  years_experience: '',
  salary_expectation: '',
  notice_period: '15 días',
  work_modality: 'Remoto',
  linkedin: '',
  github: '',
  website: '',
  twitter: '',
  cv_path: '',
  cv_file: null, // { name, type, size, dataUrl }
  work_authorization: 'yes',
  visa_sponsorship: 'no',
  english_level: 'Professional / Fluent (C1/C2)',
  disability: 'no',
  cover_letter: ''
};

const DEMO_PROFILE = {
  first_name: 'Christian',
  last_name: 'Rivero',
  full_name: 'Christian Rivero',
  email: 'christian.rivero@ejemplo.com',
  phone_prefix: '+34',
  phone: '612345678',
  id_document: '12345678Z',
  address: 'Paseo de la Castellana 100',
  city: 'Madrid',
  postal_code: '28046',
  state: 'Madrid',
  country: 'España',
  current_role: 'Senior Full Stack & AI Engineer',
  current_company: 'Tech Solutions S.L.',
  years_experience: '6',
  salary_expectation: '58000',
  notice_period: '15 días',
  work_modality: 'Remoto',
  linkedin: 'https://www.linkedin.com/in/christian-rivero',
  github: 'https://github.com/christian-rivero',
  website: 'https://christianrivero.dev',
  twitter: 'https://x.com/crivero_dev',
  cv_path: '/Users/christian.rivero/Documents/CV_Christian_Rivero.pdf',
  work_authorization: 'yes',
  visa_sponsorship: 'no',
  english_level: 'Professional / Fluent (C1/C2)',
  disability: 'no',
  cover_letter: 'Estimado equipo de selección,\n\nCuento con más de 6 años de experiencia desarrollando aplicaciones web robustas y escalables. Me apasiona resolver problemas complejos con código limpio y arquitecturas modernas.\n\nQuedo a su entera disposición para ampliar cualquier detalle sobre mi trayectoria.\n\nAtentamente,\nChristian Rivero'
};

const TAB_TITLES = {
  'tab-personal': { title: 'Datos Personales', subtitle: 'Configura tus nombres y datos de contacto directo' },
  'tab-location': { title: 'Ubicación', subtitle: 'Lugar de residencia y dirección fiscal/postal' },
  'tab-professional': { title: 'Perfil Profesional', subtitle: 'Experiencia, empresa actual y expectativas salariales' },
  'tab-links': { title: 'Enlaces y Redes', subtitle: 'Presencia digital, perfiles de LinkedIn y GitHub' },
  'tab-cv': { title: 'Currículum Vitae (CV)', subtitle: 'Archivo para auto-adjuntar y ruta en disco para copiado rápido' },
  'tab-questions': { title: 'Preguntas Frecuentes', subtitle: 'Respuestas automáticas a filtros habituales de RRHH' }
};

let currentStoredCV = null;

// DOM Elements
document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initForm();
  initCVHandling();
  initActions();
  loadSavedData();
});

// Tab Navigation
function initTabs() {
  const navItems = document.querySelectorAll('.nav-item');
  const tabPanes = document.querySelectorAll('.tab-pane');
  const titleEl = document.getElementById('page-title');
  const subtitleEl = document.getElementById('page-subtitle');

  navItems.forEach(item => {
    item.addEventListener('click', () => {
      const tabId = item.getAttribute('data-tab');

      navItems.forEach(n => n.classList.remove('active'));
      tabPanes.forEach(p => p.classList.remove('active'));

      item.classList.add('active');
      const targetPane = document.getElementById(tabId);
      if (targetPane) {
        targetPane.classList.add('active');
      }

      if (TAB_TITLES[tabId]) {
        titleEl.textContent = TAB_TITLES[tabId].title;
        subtitleEl.textContent = TAB_TITLES[tabId].subtitle;
      }
    });
  });
}

// Form Population & Serialization
function initForm() {
  // Autogenerate full name button
  const autoFullNameBtn = document.getElementById('btn-auto-fullname');
  if (autoFullNameBtn) {
    autoFullNameBtn.addEventListener('click', () => {
      const firstName = document.getElementById('first_name').value.trim();
      const lastName = document.getElementById('last_name').value.trim();
      if (firstName || lastName) {
        document.getElementById('full_name').value = `${firstName} ${lastName}`.trim();
        showToast('Nombre completo generado', '✨');
      }
    });
  }

  // Save button
  const saveBtn = document.getElementById('btn-save');
  saveBtn.addEventListener('click', saveFormData);

  // Form submit handler (when pressing Enter on inputs)
  const form = document.getElementById('profile-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      saveFormData();
    });
  }
}

function getFormData() {
  const form = document.getElementById('profile-form');
  const formData = new FormData(form);
  const data = {};

  for (const [key, value] of formData.entries()) {
    data[key] = value;
  }

  // Include CV if exists
  data.cv_file = currentStoredCV;
  return data;
}

function setFormData(data) {
  const merged = { ...DEFAULT_PROFILE, ...data };

  for (const key of Object.keys(DEFAULT_PROFILE)) {
    if (key === 'cv_file') continue;
    const el = document.getElementById(key);
    if (el) {
      el.value = merged[key] ?? '';
    }
  }

  if (merged.cv_file) {
    renderCVPreview(merged.cv_file);
  } else {
    clearCVPreview();
  }
}

// Load data from chrome.storage
function loadSavedData() {
  if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(['job_autofill_profile'], (result) => {
      if (result && result.job_autofill_profile) {
        setFormData(result.job_autofill_profile);
      }
    });
  } else {
    // Fallback for standalone preview
    const saved = localStorage.getItem('job_autofill_profile');
    if (saved) {
      try {
        setFormData(JSON.parse(saved));
      } catch (e) {
        console.error(e);
      }
    }
  }
}

// Save data
function saveFormData() {
  const data = getFormData();

  if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
    chrome.storage.local.set({ job_autofill_profile: data }, () => {
      showToast('Configuración guardada correctamente', '💾');
    });
  } else {
    localStorage.setItem('job_autofill_profile', JSON.stringify(data));
    showToast('Configuración guardada (modo local)', '💾');
  }
}

// CV Handling
function initCVHandling() {
  const dropzone = document.getElementById('cv-dropzone');
  const fileInput = document.getElementById('cv-file-input');
  const removeBtn = document.getElementById('btn-remove-cv');
  const copyPathBtn = document.getElementById('btn-copy-test');

  dropzone.addEventListener('click', (e) => {
    if (e.target.closest('#btn-remove-cv')) return;
    fileInput.click();
  });

  fileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      handleFileSelected(e.target.files[0]);
    }
  });

  // Drag & drop
  dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });

  dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('dragover');
  });

  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelected(e.dataTransfer.files[0]);
    }
  });

  removeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    currentStoredCV = null;
    clearCVPreview();
    showToast('CV eliminado del perfil', '🗑️');
  });

  copyPathBtn.addEventListener('click', () => {
    const path = document.getElementById('cv_path').value.trim();
    if (!path) {
      showToast('Primero introduce la ruta a tu CV', '⚠️');
      return;
    }
    navigator.clipboard.writeText(path).then(() => {
      showToast('Ruta copiada al portapapeles', '📋');
    }).catch(err => {
      showToast('Error al copiar ruta: ' + err, '❌');
    });
  });
}

function handleFileSelected(file) {
  if (file.size > 8 * 1024 * 1024) { // 8MB limit for local storage
    showToast('El archivo supera los 8MB permitidos', '⚠️');
    return;
  }

  const reader = new FileReader();
  reader.onload = (e) => {
    currentStoredCV = {
      name: file.name,
      type: file.type || 'application/pdf',
      size: file.size,
      lastModified: file.lastModified,
      dataUrl: e.target.result
    };
    renderCVPreview(currentStoredCV);
    showToast(`Archivo "${file.name}" cargado listo para guardar`, '📄');
  };
  reader.readAsDataURL(file);
}

function renderCVPreview(cv) {
  currentStoredCV = cv;
  const emptyEl = document.getElementById('dropzone-empty');
  const loadedEl = document.getElementById('dropzone-loaded');
  const nameEl = document.getElementById('cv-filename');
  const sizeEl = document.getElementById('cv-filesize');

  emptyEl.classList.add('hidden');
  loadedEl.classList.remove('hidden');

  nameEl.textContent = cv.name;
  const kb = Math.round(cv.size / 1024);
  sizeEl.textContent = kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`;
}

function clearCVPreview() {
  currentStoredCV = null;
  const emptyEl = document.getElementById('dropzone-empty');
  const loadedEl = document.getElementById('dropzone-loaded');
  const fileInput = document.getElementById('cv-file-input');

  emptyEl.classList.remove('hidden');
  loadedEl.classList.add('hidden');
  if (fileInput) fileInput.value = '';
}

// Action buttons: Demo data, Export, Import
function initActions() {
  // Demo Data
  document.getElementById('btn-demo-data').addEventListener('click', () => {
    setFormData(DEMO_PROFILE);
    showToast('Datos de demostración cargados. ¡Recuerda Guardar!', '⚡');
  });

  // Export JSON
  document.getElementById('btn-export').addEventListener('click', () => {
    const data = getFormData();
    // Exclude full dataUrl from JSON if huge or keep it as backup
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `JobAutoFill_Profile_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Perfil exportado en JSON', '⬇️');
  });

  // Import JSON
  const importInput = document.getElementById('file-import');
  importInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const data = JSON.parse(event.target.result);
          setFormData(data);
          showToast('Perfil importado correctamente', '⬆️');
        } catch (err) {
          showToast('Error: archivo JSON inválido', '❌');
        }
      };
      reader.readAsText(file);
    }
  });
}

// Toast helper
let toastTimeout = null;
function showToast(message, icon = '✅') {
  const toast = document.getElementById('toast');
  const msgEl = document.getElementById('toast-message');
  const iconEl = document.getElementById('toast-icon');

  msgEl.textContent = message;
  iconEl.textContent = icon;
  toast.classList.remove('hidden');

  if (toastTimeout) clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => {
    toast.classList.add('hidden');
  }, 3200);
}
