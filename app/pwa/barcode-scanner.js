(() => {
  let controls = null;
  let stream = null;
  let scanning = false;
  let zxingPromise = null;

  const $ = (id) => document.getElementById(id);

  function ensureUI() {
    if ($('barcodeLiveView')) return;
    const view = document.createElement('section');
    view.id = 'barcodeLiveView';
    view.className = 'barcode-live-view';
    view.hidden = true;
    view.innerHTML = `
      <div class="barcode-live-head">
        <button id="barcodeLiveBack" type="button" class="ghost">‹ Retour</button>
        <strong>Scanner le code-barres</strong>
      </div>
      <div class="barcode-camera-frame">
        <video id="barcodeLiveVideo" autoplay playsinline muted></video>
        <div class="barcode-target" aria-hidden="true"><span></span></div>
      </div>
      <p id="barcodeLiveStatus" class="barcode-live-status">Place le code-barres dans le cadre.</p>
      <p class="muted small">La détection est automatique. Pas besoin de prendre une photo.</p>
      <button id="barcodePhotoFallback" type="button" class="ghost barcode-fallback">Utiliser une photo à la place</button>`;
    const card = document.querySelector('.catalog-sheet-card');
    card.appendChild(view);
    $('barcodeLiveBack').addEventListener('click', stopLiveScanner);
    $('barcodePhotoFallback').addEventListener('click', openPhotoFallback);
  }

  function setStatus(text, state = '') {
    const el = $('barcodeLiveStatus');
    if (!el) return;
    el.textContent = text;
    el.dataset.state = state;
  }

  function loadZXing() {
    if (window.ZXingBrowser) return Promise.resolve(window.ZXingBrowser);
    if (zxingPromise) return zxingPromise;
    zxingPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://unpkg.com/@zxing/browser@0.2.1';
      script.async = true;
      script.onload = () => window.ZXingBrowser ? resolve(window.ZXingBrowser) : reject(new Error('Lecteur code-barres indisponible'));
      script.onerror = () => reject(new Error('Impossible de charger le lecteur code-barres'));
      document.head.appendChild(script);
    });
    return zxingPromise;
  }

  function normalizeCode(value) {
    const code = String(value || '').replace(/\D/g, '');
    return code.length >= 8 && code.length <= 14 ? code : '';
  }

  async function lookup(code) {
    setStatus(`✓ Code ${code} détecté. Recherche du produit…`, 'success');
    if (navigator.vibrate) navigator.vibrate(80);
    const token = localStorage.getItem('whatzabi_token') || '';
    const response = await fetch(`/pwa/catalog/barcode/${encodeURIComponent(code)}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    let body = null;
    try { body = await response.json(); } catch {}
    if (!response.ok) throw new Error(body?.detail || `Code ${code} reconnu, mais produit absent du référentiel.`);
    return body;
  }

  function renderResult(body) {
    const candidates = body?.candidates || [];
    const list = $('catalogCandidateList');
    list.innerHTML = '';
    $('catalogResultCount').textContent = candidates.length ? `${candidates.length} produit détecté` : 'Code reconnu';
    candidates.forEach((c) => {
      const card = document.createElement('article');
      card.className = 'catalog-candidate';
      const title = document.createElement('h3');
      title.textContent = c.name || 'Produit';
      card.appendChild(title);
      const meta = document.createElement('div');
      meta.className = 'catalog-meta';
      [c.brand, c.packaging, c.barcode && `EAN : ${c.barcode}`].filter(Boolean).forEach((value) => {
        const chip = document.createElement('span');
        chip.className = 'catalog-chip';
        chip.textContent = value;
        meta.appendChild(chip);
      });
      card.appendChild(meta);
      list.appendChild(card);
    });
    $('barcodeLiveView').hidden = true;
    $('catalogResults').hidden = false;
    $('catalogModes').hidden = true;
    $('catalogCapture').hidden = true;
  }

  async function onDetected(raw) {
    if (!scanning) return;
    const code = normalizeCode(raw);
    if (!code) return;
    scanning = false;
    stopCameraOnly();
    try {
      const body = await lookup(code);
      renderResult(body);
    } catch (error) {
      setStatus(error.message, 'warning');
      $('barcodePhotoFallback').textContent = 'Photographier le produit pour l’identifier';
      $('barcodePhotoFallback').hidden = false;
    }
  }

  async function startZXing() {
    const ZXing = await loadZXing();
    const reader = new ZXing.BrowserMultiFormatReader();
    controls = await reader.decodeFromConstraints(
      { video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } } },
      $('barcodeLiveVideo'),
      (result) => { if (result) onDetected(result.getText ? result.getText() : result.text); }
    );
  }

  async function startLiveScanner() {
    ensureUI();
    $('catalogModes').hidden = true;
    $('catalogCapture').hidden = true;
    $('catalogResults').hidden = true;
    $('barcodeLiveView').hidden = false;
    $('barcodePhotoFallback').hidden = false;
    $('barcodePhotoFallback').textContent = 'Utiliser une photo à la place';
    setStatus('Ouverture de la caméra…');
    scanning = true;
    try {
      await startZXing();
      setStatus('Place le code-barres dans le cadre. Détection automatique.');
    } catch (error) {
      scanning = false;
      stopCameraOnly();
      setStatus('Caméra scanner indisponible. Tu peux utiliser une photo.', 'warning');
    }
  }

  function stopCameraOnly() {
    try { controls?.stop?.(); } catch {}
    controls = null;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
    const video = $('barcodeLiveVideo');
    if (video?.srcObject) {
      video.srcObject.getTracks().forEach((track) => track.stop());
      video.srcObject = null;
    }
  }

  function stopLiveScanner() {
    scanning = false;
    stopCameraOnly();
    if ($('barcodeLiveView')) $('barcodeLiveView').hidden = true;
    $('catalogModes').hidden = false;
    $('catalogCapture').hidden = true;
    $('catalogResults').hidden = true;
  }

  function openPhotoFallback() {
    scanning = false;
    stopCameraOnly();
    $('barcodeLiveView').hidden = true;
    $('catalogModes').hidden = false;
    $('catalogCapture').hidden = true;
    const productButton = document.querySelector('[data-catalog-source="product"]');
    if (productButton) productButton.click();
  }

  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-catalog-source="barcode"]');
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    startLiveScanner();
  }, true);

  document.addEventListener('click', (event) => {
    if (event.target.closest('#catalogCloseBtn') || event.target.closest('#catalogRestartBtn')) {
      scanning = false;
      stopCameraOnly();
      if ($('barcodeLiveView')) $('barcodeLiveView').hidden = true;
    }
  }, true);
})();
