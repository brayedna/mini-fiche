/**
 * Logique client — Mini Fiche
 *
 * Gère l'interaction drag & drop, l'affichage du nom de fichier,
 * le slider de niveau de détail et le loader animé.
 */

document.addEventListener('DOMContentLoaded', () => {
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const fileName = document.getElementById('fileName');
  const uploadForm = document.getElementById('uploadForm');
  const submitBtn = document.getElementById('submitBtn');
  const btnText = submitBtn.querySelector('.btn-text');
  const btnLoading = submitBtn.querySelector('.btn-loading');

  // --- Clic sur la zone d'upload → ouvrir le sélecteur de fichier ---
  dropZone.addEventListener('click', () => {
    fileInput.click();
  });

  // --- Afficher le nom du fichier sélectionné ---
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) {
      fileName.textContent = fileInput.files[0].name;
      dropZone.classList.add('drag-over');
    }
  });

  // --- Drag & Drop ---
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
  });

  dropZone.addEventListener('dragleave', () => {
    if (!fileInput.files.length) {
      dropZone.classList.remove('drag-over');
    }
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    const files = e.dataTransfer.files;

    if (files.length > 0) {
      const file = files[0];
      const ext = file.name.split('.').pop().toLowerCase();

      if (['pdf', 'docx'].includes(ext)) {
        fileInput.files = files;
        fileName.textContent = file.name;
        dropZone.classList.add('drag-over');
      } else {
        fileName.textContent = 'Format non supporté. Utilisez .pdf ou .docx';
        dropZone.classList.remove('drag-over');
      }
    }
  });

  // --- Slider niveau de détail ---
  const detailSlider = document.getElementById('detailSlider');
  const detailLabels = document.querySelectorAll('.detail-labels span');

  if (detailSlider) {
    detailSlider.addEventListener('input', () => {
      const value = detailSlider.value;
      detailLabels.forEach((label) => {
        label.classList.toggle('active', label.dataset.level === value);
      });
    });
  }

  // --- Loader animé ---
  const loaderOverlay = document.getElementById('loaderOverlay');
  const loaderStatus = document.getElementById('loaderStatus');
  const loaderSteps = document.querySelectorAll('.loader-step');

  const LOADER_PHASES = [
    { step: 1, text: 'Envoi du document...', delay: 0 },
    { step: 2, text: 'Analyse de la structure...', delay: 3000 },
    { step: 3, text: 'Résumé par l\'IA en cours...', delay: 8000 },
    { step: 4, text: 'Génération du fichier DOCX...', delay: 60000 },
  ];

  function setLoaderStep(stepNum, text) {
    loaderStatus.textContent = text;
    loaderSteps.forEach((el) => {
      const s = parseInt(el.dataset.step);
      el.classList.remove('active', 'done');
      if (s < stepNum) el.classList.add('done');
      if (s === stepNum) el.classList.add('active');
    });
  }

  function startLoader() {
    loaderOverlay.hidden = false;

    LOADER_PHASES.forEach(({ step, text, delay }) => {
      setTimeout(() => {
        if (!loaderOverlay.hidden) {
          setLoaderStep(step, text);
        }
      }, delay);
    });
  }

  // --- Soumission du formulaire ---
  uploadForm.addEventListener('submit', () => {
    if (!fileInput.files.length) return;

    submitBtn.disabled = true;
    btnText.hidden = true;
    btnLoading.hidden = false;

    startLoader();
  });
});
