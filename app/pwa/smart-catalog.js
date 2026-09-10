const $ = (id) => document.getElementById(id);

let token = localStorage.getItem('whatzabi_token') || '';
let catalogSource = '';
let selectedFile = null;
let analysis = null;

const MODE_LABELS = {
  product: 'Photo produit',
  invoice: 'Facture fournisseur',
  barcode: 'Code-barres / EAN',
};

function toast(message) {
  const node = $('catalogToast');
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    node.hidden = true;
  }, 2800);
}

function resetImage() {
  selectedFile = null;
  $('catalogPreview').removeAttribute('src');
  $('catalogPreviewWrap').hidden = true;
  $('catalogEmptyPreview').hidden = false;
  $('analyzeCatalogBtn').disabled = true;
  $('catalogStatus').textContent = '';
}

function selectMode(source) {
  catalogSource = source;
  $('captureChoices').hidden = true;
  $('capturePanel').hidden = false;
  $('catalogResults').hidden = true;
  $('captureModeLabel').textContent = MODE_LABELS[source] || 'Smart Catalog';
  resetImage();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showChoices() {
  catalogSource = '';
  analysis = null;
  $('captureChoices').hidden = false;
  $('capturePanel').hidden = true;
  $('catalogResults').hidden = true;
  resetImage();
}

function previewFile(file) {
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    toast('Choisis une image ou prends une photo.');
    return;
  }
  selectedFile = file;
  const url = URL.createObjectURL(file);
  $('catalogPreview').src = url;
  $('catalogPreviewWrap').hidden = false;
  $('catalogEmptyPreview').hidden = true;
  $('analyzeCatalogBtn').disabled = false;
  $('catalogStatus').textContent = `${Math.max(1, Math.round(file.size / 1024))} Ko prêts à analyser.`;
}

function money(value) {
  if (value === null || value === undefined || value === '') return null;
  return new Intl.NumberFormat('fr-FR').format(Number(value)) + ' FCFA';
}

function candidateMeta(candidate) {
  const items = [];
  if (candidate.brand) items.push(candidate.brand);
  if (candidate.variant) items.push(candidate.variant);
  if (candidate.packaging) items.push(candidate.packaging);
  if (candidate.unit) items.push(`Unité : ${candidate.unit}`);
  if (candidate.barcode) items.push(`EAN : ${candidate.barcode}`);
  if (candidate.quantity) items.push(`Qté : ${candidate.quantity}`);
  const price = money(candidate.purchase_price);
  if (price) items.push(`Achat : ${price}`);
  return items;
}

function renderResults(body) {
  analysis = body;
  const list = $('candidateList');
  list.innerHTML = '';
  const candidates = body.candidates || [];
  $('candidateCount').textContent = `${candidates.length} détecté${candidates.length > 1 ? 's' : ''}`;

  candidates.forEach((candidate, index) => {
    const card = document.createElement('article');
    card.className = 'catalog-candidate';

    const top = document.createElement('div');
    top.className = 'catalog-candidate-top';

    const titleWrap = document.createElement('div');
    const title = document.createElement('h3');
    title.textContent = candidate.name;
    titleWrap.appendChild(title);

    const confidence = document.createElement('span');
    confidence.className = 'catalog-confidence';
    confidence.textContent = `${Math.round((candidate.confidence || 0) * 100)}%`;

    top.appendChild(titleWrap);
    top.appendChild(confidence);
    card.appendChild(top);

    const meta = candidateMeta(candidate);
    if (meta.length) {
      const metaWrap = document.createElement('div');
      metaWrap.className = 'catalog-meta';
      meta.forEach((value) => {
        const chip = document.createElement('span');
        chip.className = 'catalog-chip';
        chip.textContent = value;
        metaWrap.appendChild(chip);
      });
      card.appendChild(metaWrap);
    }

    const matches = body.matches?.[String(index)] || body.matches?.[index] || [];
    const matchBox = document.createElement('div');
    if (matches.length) {
      matchBox.className = 'catalog-match';
      matchBox.textContent = `Produit proche déjà présent : ${matches[0].name} (${Math.round(matches[0].score * 100)}%). À valider avant création.`;
    } else {
      matchBox.className = 'catalog-no-match';
      matchBox.textContent = 'Aucun doublon proche détecté dans le catalogue.';
    }
    card.appendChild(matchBox);
    list.appendChild(card);
  });

  $('capturePanel').hidden = true;
  $('catalogResults').hidden = false;
  $('catalogResults').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function analyzeSelectedImage() {
  if (!selectedFile || !catalogSource) return;
  if (!token) {
    window.location.href = '/auth/app';
    return;
  }

  const sourceForApi = catalogSource === 'barcode' ? 'barcode' : catalogSource;
  const form = new FormData();
  form.append('image', selectedFile, selectedFile.name || 'catalog-image.jpg');
  form.append('source', sourceForApi);

  $('analyzeCatalogBtn').disabled = true;
  $('catalogStatus').textContent = 'Whatzabi analyse l’image…';

  try {
    const response = await fetch('/pwa/catalog/analyze', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + token },
      body: form,
    });

    let body = null;
    try { body = await response.json(); } catch {}

    if (response.status === 401) {
      localStorage.removeItem('whatzabi_token');
      window.location.href = '/auth/app';
      return;
    }

    if (!response.ok) {
      throw new Error(body?.detail || 'Analyse impossible');
    }

    renderResults(body);
  } catch (error) {
    $('catalogStatus').textContent = error.message;
    $('analyzeCatalogBtn').disabled = false;
    toast(error.message);
  }
}

function prepareProducts() {
  if (!analysis?.candidates?.length) return;
  sessionStorage.setItem('whatzabi_catalog_draft', JSON.stringify(analysis));
  toast('Brouillon catalogue préparé. La création en base reste désactivée pour ce premier test.');
}

document.querySelectorAll('[data-source]').forEach((button) => {
  button.addEventListener('click', () => selectMode(button.dataset.source));
});

$('changeModeBtn').addEventListener('click', showChoices);
$('restartCatalogBtn').addEventListener('click', showChoices);
$('takePhotoBtn').addEventListener('click', () => $('catalogCameraInput').click());
$('choosePhotoBtn').addEventListener('click', () => $('catalogGalleryInput').click());
$('catalogCameraInput').addEventListener('change', (event) => previewFile(event.target.files?.[0]));
$('catalogGalleryInput').addEventListener('change', (event) => previewFile(event.target.files?.[0]));
$('analyzeCatalogBtn').addEventListener('click', analyzeSelectedImage);
$('prepareProductsBtn').addEventListener('click', prepareProducts);
