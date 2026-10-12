(() => {
  let productId = null;
  let dialog;
  function ensureDialog() {
    if (dialog) return;
    dialog = document.createElement('dialog');
    dialog.style.cssText = 'max-width:440px;width:90%;border:0;border-radius:18px;padding:24px';
    dialog.innerHTML = `<h2>Code-barres interne</h2>
      <p data-label-name></p><div data-label-preview></div>
      <p class="muted small">Le même code reste valable après un changement de prix. L’impression ne modifie pas le stock.</p>
      <label class="field"><span>Nombre d’étiquettes</span><input data-label-copies type="number" min="1" max="200" value="1"></label>
      <label class="field"><span>Format</span><select data-label-layout><option value="a4">Feuille A4 — étiquettes 58 × 40 mm</option><option value="thermal">Thermique — 58 × 40 mm</option></select></label>
      <p class="muted small">Imprimer à 100 %, sans ajuster à la page.</p>
      <button type="button" data-label-download>Télécharger le PDF</button>
      <button type="button" data-label-close class="ghost">Fermer</button>`;
    document.body.appendChild(dialog);
    dialog.querySelector('[data-label-close]').onclick = () => dialog.close();
    dialog.querySelector('[data-label-download]').onclick = download;
  }
  async function download() {
    const input = dialog.querySelector('[data-label-copies]');
    if (!input.reportValidity()) return;
    const copies = Number(input.value);
    if (!Number.isInteger(copies)) { toast('Choisis un nombre entier.'); return; }
    const button = dialog.querySelector('[data-label-download]');
    button.disabled = true;
    try {
      const layout = dialog.querySelector('[data-label-layout]').value;
      const response = await fetch(`/pwa/catalog/products/${productId}/internal-barcode/labels.pdf?copies=${copies}&layout=${layout}`, {
        headers: { Authorization: 'Bearer ' + token },
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.detail || 'Impression indisponible.');
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = `whatzabi-etiquettes-${productId}.pdf`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) { toast(error.message); }
    finally { button.disabled = false; }
  }
  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-internal-barcode]');
    if (!button || button.disabled) return;
    button.disabled = true;
    const requestToken = token;
    try {
      const result = await api(`/pwa/catalog/products/${Number(button.dataset.internalBarcode)}/internal-barcode`, { method: 'POST' });
      if (token !== requestToken) return;
      ensureDialog();
      productId = result.product_id;
      dialog.querySelector('[data-label-name]').textContent = result.name;
      dialog.querySelector('[data-label-preview]').innerHTML = result.svg;
      const svg = dialog.querySelector('svg');
      if (svg) { svg.style.maxWidth = '100%'; svg.style.height = 'auto'; }
      dialog.showModal();
    } catch (error) { toast(error.message); }
    finally { button.disabled = false; }
  });
  document.getElementById('shopSelector')?.addEventListener('change', () => dialog?.close());
  document.getElementById('logoutBtn')?.addEventListener('click', () => dialog?.close());
})();
