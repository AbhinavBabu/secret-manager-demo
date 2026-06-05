/**
 * app.js — Secure Employee Document Portal
 * Client-side interactivity:
 *   - Live clock in the navbar
 *   - Sidebar mobile toggle
 *   - Login form: password toggle + loading state
 *   - Upload page: drag-and-drop, file validation, progress animation
 *   - Documents page: client-side table sorting
 */

/* ── Live clock ──────────────────────────────────────────────── */
function startClock() {
  const el = document.getElementById('currentTime');
  if (!el) return;

  const tick = () => {
    const now = new Date();
    el.textContent = now.toUTCString().replace(' GMT', ' UTC');
  };
  tick();
  setInterval(tick, 1000);
}

/* ── Sidebar mobile toggle ───────────────────────────────────── */
function initSidebar() {
  const toggle = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('sidebar');
  if (!toggle || !sidebar) return;

  toggle.addEventListener('click', () => {
    sidebar.classList.toggle('sidebar-open');
  });

  // Close sidebar when clicking outside on mobile
  document.addEventListener('click', (e) => {
    if (window.innerWidth < 992 &&
        !sidebar.contains(e.target) &&
        !toggle.contains(e.target)) {
      sidebar.classList.remove('sidebar-open');
    }
  });
}

/* ── Login page ──────────────────────────────────────────────── */
function initLoginPage() {
  // Password visibility toggle
  const toggleBtn = document.getElementById('togglePassword');
  const pwInput   = document.getElementById('password');
  const eyeIcon   = document.getElementById('pwEyeIcon');

  if (toggleBtn && pwInput) {
    toggleBtn.addEventListener('click', () => {
      const isVisible = pwInput.type === 'text';
      pwInput.type = isVisible ? 'password' : 'text';
      eyeIcon.className = isVisible ? 'bi bi-eye-fill' : 'bi bi-eye-slash-fill';
    });
  }

  // Show loading state on form submit
  const form      = document.getElementById('loginForm');
  const submitBtn = document.getElementById('loginSubmitBtn');

  if (form && submitBtn) {
    form.addEventListener('submit', () => {
      const btnText   = submitBtn.querySelector('.btn-text');
      const btnLoader = submitBtn.querySelector('.btn-loader');
      if (btnText)   btnText.classList.add('d-none');
      if (btnLoader) btnLoader.classList.remove('d-none');
      submitBtn.disabled = true;
    });
  }
}

/* ── Upload page ─────────────────────────────────────────────── */
function initUploadPage() {
  const dropZone        = document.getElementById('dropZone');
  const fileInput       = document.getElementById('documentInput');
  const dropContent     = document.getElementById('dropZoneContent');
  const selectedView    = document.getElementById('dropZoneSelected');
  const selectedName    = document.getElementById('selectedFileName');
  const selectedSize    = document.getElementById('selectedFileSize');
  const clearBtn        = document.getElementById('clearFile');
  const uploadBtn       = document.getElementById('uploadBtn');
  const descArea        = document.getElementById('description');
  const charCount       = document.getElementById('charCount');
  const form            = document.getElementById('uploadForm');
  const progressWrap    = document.getElementById('uploadProgressWrap');
  const progressBar     = document.getElementById('uploadProgressBar');
  const progressPct     = document.getElementById('uploadProgressPct');

  const MAX_SIZE = 20 * 1024 * 1024; // 20 MB

  if (!dropZone) return;

  // ── Drag-and-drop events ─────────────────────────────────────
  ['dragenter', 'dragover'].forEach(event => {
    dropZone.addEventListener(event, (e) => {
      e.preventDefault();
      dropZone.classList.add('drag-over');
    });
  });

  ['dragleave', 'drop'].forEach(event => {
    dropZone.addEventListener(event, (e) => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
    });
  });

  dropZone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      fileInput.files = files;
      handleFileSelected(files[0]);
    }
  });

  // ── File input change ─────────────────────────────────────────
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      handleFileSelected(fileInput.files[0]);
    }
  });

  // ── Handle file selection ─────────────────────────────────────
  function handleFileSelected(file) {
    // Validate PDF
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      showDropError('Only PDF files are allowed. Please select a valid PDF.');
      resetDropZone();
      return;
    }

    // Validate size
    if (file.size > MAX_SIZE) {
      showDropError(`File is too large (${formatSize(file.size)}). Maximum allowed is 20 MB.`);
      resetDropZone();
      return;
    }

    // Show selected state
    if (dropContent)   dropContent.classList.add('d-none');
    if (selectedView)  selectedView.classList.remove('d-none');
    if (selectedName)  selectedName.textContent = file.name;
    if (selectedSize)  selectedSize.textContent = formatSize(file.size);
    if (uploadBtn)     uploadBtn.disabled = false;
  }

  function resetDropZone() {
    if (dropContent)  dropContent.classList.remove('d-none');
    if (selectedView) selectedView.classList.add('d-none');
    if (uploadBtn)    uploadBtn.disabled = true;
    fileInput.value = '';
  }

  function showDropError(msg) {
    // Create a temporary alert
    const alert = document.createElement('div');
    alert.className = 'alert alert-danger mt-3 custom-alert';
    alert.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-2"></i>${msg}`;
    dropZone.insertAdjacentElement('afterend', alert);
    setTimeout(() => alert.remove(), 5000);
  }

  // ── Clear file ────────────────────────────────────────────────
  if (clearBtn) {
    clearBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      resetDropZone();
    });
  }

  // ── Keyboard accessibility for drop zone ─────────────────────
  dropZone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      fileInput.click();
    }
  });

  // ── Description character counter ─────────────────────────────
  if (descArea && charCount) {
    descArea.addEventListener('input', () => {
      charCount.textContent = descArea.value.length;
    });
  }

  // ── Form submission: show progress animation ──────────────────
  if (form) {
    form.addEventListener('submit', (e) => {
      if (!fileInput.files.length) {
        e.preventDefault();
        return;
      }

      // Show progress UI
      if (progressWrap) progressWrap.classList.remove('d-none');
      if (uploadBtn)    uploadBtn.disabled = true;

      // Animate progress bar (simulated — actual upload is server-side)
      let pct = 0;
      const step1 = document.getElementById('step1');
      const step2 = document.getElementById('step2');
      const step3 = document.getElementById('step3');

      const interval = setInterval(() => {
        if (pct < 45) {
          pct += 2;
        } else if (pct < 75) {
          pct += 1;
          if (step2) step2.classList.add('active');
        } else if (pct < 92) {
          pct += 0.5;
          if (step3) step3.classList.add('active');
        }

        if (progressBar)  progressBar.style.width = `${pct}%`;
        if (progressPct)  progressPct.textContent  = `${Math.round(pct)}%`;
      }, 120);

      // Store interval id so it can be cleared if needed
      window._uploadInterval = interval;
    });
  }
}

/* ── Documents page ──────────────────────────────────────────── */
function initDocumentsPage() {
  initTableSort();
}

function initTableSort() {
  const table = document.getElementById('documentsTable');
  if (!table) return;

  const headers = table.querySelectorAll('th.sortable');
  let lastCol = -1;
  let asc = true;

  headers.forEach((th) => {
    th.addEventListener('click', () => {
      const col = parseInt(th.dataset.col, 10);
      asc = (col === lastCol) ? !asc : true;
      lastCol = col;

      // Update sort icons
      table.querySelectorAll('.sort-icon').forEach(icon => {
        icon.className = 'bi bi-arrow-down-up ms-1 sort-icon';
      });
      const icon = th.querySelector('.sort-icon');
      if (icon) icon.className = `bi bi-arrow-${asc ? 'down' : 'up'} ms-1 sort-icon`;

      // Sort rows
      const tbody = table.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));

      rows.sort((a, b) => {
        const aText = a.querySelectorAll('td')[col]?.textContent.trim() ?? '';
        const bText = b.querySelectorAll('td')[col]?.textContent.trim() ?? '';
        const cmp = aText.localeCompare(bText, undefined, { numeric: true });
        return asc ? cmp : -cmp;
      });

      rows.forEach(row => tbody.appendChild(row));
    });
  });
}

/* ── Auto-dismiss flash messages ─────────────────────────────── */
function initFlashMessages() {
  document.querySelectorAll('.custom-alert').forEach((alert) => {
    setTimeout(() => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      bsAlert.close();
    }, 6000);
  });
}

/* ── Utility ──────────────────────────────────────────────────── */
function formatSize(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  if (bytes >= 1024)        return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

/* ── Bootstrap tooltip init ──────────────────────────────────── */
function initTooltips() {
  const tooltipEls = document.querySelectorAll('[data-bs-toggle="tooltip"]');
  tooltipEls.forEach(el => new bootstrap.Tooltip(el));
}

/* ── Main init ────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  startClock();
  initSidebar();
  initLoginPage();
  initFlashMessages();
  initTooltips();
  // Upload and Documents pages are initialised from inline script in their templates
});
