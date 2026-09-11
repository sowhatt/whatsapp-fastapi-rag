(() => {
  let controls = null;
  let scanning = false;
  let zxingPromise = null;
  const byId = (id) => document.getElementById(id);

  function ensureUI() {
    if (byId('barcodeLiveView')) return;
    const view = document.createElement('section');
    view.id = 'barcodeLiveView';
    view.className = 'barcode-live-view';
    view.hidden = true;
    view.innerHTML = `<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin:12px 0"><button id="barcodeLiveBack" type="button" class="ghost">‹ Retour</button><strong>Scanner le code-barres</strong></div><div style="position:relative;overflow:hidden;border-radius:18px;background:#10211f;aspect-ratio:4/3"><video id="barcodeLiveVideo" autoplay playsinline muted style="width:100%;height:100%;object-fit:cover"></video><div style="position:absolute;left:8%;right:8%;top:35%;height:30%;border:3px solid #fff;border-radius:14px;box-shadow:0 0 0 999px rgba(0,0,0,.28)"></div></div><p id="barcodeLiveStatus" style="font-weight:700;text-align:center;margin:14px 0">Place le code-barres dans le cadre.</p><p class="muted small" style="text-align:center">Détection automatique — pas besoin de prendre une photo.</p><button id="barcodePhotoFallback" type="button" class="ghost" style="width:100%">Photographier le produit à la place</button>`;
    document.querySelector('.catalog-sheet-card')?.appendChild(view);
    byId('barcodeLiveBack').addEventListener('click', stopScanner);
    byId('barcodePhotoFallback').addEventListener('click', photoFallback);
  }

  function status(text) { if (byId('barcodeLiveStatus')) byId('barcodeLiveStatus').textContent = text; }
  function loadZXing() {
    if (window.ZXingBrowser) return Promise.resolve(window.ZXingBrowser);
    if (zxingPromise) return zxingPromise;
    zxingPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://unpkg.com/@zxing/browser@0.2.1';
      script.async = true;
      script.onload = () => window.ZXingBrowser ? resolve(window.ZXingBrowser) : reject(new Error('Lecteur indisponible'));
      script.onerror = () => reject(new Error('Lecteur indisponible'));
      document.head.appendChild(script);
    });
    return zxingPromise;
  }
  function stopCamera() {
    try { controls?.stop?.(); } catch {}
    controls = null;
    const video = byId('barcodeLiveVideo');
    if (video?.srcObject) { video.srcObject.getTracks().forEach(t => t.stop()); video.srcObject = null; }
  }
  function stopScanner() {
    scanning = false; stopCamera();
    if (byId('barcodeLiveView')) byId('barcodeLiveView').hidden = true;
    if (byId('catalogModes')) byId('catalogModes').hidden = false;
  }
  async function lookup(code) {
    status(`✓ ${code} détecté — recherche du produit…`);
    navigator.vibrate?.(80);
    const token = localStorage.getItem('whatzabi_token') || '';
    const response = await fetch(`/pwa/catalog/barcode/${encodeURIComponent(code)}`, { headers: { Authorization: `Bearer ${token}` } });
    let body = null; try { body = await response.json(); } catch {}
    if (!response.ok) throw new Error(body?.detail || `Code ${code} reconnu, produit absent du référentiel.`);
    return body;
  }
  function showResult(body) {
    const candidates = body?.candidates || [];
    const list = byId('catalogCandidateList');
    list.innerHTML = '';
    byId('catalogResultCount').textContent = `${candidates.length} produit${candidates.length > 1 ? 's' : ''} détecté${candidates.length > 1 ? 's' : ''}`;
    candidates.forEach(c => {
      const card = document.createElement('article'); card.className = 'catalog-candidate';
      const h = document.createElement('h3'); h.textContent = c.name || 'Produit'; card.appendChild(h);
      const meta = document.createElement('div'); meta.className = 'catalog-meta';
      [c.brand, c.packaging, c.barcode && `EAN : ${c.barcode}`].filter(Boolean).forEach(v => { const chip = document.createElement('span'); chip.className = 'catalog-chip'; chip.textContent = v; meta.appendChild(chip); });
      card.appendChild(meta); list.appendChild(card);
    });
    byId('barcodeLiveView').hidden = true; byId('catalogResults').hidden = false; byId('catalogModes').hidden = true; byId('catalogCapture').hidden = true;
  }
  async function detected(value) {
    if (!scanning) return;
    const code = String(value || '').replace(/\D/g, '');
    if (code.length < 8 || code.length > 14) return;
    scanning = false; stopCamera();
    try { showResult(await lookup(code)); }
    catch (e) { status(e.message); byId('barcodePhotoFallback').textContent = 'Photographier le produit pour l’identifier'; }
  }
  async function startScanner() {
    ensureUI();
    byId('catalogModes').hidden = true; byId('catalogCapture').hidden = true; byId('catalogResults').hidden = true; byId('barcodeLiveView').hidden = false;
    scanning = true; status('Ouverture de la caméra…');
    try {
      const ZXing = await loadZXing();
      const reader = new ZXing.BrowserMultiFormatReader();
      controls = await reader.decodeFromConstraints({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } } }, byId('barcodeLiveVideo'), result => { if (result) detected(result.getText ? result.getText() : result.text); });
      status('Place le code-barres dans le cadre. Détection automatique.');
    } catch { scanning = false; stopCamera(); status('Caméra scanner indisponible. Utilise la photo produit.'); }
  }
  function photoFallback() {
    stopScanner();
    const product = document.querySelector('[data-catalog-source="product"]');
    product?.click();
  }
  document.addEventListener('click', e => {
    const button = e.target.closest('[data-catalog-source="barcode"]');
    if (!button) return;
    e.preventDefault(); e.stopImmediatePropagation(); startScanner();
  }, true);
  document.addEventListener('click', e => {
    if (e.target.closest('#catalogCloseBtn') || e.target.closest('#catalogRestartBtn')) { scanning = false; stopCamera(); }
  }, true);
})();