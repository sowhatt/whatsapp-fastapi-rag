(() => {
  const purchaseCart = new Map();
  let suppliers = [];
  let purchases = [];
  let selectedPayablePurchaseId = null;
  let loadedShopId = null;
  let loadingPurchasingData = false;
  let scope = null, generation = 0, loadGeneration = 0, storageHash = null;
  let pending = {}, keys = {}, writing = false;
  const savedFields = ['purchaseSupplier', 'purchasePaidAmount', 'purchaseDueDate', 'purchasePaymentChannel',
    'purchaseQuickSupplierName', 'purchaseQuickSupplierPhone', 'supplierName', 'supplierPhone',
    'supplierPaymentAmount', 'supplierPaymentChannel', 'supplierPaymentReference', 'supplierPaymentDate'];
  const storageKey = 'whatzabi.purchasing.v1';
  const context = () => ({merchant:state.merchant?.id, shop:state.merchant?.shop_id, token, generation});
  const same = value => value && value.merchant === state.merchant?.id &&
    value.shop === state.merchant?.shop_id && value.token === token && value.generation === generation;
  function status(message) { if ($('purchasingStatus')) $('purchasingStatus').textContent = message; }
  function persist() {
    if (!same(scope) || !storageHash) return;
    try { sessionStorage.setItem(storageKey, JSON.stringify({
      hash:storageHash, cart:[...purchaseCart.values()], pending, keys, selectedPayablePurchaseId,
      fields:Object.fromEntries(savedFields.map(id => [id, $(id)?.value || '']))
    })); } catch { /* The in-memory form remains available. */ }
  }
  function checkContext() {
    if (same(scope)) return;
    generation++;
    scope = context();
    storageHash = null;
    purchaseCart.clear(); suppliers = []; purchases = [];
    pending = {}; keys = {}; selectedPayablePurchaseId = null;
    loadedShopId = null; loadingPurchasingData = false;
    for (const id of savedFields) if ($(id)) $(id).value = '';
    if ($('supplierPaymentSheet')) $('supplierPaymentSheet').hidden = true;
    status('');
    renderPurchaseCart(); renderPurchases(); renderSupplierWorkspace(); renderSupplierDebtDashboard();
  }
  async function ready() {
    checkContext();
    const before = scope;
    if (!storageHash && before.token && before.shop) {
      try {
        const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([before.merchant, before.shop, before.token])));
        if (!same(before)) return null;
        storageHash = [...new Uint8Array(bytes)].map(b => b.toString(16).padStart(2, '0')).join('');
        const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
        if (saved?.hash === storageHash && Array.isArray(saved.cart)) {
          for (const line of saved.cart) purchaseCart.set(line.product.id, line);
          pending = saved.pending || {}; keys = saved.keys || {};
          selectedPayablePurchaseId = saved.selectedPayablePurchaseId;
          for (const id of savedFields) if ($(id)) $(id).value = saved.fields[id] || '';
          if (pending.payment) $('supplierPaymentSheet').hidden = false;
          renderPurchaseCart();
          status('Brouillon restauré. Une confirmation en attente se rejoue avec le même contenu.');
        } else if (saved) sessionStorage.removeItem(storageKey);
      } catch { /* Recovery is optional when browser storage is unavailable. */ }
    }
    return same(before) ? before : null;
  }
  function freeze() {
    const purchaseFrozen = writing || !!pending.purchase;
    for (const id of ['purchaseSupplier', 'purchaseProduct', 'purchaseQty', 'purchaseUnitCost',
      'purchaseAddLineBtn', 'purchasePaidAmount', 'purchasePaymentChannel', 'purchaseDueDate']) {
      if ($(id)) $(id).disabled = purchaseFrozen;
    }
    for (const id of ['purchaseQuickSupplierName', 'purchaseQuickSupplierPhone', 'supplierName', 'supplierPhone']) {
      if ($(id)) $(id).disabled = writing || !!pending.supplier;
    }
    for (const id of ['supplierPaymentAmount', 'supplierPaymentChannel', 'supplierPaymentReference', 'supplierPaymentDate']) {
      if ($(id)) $(id).disabled = writing || !!pending.payment;
    }
    for (const id of ['purchaseSubmitBtn', 'supplierPaymentSubmitBtn', 'purchaseQuickSupplierBtn']) {
      if ($(id)) $(id).disabled = writing;
    }
  }
  async function write(kind, path, build) {
    if (writing) return null;
    writing = true; freeze();
    let before;
    try {
      before = await ready();
      if (!before?.shop || !before?.token) throw new Error('Sélectionne une boutique et reconnecte-toi.');
      if (!pending[kind]) {
        keys[kind] ||= crypto.randomUUID();
        pending[kind] = {...build(), shop_id:Number(before.shop), idempotency_key:keys[kind]};
      }
      persist(); freeze();
      if (!same(before)) return null;
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 90000);
      let result;
      try { result = await api(path, {method:'POST', body:JSON.stringify(pending[kind]), signal:controller.signal}); }
      finally { clearTimeout(timer); }
      if (!same(before)) return null;
      if (!Number.isInteger(result?.id) || result.id <= 0) throw new Error('Réponse incomplète. Relance la même confirmation.');
      delete pending[kind]; delete keys[kind]; persist();
      return result;
    } catch (error) {
      if (same(before)) {
        if (error.status && error.status < 500) delete pending[kind];
        persist();
        status((error.status ? error.message : 'Réponse non confirmée. Réessaie la même validation.') + ' Le formulaire est conservé.');
      }
      return null;
    } finally { writing = false; freeze(); }
  }
  async function refreshAfterWrite(withStock = false) {
    const before = scope;
    try {
      const results = await Promise.allSettled([
        withStock ? api('/pwa/products', {cache:'no-store'}) : Promise.resolve(null),
        can('report.read') ? api('/pwa/finance/overview?period=' + (state.financePeriod || 'month'), {cache:'no-store'}) : Promise.resolve(null),
        loadPurchasingData(),
      ]);
      if (!same(before)) return;
      if (results.some(result => result.status === 'rejected')) throw new Error('refresh failed');
      const [products, finance] = results.map(result => result.value);
      if (products) state.products = products;
      if (finance) { state.finance = finance; renderFinanceOverview(finance); }
      render();
    } catch {
      if (same(before)) status('Écriture enregistrée. Indicateurs à actualiser : utilise « Actualiser les achats ».');
    }
  }
  $('purchasingRefreshBtn')?.addEventListener('click', () => refreshAfterWrite(true));
  document.addEventListener('input', () => { renderPurchaseAmounts(); persist(); });
  document.addEventListener('change', persist);


  const money = (value) => fmt(Number(value || 0));

  function localDateKey(date = new Date()) {
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    return yyyy + '-' + mm + '-' + dd;
  }

  function setPurchaseDueDays(days) {
    const input = $('purchaseDueDate');
    if (!input) return;
    const date = new Date();
    date.setDate(date.getDate() + Number(days || 0));
    input.value = localDateKey(date);
  }

  function purchaseTotal() {
    return [...purchaseCart.values()].reduce(
      (sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_cost || 0),
      0,
    );
  }

  function syncPurchaseSelectors() {
    const supplierSelect = $('purchaseSupplier');
    const productSelect = $('purchaseProduct');

    if (supplierSelect) {
      const selected = supplierSelect.value;
      supplierSelect.innerHTML =
        '<option value="">Sans fournisseur identifié (achat comptant)</option>' +
        suppliers
          .map((supplier) =>
            '<option value="' + supplier.id + '">' + esc(supplier.name) + '</option>'
          )
          .join('');
      if ([...supplierSelect.options].some((option) => option.value === selected)) {
        supplierSelect.value = selected;
      }
    }

    if (productSelect) {
      const selected = productSelect.value;
      productSelect.innerHTML =
        '<option value="">Choisir un produit</option>' +
        state.products
          .map((product) =>
            '<option value="' + product.id + '">' +
            esc(product.name) + ' · stock ' + Number(product.stock || 0) +
            '</option>'
          )
          .join('');
      if ([...productSelect.options].some((option) => option.value === selected)) {
        productSelect.value = selected;
      }
    }
  }

  function syncPurchaseDetailsVisibility() {
    if ($('purchaseDetails')) $('purchaseDetails').hidden = false;
    if ($('purchaseSupplierHint')) $('purchaseSupplierHint').textContent =
      'Fournisseur facultatif si tout est payé ; obligatoire pour toute dette.';
    if ($('purchaseQuickSupplier')) $('purchaseQuickSupplier').hidden = !can('supplier.create');
  }
  function onPurchaseSupplierChanged() { syncPurchaseDetailsVisibility(); persist(); }
  function renderPurchaseAmounts() {
    const total = purchaseTotal(), paid = Number($('purchasePaidAmount')?.value || 0);
    if ($('purchaseRemaining')) $('purchaseRemaining').textContent = money(total - paid);
    if ($('purchasePaidSummary')) $('purchasePaidSummary').textContent = money(paid);
    if ($('purchaseDueDate')) $('purchaseDueDate').required = total > paid;
  }

  function renderPurchaseCart() {
    const box = $('purchaseCart');
    if (!box) return;

    const lines = [...purchaseCart.values()];
    box.innerHTML = lines.length
      ? lines.map((line) => {
          const lineTotal = Number(line.quantity) * Number(line.unit_cost);
          return `
            <article class="purchase-line">
              <div>
                <strong>${esc(line.product.name)}</strong>
                <span>${line.quantity} × ${money(line.unit_cost)}</span>
              </div>
              <div class="purchase-line-end">
                <strong>${money(lineTotal)}</strong>
                <button type="button" class="ghost" data-purchase-remove="${line.product.id}">Retirer</button>
              </div>
            </article>
          `;
        }).join('')
      : '<p class="muted empty-state">Aucune ligne d’achat.</p>';

    $('purchaseTotal').textContent = money(purchaseTotal());
    renderPurchaseAmounts();

    const total = purchaseTotal();
    const paidInput = $('purchasePaidAmount');
    if (paidInput) {
      paidInput.max = String(total);

    }
  }

  function supplierName(id) {
    return suppliers.find((supplier) => Number(supplier.id) === Number(id))?.name || (id ? 'Fournisseur' : 'Comptant sans fournisseur');
  }

  function purchaseStatusLabel(status) {
    const labels = {
      paid: 'Payé',
      credit: 'À crédit',
      partial: 'Partiel',
      cancelled: 'Annulé',
    };
    return labels[status] || status || '';
  }

  function renderSupplierDebtDashboard() {
    const card = $('statSupplierDebtCard');
    const totalEl = $('statSupplierDebt');
    const countEl = $('statSupplierDebtCount');

    if (!card || !totalEl || !countEl) return;

    const allowed = can('supplier.read') && can('purchase.read');
    card.hidden = !allowed;
    if (!allowed) return;

    // purchases is already scoped by the backend to the active shop.
    const openPurchases = purchases.filter((purchase) =>
      Number(purchase.remaining_amount || 0) > 0 &&
      String(purchase.status) !== 'cancelled'
    );

    const totalDebt = openPurchases.reduce(
      (sum, purchase) => sum + Number(purchase.remaining_amount || 0),
      0,
    );

    const supplierIds = new Set(
      openPurchases
        .map((purchase) => Number(purchase.supplier_id || 0))
        .filter((id) => id > 0)
    );

    totalEl.textContent = money(totalDebt);
    countEl.textContent =
      supplierIds.size +
      (supplierIds.size > 1 ? ' fournisseurs' : ' fournisseur');
  }

  function renderSupplierWorkspace() {
    if ($('supplierCount')) $('supplierCount').textContent = String(suppliers.length);
    if ($('supplierDebtTotal')) {
      $('supplierDebtTotal').textContent = money(
        suppliers.reduce((sum, supplier) => sum + Number(supplier.debt || 0), 0)
      );
    }

    if ($('supplierCreateCard')) {
      $('supplierCreateCard').hidden = !can('supplier.create');
    }

    if ($('supplierList')) {
      $('supplierList').innerHTML = suppliers.length
        ? suppliers.map((supplier) => {
            const debt = Number(supplier.debt || 0);
            return `
              <article class="item">
                <div class="item-main">
                  <div class="item-title">${esc(supplier.name)}</div>
                  <div class="item-meta">${esc(supplier.phone || 'Sans téléphone')}</div>
                </div>
                ${debt > 0 && can('supplier_payment.create')
                  ? '<button type="button" class="debt-link" data-supplier-debt="' + supplier.id + '">Dette ' + money(debt) + ' ›</button>'
                  : '<div class="money">Dette ' + money(debt) + '</div>'}
              </article>
            `;
          }).join('')
        : '<p class="muted empty-state">Aucun fournisseur.</p>';
    }
  }

  function renderPurchases() {
    const today = localDateKey();

    if ($('purchaseList')) {
      $('purchaseList').innerHTML = purchases.length
        ? purchases.slice(0, 20).map((purchase) => `
            <article class="purchase-history-row">
              <div>
                <strong>${esc(supplierName(purchase.supplier_id))}</strong>
                <span>Achat #${purchase.id} · ${esc(purchaseStatusLabel(purchase.status))}</span>
                <small>${purchase.created_at ? esc(fmtSaleDate(purchase.created_at)) : ''}</small>
              </div>
              <div class="purchase-line-end">
                <strong>${money(purchase.total_amount)}</strong>
                <small>Total payé ${money(purchase.paid_amount)} · Reste dû ${money(purchase.remaining_amount)}</small>
                <small>Versement initial ${purchase.initial_paid_amount == null ? 'inconnu' : money(purchase.initial_paid_amount)} · Crédit initial ${purchase.initial_credit_amount == null ? 'inconnu' : money(purchase.initial_credit_amount)}</small>
                <small>Paiements ultérieurs ${purchase.subsequent_paid_amount == null ? 'non déterminables' : money(purchase.subsequent_paid_amount)}</small>
                <small>Échéance ${esc(fmtDueDate(purchase.due_date))}</small>
                <button type="button" data-purchase-payments="${purchase.id}">Voir les règlements datés</button>
                <div id="purchasePayments-${purchase.id}" aria-live="polite"></div>
              </div>
            </article>
          `).join('')
        : '<p class="muted empty-state">Aucun achat.</p>';
    }

    const payables = purchases
      .filter((purchase) =>
        Number(purchase.remaining_amount || 0) > 0 &&
        String(purchase.status) !== 'cancelled'
      )
      .sort((a, b) => {
        const dueA = a.due_date || '9999-12-31';
        const dueB = b.due_date || '9999-12-31';
        if (dueA !== dueB) return dueA.localeCompare(dueB);
        return Number(b.id) - Number(a.id);
      });

    if ($('supplierPayablesList')) {
      $('supplierPayablesList').innerHTML = payables.length
        ? payables.map((purchase) => {
            const overdue = purchase.due_date && purchase.due_date < today;
            const dueToday = purchase.due_date === today;
            const badge = overdue
              ? '<span class="receivable-state receivable-overdue">En retard</span>'
              : dueToday
                ? '<span class="receivable-state receivable-today">Aujourd’hui</span>'
                : '<span class="receivable-state receivable-upcoming">À venir</span>';

            return `
              <article class="receivable-row">
                <div class="receivable-main">
                  <div class="receivable-title">
                    <strong>${esc(supplierName(purchase.supplier_id))}</strong>
                    ${badge}
                  </div>
                  <span>Achat #${purchase.id} · échéance ${esc(fmtDueDate(purchase.due_date))}</span>
                  <small>Total ${money(purchase.total_amount)} · payé ${money(purchase.paid_amount)}</small>
                </div>
                <div class="receivable-end">
                  <strong>${money(purchase.remaining_amount)}</strong>
                  ${can('supplier_payment.create')
                    ? '<button type="button" class="primary receivable-pay-btn" data-supplier-pay="' + purchase.id + '">Payer</button>'
                    : ''}
                </div>
              </article>
            `;
          }).join('')
        : '<p class="muted empty-state">Aucune dette fournisseur ouverte.</p>';
    }
  }

  async function showPurchasePayments(purchaseId) {
    if (!can('purchase.read') || !purchases.some(p => Number(p.id) === Number(purchaseId))) return;
    const before = await ready();
    const generation = loadGeneration;
    const target = $('purchasePayments-' + purchaseId);
    if (!target || !same(before)) return;
    target.textContent = 'Chargement des règlements…';
    try {
      const payments = await api('/pwa/purchases/' + purchaseId + '/payments', {cache:'no-store'});
      if (!same(before) || generation !== loadGeneration) return;
      target.innerHTML = payments.length ? payments.slice().sort((a, b) =>
        String(a.paid_at).localeCompare(String(b.paid_at)) || Number(a.id) - Number(b.id)
      ).map(payment => `<small>${esc(fmtSaleDate(payment.paid_at))} · ${money(payment.amount)} · ${esc(payment.channel)}</small>`).join('')
        : '<small>Aucun règlement enregistré.</small>';
    } catch (error) {
      if (same(before) && generation === loadGeneration) target.textContent = 'Règlements indisponibles. Réessaie.';
    }
  }

  async function loadPurchasingData() {
    const before = await ready();
    if (!before?.token || !before.shop) return;
    const requestId = ++loadGeneration;
    loadingPurchasingData = true;
    try {
      const results = await Promise.all([
        can('supplier.read') ? api('/pwa/suppliers', {cache:'no-store'}) : Promise.resolve([]),
        can('purchase.read') ? api('/pwa/purchases', {cache:'no-store'}) : Promise.resolve([]),
      ]);
      if (!same(before) || requestId !== loadGeneration) return;
      suppliers = results[0] || []; purchases = results[1] || [];
      loadedShopId = before.shop;
      syncPurchaseSelectors(); syncPurchaseDetailsVisibility();
      renderSupplierWorkspace(); renderSupplierDebtDashboard(); renderPurchases(); renderPurchaseCart(); freeze();
    } catch (error) {
      if (same(before)) status('Achats indisponibles. Utilise « Actualiser les achats ».');
      throw error;
    } finally { if (requestId === loadGeneration) loadingPurchasingData = false; }
  }
  async function addSupplier(inline) {
    if (!can('supplier.create') || writing || pending.purchase) return;
    const nameField = inline ? 'purchaseQuickSupplierName' : 'supplierName';
    const phoneField = inline ? 'purchaseQuickSupplierPhone' : 'supplierPhone';
    if (!$(nameField).value.trim() && !pending.supplier) return status('Renseigne le nom du fournisseur.');
    const result = await write('supplier', '/pwa/suppliers', () => ({name:$(nameField).value.trim(), phone:$(phoneField).value.trim() || null, debt:0}));
    if (!result) return;
    suppliers = [...suppliers.filter(s => s.id !== result.id), result];
    syncPurchaseSelectors();
    if (inline) $('purchaseSupplier').value = String(result.id);
    $(nameField).value = ''; $(phoneField).value = '';
    renderSupplierWorkspace(); persist(); status('Fournisseur ajouté. Tu peux poursuivre l’achat.');
  }
  $('supplierForm')?.addEventListener('submit', async event => { event.preventDefault(); await addSupplier(false); });
  $('purchaseQuickSupplierBtn')?.addEventListener('click', () => addSupplier(true));

  $('purchaseSupplier')?.addEventListener('change', onPurchaseSupplierChanged);

  $('purchaseAddLineBtn')?.addEventListener('click', () => {
    if (writing || pending.purchase) return;
    const productId = Number($('purchaseProduct').value);
    const product = state.products.find((item) => Number(item.id) === productId);
    const quantity = Number($('purchaseQty').value);
    const unitCost = Number($('purchaseUnitCost').value);

    if (!product) return toast('Choisis un produit.');
    if (!Number.isInteger(quantity) || quantity <= 0) return toast('Quantité invalide.');
    if (!Number.isInteger(unitCost) || unitCost < 0) return toast('Coût unitaire invalide.');

    purchaseCart.set(product.id, {
      product,
      quantity,
      unit_cost: unitCost,
    });

    $('purchaseQty').value = '1';
    $('purchaseUnitCost').value = String(product.purchase_price || 0);
    renderPurchaseCart(); persist();
  });

  $('purchaseProduct')?.addEventListener('change', () => {
    const product = state.products.find(
      (item) => Number(item.id) === Number($('purchaseProduct').value)
    );
    if (product) $('purchaseUnitCost').value = String(product.purchase_price || 0);
  });

  document.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-purchase-remove]');
    if (remove) {
      if (writing || pending.purchase) return;
      purchaseCart.delete(Number(remove.dataset.purchaseRemove));
      renderPurchaseCart(); persist();
      return;
    }

    const due = event.target.closest('[data-purchase-due-days]');
    if (due) {
      if (writing || pending.purchase) return;
      setPurchaseDueDays(due.dataset.purchaseDueDays); persist();
      return;
    }

    const debt = event.target.closest('[data-supplier-debt]');
    if (debt) {
      openSupplierDebtPayment(Number(debt.dataset.supplierDebt));
      return;
    }

    const pay = event.target.closest('[data-supplier-pay]');
    if (pay) {
      openSupplierPayment(Number(pay.dataset.supplierPay));
    }
  });

  $('purchaseSubmitBtn')?.addEventListener('click', async () => {
    if (writing || !can('purchase.create')) return;
    if (!pending.purchase) {
      if (!purchaseCart.size) return status('Ajoute au moins un produit.');
      const paid = Number($('purchasePaidAmount').value || 0), remaining = purchaseTotal() - paid;
      if (!Number.isInteger(paid) || paid < 0 || remaining < 0) return status('Montant payé invalide.');
      if (remaining > 0 && !$('purchaseSupplier').value) return status('Choisis ou crée un fournisseur pour cet achat avec dette.');
      if (remaining > 0 && !$('purchaseDueDate').value) return status('Choisis une échéance pour la dette fournisseur.');
    }
    const result = await write('purchase', '/pwa/purchases', () => ({
      supplier_id:Number($('purchaseSupplier').value) || null,
      items:[...purchaseCart.values()].map(line => ({product_id:line.product.id, quantity:line.quantity, unit_cost:line.unit_cost})),
      paid_amount:Number($('purchasePaidAmount').value || 0),
      payment_channel:$('purchasePaymentChannel').value || 'cash',
      paid_at:new Date().toISOString(),
      due_date:purchaseTotal() > Number($('purchasePaidAmount').value || 0) ? $('purchaseDueDate').value : null,
      original_amount:purchaseTotal(), original_currency:state.currencyContext?.shop_currency || 'XOF', exchange_rate:null,
    }));
    if (!result) return;
    purchaseCart.clear(); $('purchasePaidAmount').value = '0'; $('purchaseDueDate').value = '';
    renderPurchaseCart(); persist(); status('Achat #' + result.id + ' enregistré. Stock mis à jour.');
    await refreshAfterWrite(true);
  });

  function openSupplierDebtPayment(supplierId) {
    const supplier = suppliers.find(
      (item) => Number(item.id) === Number(supplierId)
    );
    const openPurchases = purchases
      .filter((purchase) =>
        Number(purchase.supplier_id) === Number(supplierId) &&
        Number(purchase.remaining_amount || 0) > 0 &&
        String(purchase.status) !== 'cancelled'
      )
      .sort((a, b) => {
        const dueA = a.due_date || '9999-12-31';
        const dueB = b.due_date || '9999-12-31';
        if (dueA !== dueB) return dueA.localeCompare(dueB);
        return Number(a.id) - Number(b.id);
      });

    if (!openPurchases.length) {
      toast('Aucune dette ouverte pour ce fournisseur.');
      return;
    }

    showTab('purchases');
    openSupplierPayment(openPurchases[0].id);

    if (openPurchases.length > 1) {
      toast(
        (supplier?.name || 'Fournisseur') +
        ' a ' + openPurchases.length +
        ' achats non soldés. Le paiement commence par le plus ancien.'
      );
    }
  }

  function openSupplierPayment(purchaseId) {
    if (writing) return;
    if (pending.payment) {
      $('supplierPaymentSheet').hidden = false;
      return status('Vérifie d’abord le résultat du règlement en attente avec la même confirmation.');
    }
    const purchase = purchases.find((item) => Number(item.id) === Number(purchaseId));
    if (!purchase) return toast('Achat introuvable.');

    selectedPayablePurchaseId = purchase.id;
    $('supplierPaymentTitle').textContent = 'Paiement · ' + supplierName(purchase.supplier_id);
    $('supplierPaymentMeta').textContent =
      'Achat #' + purchase.id + ' · reste ' + money(purchase.remaining_amount) +
      ' · échéance ' + fmtDueDate(purchase.due_date) +
      ' · paiement partiel possible';
    $('supplierPaymentAmount').value = String(purchase.remaining_amount);
    $('supplierPaymentAmount').max = String(purchase.remaining_amount);
    $('supplierPaymentReference').value = '';
    $('supplierPaymentDate').value = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0,16);
    $('supplierPaymentSheet').hidden = false;
  }

  function closeSupplierPayment() {
    $('supplierPaymentSheet').hidden = true;
    if (!pending.payment) selectedPayablePurchaseId = null;
    persist();
  }

  $('supplierPaymentCloseBtn')?.addEventListener('click', closeSupplierPayment);

  $('supplierPaymentSubmitBtn')?.addEventListener('click', async () => {
    if (writing || !can('supplier_payment.create')) return;
    const purchase = purchases.find(p => Number(p.id) === Number(selectedPayablePurchaseId));
    const amount = Number($('supplierPaymentAmount').value);
    if (!pending.payment) {
      if (!purchase) return status('Achat introuvable.');
      if (!Number.isInteger(amount) || amount <= 0 || amount > purchase.remaining_amount) return status('Montant invalide ou supérieur au reste dû.');
      if (!$('supplierPaymentDate').value || !Number.isFinite(Date.parse($('supplierPaymentDate').value))) return status('Renseigne la date réelle du paiement.');
    }
    const result = await write('payment', '/pwa/supplier-payments', () => ({
      purchase_id:purchase.id, supplier_id:purchase.supplier_id, amount,
      channel:$('supplierPaymentChannel').value || 'cash',
      reference:$('supplierPaymentReference').value.trim() || null,
      paid_at:new Date($('supplierPaymentDate').value).toISOString(),
    }));
    if (!result) return;
    closeSupplierPayment(); persist(); status('Règlement #' + result.id + ' enregistré.');
    await refreshAfterWrite(false);
  });

  const originalRender = render;
  render = function() {
    checkContext();
    originalRender();
    syncPurchaseSelectors();
    renderSupplierWorkspace();
    renderSupplierDebtDashboard();
    renderPurchases();
    renderPurchaseCart();

    const currentShopId = state.merchant?.shop_id ?? null;
    if (
      token &&
      state.merchant &&
      currentShopId !== loadedShopId &&
      !loadingPurchasingData
    ) {
      void loadPurchasingData().catch(() => {});
    }
  };

  document.addEventListener('click', (event) => {
    const payments = event.target.closest('[data-purchase-payments]');
    if (payments) void showPurchasePayments(Number(payments.dataset.purchasePayments));
    const tab = event.target.closest('[data-open-tab]');
    if (tab && (tab.dataset.openTab === 'suppliers' || tab.dataset.openTab === 'purchases')) {
      void loadPurchasingData().catch(() => {});
    }
  });

  syncPurchaseDetailsVisibility();
  void loadPurchasingData().catch(() => {});
})();