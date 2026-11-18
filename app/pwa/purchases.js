(() => {
  // A network-first worker may deliver this script to a cached older document.
  // Do not partially bind the new workflow or send from incompatible markup.
  if (!$('purchasePaymentMode')) {
    const message = 'Une nouvelle version du parcours achat est disponible. Actualise pour continuer ; ton achat en attente est conservé.';
    if ($('purchaseValidationMessage')) $('purchaseValidationMessage').textContent = message;
    else toast(message);
    if ($('purchaseSubmitBtn')) {
      $('purchaseSubmitBtn').textContent = 'Actualiser le parcours achat';
      $('purchaseSubmitBtn').addEventListener('click', () => location.reload());
    }
    return;
  }
  const purchaseCart = new Map();
  let suppliers = [];
  let purchases = [];
  let selectedPayablePurchaseId = null;
  let loadedShopId = null;
  let loadingPurchasingData = false;
  let supplierLoadState = 'idle';
  let supplierLoadId = 0;
  let supplierContext = null;
  let supplierCreationContext = null;
  let creatingSupplier = false;
  let creatingProduct = false;
  let catalogRequest = 0;
  let restoredSupplier = '';
  let restoredProduct = '';
  let draftBlocked = false;
  const businessError = error => {
    if (!error.status) return 'Connexion interrompue ou réponse non confirmée. Ton brouillon est conservé. Reprends l’achat en attente pour vérifier son enregistrement.';
    if (error.status === 422) return 'Vérifie les quantités et montants entiers, le produit et l’échéance. Si le problème persiste, actualise l’application.';
    if (error.status === 401) return 'Reconnecte-toi puis reprends cet achat dans la même boutique. Ton brouillon est conservé.';
    if (error.status === 403) return 'Ton rôle ne permet pas cette action dans cette boutique.';
    if (error.status >= 500) return 'Le serveur n’a pas confirmé l’achat. Reprends l’achat en attente sans en créer un autre.';
    return error.message || 'Impossible de confirmer cet achat. Ton brouillon est conservé.';
  };
  const draftKey = () => 'whatzabi:purchase:draft:v2:' + state.merchant?.id + ':' + state.merchant?.user_id + ':' + state.merchant?.shop_id;
  const draftFields = ['purchaseNewProductName', 'purchaseNewProductUnit', 'purchaseNewProductCost', 'purchasePaymentMode', 'purchasePaidAmount', 'purchasePaymentChannel', 'purchaseDueDate', 'purchaseQty', 'purchaseUnitCost', 'purchaseProductSearch'];
  function saveDraft() {
    if (!token || !state.merchant?.shop_id || draftBlocked) return;
    try {
      localStorage.setItem(draftKey(), JSON.stringify({
        selectedProduct: $('purchaseProduct')?.value || restoredProduct, editorOpen: !$('purchaseProductEditor').hidden, newProductOpen: !$('purchaseNewProduct').hidden, lines: [...purchaseCart.values()], supplier: $('purchaseSupplier')?.value || restoredSupplier,
        fields: Object.fromEntries(draftFields.map(id => [id, $(id)?.value || ''])),
      }));
    } catch (_) {
      draftBlocked = true;
      purchaseMessage('Le navigateur ne peut pas conserver le brouillon. Libère de l’espace puis recharge avant d’enregistrer.');
    }
  }
  function restoreDraft() {
    draftBlocked = false;
    if (!token || !state.merchant?.shop_id) return;
    try {
      const raw = localStorage.getItem(draftKey());
      const draft = raw ? JSON.parse(raw) : null;
      if (draft) {
        if (!Array.isArray(draft.lines)) throw new Error('draft');
        for (const line of draft.lines) purchaseCart.set(line.product.id, line);
        for (const id of draftFields) if ($(id) && draft.fields?.[id] !== undefined) $(id).value = draft.fields[id];
        restoredSupplier = draft.supplier || '';
        restoredProduct = draft.selectedProduct || '';
        $('purchaseProductEditor').hidden = !draft.editorOpen;
        $('purchaseNewProduct').hidden = !draft.newProductOpen;
      }
      // Upgrade/reload also recovers the immutable Lot 6.1 pending payload.
      const pending = readPendingPurchase(purchaseStorageKey());
      if (pending) {
        purchaseCart.clear();
        for (const line of pending.payload.items) {
          const product = state.products.find(p => p.id === line.product_id) || {id:line.product_id, name:'Produit #' + line.product_id, unit:'unité'};
          purchaseCart.set(product.id, {product, quantity:line.quantity, unit_cost:line.unit_cost});
        }
        restoredSupplier = String(pending.payload.supplier_id || '');
        $('purchasePaidAmount').value = String(pending.payload.paid_amount);
        $('purchasePaymentMode').value = pending.payload.paid_amount === purchaseTotal() ? 'paid' : pending.payload.paid_amount === 0 ? 'credit' : 'partial';
        $('purchaseDueDate').value = pending.payload.due_date || '';
        $('purchasePaymentChannel').value = pending.payload.payment_channel;
        purchaseMessage('Un achat attend confirmation. Reprends-le avec le bouton ci-dessous.');
      }
    } catch (_) {
      draftBlocked = true;
      purchaseMessage('Brouillon ou achat en attente illisible. Contacte le support avant de recommencer.');
    }
  }
  function updatePayment() {
    const total = purchaseTotal();
    const mode = $('purchasePaymentMode')?.value || 'partial';
    if (mode === 'paid') $('purchasePaidAmount').value = String(total);
    if (mode === 'credit') $('purchasePaidAmount').value = '0';
    if ($('purchasePaidAmount')) $('purchasePaidAmount').readOnly = mode !== 'partial';
    const remaining = total - Number($('purchasePaidAmount')?.value || 0);
    $('purchasePaymentChannel').closest('label').hidden=Number($('purchasePaidAmount').value)<=0;
    if ($('purchaseRemaining')) $('purchaseRemaining').textContent = money(Math.max(0, remaining));
    if ($('purchaseDueWrap')) $('purchaseDueWrap').hidden = remaining <= 0;
    if ($('purchaseDueDate')) $('purchaseDueDate').required = remaining > 0;
    if ($('purchaseSupplier')) $('purchaseSupplier').required = remaining > 0;
    if ($('purchaseSupplierRequirement')) $('purchaseSupplierRequirement').textContent = remaining > 0 ? '(obligatoire pour le reste à payer)' : '(facultatif si tout est payé)';
  }
  async function loadPurchaseProducts() {
    if (!can('product.read')) return;
    const before = currentContext(), request = ++catalogRequest;
    $('purchaseCatalogStatus').textContent = 'Chargement des produits…';
    try {
      const products = await api('/pwa/products', {cache:'no-store'});
      if (before !== currentContext() || request !== catalogRequest) return;
      state.products = Array.isArray(products) ? products : [];
      syncPurchaseSelectors();
      $('purchaseCatalogStatus').textContent = state.products.length ? '' : 'Aucun produit. Crée un produit absent du catalogue.';
    } catch (_) {
      if (before !== currentContext() || request !== catalogRequest) return;
      $('purchaseCatalogStatus').textContent = 'Catalogue indisponible. Les produits déjà chargés restent utilisables. Actualise les produits pour réessayer.';
    }
  }

  const currentContext = () => JSON.stringify([token, state.merchant?.id, state.merchant?.shop_id]);
  const purchaseMessage = message => {
    if ($('purchaseValidationMessage')) $('purchaseValidationMessage').textContent = message;
    else if (message) toast(message); // An already-open page may still have the old HTML.
  };
  const supplierMessage = message => {
    if ($('supplierCreateStatus')) $('supplierCreateStatus').textContent = message;
  };
  function supplierBusy(busy) {
    for (const id of ['supplierSubmitBtn', 'purchaseSupplierBackBtn']) {
      if ($(id)) $(id).disabled = busy;
    }
  }

  function resetSupplierGuide() {
    supplierCreationContext = null;
    if ($('purchaseSupplierBackBtn')) $('purchaseSupplierBackBtn').hidden = true;
  }

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
    purchaseMessage('');
    input.removeAttribute('aria-invalid');
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
      const selected = restoredSupplier || supplierSelect.value;
      supplierSelect.innerHTML =
        '<option value="">Sans fournisseur</option>' +
        suppliers
          .map((supplier) =>
            '<option value="' + supplier.id + '">' + esc(supplier.name) + '</option>'
          )
          .join('');
      if ([...supplierSelect.options].some((option) => option.value === selected)) {
        supplierSelect.value = selected;
        restoredSupplier = '';
      }
    }

    if (productSelect) {
      const selected = restoredProduct || productSelect.value;
      productSelect.innerHTML =
        '<option value="">Choisir un produit</option>' +
        state.products
          .filter(product => product.name.toLocaleLowerCase().includes(($('purchaseProductSearch')?.value || '').trim().toLocaleLowerCase()))
          .map((product) =>
            '<option value="' + product.id + '">' +
            esc(product.name) + ' · stock ' + Number(product.stock || 0) +
            '</option>'
          )
          .join('');
      if ([...productSelect.options].some((option) => option.value === selected)) {
        productSelect.value = selected;
        restoredProduct = '';
      }
    }
  }

  function syncPurchaseDetailsVisibility() {
    if ($('purchaseDetails')) $('purchaseDetails').hidden = false;
    if ($('purchaseSupplier')) $('purchaseSupplier').disabled = supplierLoadState !== 'ready' || !can('supplier.read');
    if ($('purchaseCreateSupplierBtn')) $('purchaseCreateSupplierBtn').hidden = !can('supplier.create');
    if ($('purchaseCreateProductBtn')) $('purchaseCreateProductBtn').hidden = !can('product.create');
    if ($('purchaseOpenProductsBtn')) $('purchaseOpenProductsBtn').disabled = !can('purchase.create');
    if ($('purchaseRefreshSuppliersBtn')) $('purchaseRefreshSuppliersBtn').disabled = loadingPurchasingData || !can('supplier.read');
    const hint = $('purchaseSupplierHint');
    if (hint) {
      hint.hidden = false;
      hint.textContent = !can('supplier.read') ? 'Ton rôle ne permet pas de consulter les fournisseurs. Le comptant sans fournisseur reste possible.'
        : supplierLoadState === 'error' ? 'Fournisseurs indisponibles. Actualise la liste pour un achat avec fournisseur. Le comptant sans fournisseur reste possible.'
        : supplierLoadState !== 'ready' ? 'Chargement des fournisseurs… Tu peux déjà ajouter tes produits.'
        : !suppliers.length ? 'Aucun fournisseur enregistré. Facultatif si tout est payé ; sinon ajoute un fournisseur ou contacte un responsable, puis actualise.'
        : 'Facultatif si tout est payé. Fournisseur et échéance obligatoires pour un reste à payer.';
    }
  }

  function onPurchaseSupplierChanged() {
    restoredSupplier = '';
    saveDraft();
    syncPurchaseDetailsVisibility();
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
                <span>${line.quantity} ${esc(line.product.unit || "unité")} × ${money(line.unit_cost)}</span>
              </div>
              <div class="purchase-line-end">
                <strong>${money(lineTotal)}</strong>
                <button type="button" class="ghost" data-purchase-remove="${line.product.id}">Retirer</button>
              </div>
            </article>
          `;
        }).join('')
      : '<p class="muted empty-state">Ton panier est vide. Commence par « Ajouter un produit ».</p>';

    $('purchaseTotal').textContent = money(purchaseTotal());

    if ($('purchasePaidAmount')) $('purchasePaidAmount').max = String(purchaseTotal());
    updatePayment();
  }

  function supplierName(id) {
    if (!id) return 'Sans fournisseur';
    return suppliers.find((supplier) => Number(supplier.id) === Number(id))?.name || 'Fournisseur';
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
        purchases.filter(p=>p.status!=='cancelled').reduce((sum,p)=>sum+Number(p.remaining_amount||0),0)
      );
    }

    if ($('supplierCreateCard')) {
      $('supplierCreateCard').hidden = !can('supplier.create');
    }

    if ($('supplierList')) {
      $('supplierList').innerHTML = suppliers.length
        ? suppliers.map((supplier) => {
            const debt=purchases.filter(p=>p.supplier_id===supplier.id && p.status!=='cancelled').reduce((n,p)=>n+Number(p.remaining_amount||0),0);
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
        ? purchases.map((purchase) => `
            <article class="purchase-history-row">
              <div>
                <strong>${esc(supplierName(purchase.supplier_id))}</strong>
                <span>Achat #${purchase.id} · ${esc(purchaseStatusLabel(purchase.status))}</span>
                <small>${purchase.created_at ? esc(fmtSaleDate(purchase.created_at)) : ''}</small>
              </div>
              <div class="purchase-line-end">
                <strong>${operationMoney(purchase.total_amount,purchase.currency_code)}</strong>
                <small>Reste ${operationMoney(purchase.remaining_amount,purchase.currency_code)}</small>
                <button type="button" data-purchase-receipt="${purchase.id}">Consulter le reçu</button>
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
                  <small>Total ${operationMoney(purchase.total_amount,purchase.currency_code)} · payé ${operationMoney(purchase.paid_amount,purchase.currency_code)}</small>
                </div>
                <div class="receivable-end">
                  <strong>${operationMoney(purchase.remaining_amount,purchase.currency_code)}</strong>
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

  async function loadPurchasingData() {
    if (!token) return false;
    const before = currentContext();
    const requestId = ++supplierLoadId;
    loadingPurchasingData = true;
    supplierLoadState = 'loading';
    syncPurchaseDetailsVisibility();
    try {
      const results = await Promise.allSettled([
        can('supplier.read') ? api('/pwa/suppliers', {cache:'no-store'}) : Promise.resolve([]),
        can('purchase.read') ? api('/pwa/purchases') : Promise.resolve([]),
      ]);
      if (requestId !== supplierLoadId || before !== currentContext()) return false;
      if (results[0].status === 'rejected') throw results[0].reason;
      suppliers = results[0].value || [];
      if (results[1].status === 'fulfilled') purchases = results[1].value || [];
      else toast('Fournisseurs actualisés. Historique des achats indisponible.');
      loadedShopId = state.merchant?.shop_id ?? null;
      supplierLoadState = 'ready';
      syncPurchaseSelectors();
      renderSupplierWorkspace();
      renderSupplierDebtDashboard();
      renderPurchases();
      renderPurchaseCart();
      return true;
    } catch (error) {
      if (requestId !== supplierLoadId || before !== currentContext()) return false;
      supplierLoadState = 'error';
      toast(error.message || 'Impossible de charger les achats.');
      return false;
    } finally {
      if (requestId === supplierLoadId) {
        loadingPurchasingData = false;
        syncPurchaseDetailsVisibility();
        renderPendingPurchase();
      }
    }
  }

  // UX backport on the Railway purchase contract: opening only performs reads.
  function openPurchaseForm() {
    if (!can('purchase.create')) return toast('Ton rôle ne permet pas de créer un achat.');
    if (!token || !state.merchant?.shop_id) return toast('Sélectionne une boutique et reconnecte-toi.');
    const before = currentContext();
    showTab('purchases');
    requestAnimationFrame(() => {
      if (before !== currentContext() || !$('purchases')?.classList.contains('active')) return;
      $('purchaseFormTitle')?.focus({preventScroll:true});
      $('purchaseFormTitle')?.scrollIntoView({behavior:'smooth', block:'start'});
    });
    if (!loadingPurchasingData) void loadPurchasingData();
    void loadPurchaseProducts();
  }
  $('quickAddPurchase')?.addEventListener('click', openPurchaseForm);

  $('purchaseRefreshSuppliersBtn')?.addEventListener('click', () => loadPurchasingData());

  $('purchaseCreateSupplierBtn')?.addEventListener('click', () => {
    if (!can('supplier.create')) return toast('Permission insuffisante.');
    saveDraft();
    supplierCreationContext = currentContext();
    supplierMessage('Crée le fournisseur pour revenir à ton achat. Ton panier est conservé.');
    $('purchaseSupplierBackBtn').hidden = false;
    showTab('suppliers');
    $('supplierName').focus();
  });

  $('purchaseSupplierBackBtn')?.addEventListener('click', () => {
    if (creatingSupplier) return;
    resetSupplierGuide();
    showTab('purchases');
  });

  $('supplierForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!can('supplier.create')) return toast('Permission insuffisante.');
    if (creatingSupplier) return;
    if (!$('supplierName').value.trim()) {
      supplierMessage('Renseigne le nom du fournisseur.');
      return $('supplierName').focus();
    }
    const before = currentContext();
    const guided = supplierCreationContext === before;
    creatingSupplier = true;
    supplierBusy(true);
    supplierMessage('Création du fournisseur…');
    try {
      const supplier = await api('/pwa/suppliers', {
        method: 'POST',
        body: JSON.stringify({
          name: $('supplierName').value.trim(),
          phone: $('supplierPhone').value.trim() || null,
          debt: 0,
        }),
      });
      if (before !== currentContext()) return;
      event.target.reset();
      // A confirmed creation is not a failed write if the subsequent read fails.
      supplierMessage('Fournisseur ajouté.');
      const loaded = await loadPurchasingData();
      if (before !== currentContext()) return;
      if (guided && supplierCreationContext === before) {
        resetSupplierGuide();
        showTab('purchases');
        const selectable = loaded && suppliers.some(item => item.id === supplier.id);
        $('purchaseSupplier').value = selectable ? String(supplier.id) : '';
        syncPurchaseDetailsVisibility();
        if (selectable) onPurchaseSupplierChanged();
        if (before !== currentContext()) return;
        purchaseMessage(selectable
          ? 'Fournisseur ajouté. Poursuis ton achat.'
          : 'Fournisseur ajouté. Actualise les fournisseurs pour le sélectionner ; ne le recrée pas.');
      }
      toast('Fournisseur ajouté.');
    } catch (error) {
      if (before !== currentContext()) return;
      supplierMessage(error.status
        ? error.message
        : 'Création non confirmée. Actualise la liste avant de réessayer.');
      toast(error.message);
    } finally {
      creatingSupplier = false;
      supplierBusy(false);
    }
  });

  $('purchaseSupplier')?.addEventListener('change', onPurchaseSupplierChanged);

  $('purchaseAddLineBtn')?.addEventListener('click', () => {
    if (!can('purchase.create')) return;
    if (hasPendingPurchase()) return purchaseMessage('Reprends d’abord l’achat en attente.');
    const productId = Number($('purchaseProduct').value);
    const product = state.products.find((item) => Number(item.id) === productId);
    const quantity = Number($('purchaseQty').value);
    const unitCost = Number($('purchaseUnitCost').value);

    if (!product) return toast('Choisis un produit.');
    if (!Number.isSafeInteger(quantity) || quantity <= 0) return purchaseMessage('Saisis une quantité entière supérieure à zéro.');
    if (!Number.isSafeInteger(unitCost) || unitCost < 0) return purchaseMessage('Saisis un prix d’achat entier, positif ou nul.');

    const previous = purchaseCart.get(product.id);
    if (previous && previous.unit_cost !== unitCost) return purchaseMessage('Ce produit est déjà dans le panier avec un autre prix. Retire sa ligne pour modifier le prix.');
    purchaseCart.set(product.id, {
      product,
      quantity: quantity + (previous?.quantity || 0),
      unit_cost: unitCost,
    });

    $('purchaseQty').value = '1';
    $('purchaseUnitCost').value = String(product.purchase_price || 0);
    renderPurchaseCart();
    saveDraft();
    purchaseMessage('Produit ajouté au panier.');
  });

  $('purchaseProduct')?.addEventListener('change', () => {
    const product = state.products.find(
      (item) => Number(item.id) === Number($('purchaseProduct').value)
    );
    if (product) $('purchaseUnitCost').value = String(product.purchase_price || 0);
    if ($('purchaseUnit')) $('purchaseUnit').textContent = product?.unit || 'unité';
    saveDraft();
  });

  document.addEventListener('click', async (event) => {
    const receiptButton=event.target.closest('[data-purchase-receipt]');
    if(receiptButton){
      const before=currentContext(),id=Number(receiptButton.dataset.purchaseReceipt),purchase=purchases.find(p=>p.id===id);
      if(!purchase)return;
      try{const [items,payments]=await Promise.all([api('/pwa/purchases/'+id+'/items'),api('/pwa/purchases/'+id+'/payments')]);
        if(before!==currentContext())return;
        commercialReceipt('Achat reçu', {...purchase,items,payment_details:payments});$('commercialReceipt').scrollIntoView({block:'start'});
      }catch(e){if(before===currentContext())toast('Reçu indisponible : '+e.message);}return;
    }
    const remove = event.target.closest('[data-purchase-remove]');
    if (remove) {
      if (hasPendingPurchase()) return purchaseMessage('Reprends d’abord l’achat en attente.');
      purchaseCart.delete(Number(remove.dataset.purchaseRemove));
      renderPurchaseCart();
      saveDraft();
      return;
    }

    const due = event.target.closest('[data-purchase-due-days]');
    if (due) {
      if (hasPendingPurchase()) return;
      setPurchaseDueDays(due.dataset.purchaseDueDays);
      saveDraft();
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

  let submittingPurchase = false;
  const purchaseStorageKey = () => {
    if (!token || !state.merchant?.id || !state.merchant?.shop_id) throw new Error('Choisis une boutique.');
    return 'whatzabi:purchase:v2:' + state.merchant.id + ':' + state.merchant.shop_id;
  };
  function readPendingPurchase(key) {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const pending = JSON.parse(raw);
    if (!pending.key || !pending.payload) throw new Error('Achat en attente illisible. Contacte le support avant de recommencer.');
    return pending;
  }
  function hasPendingPurchase() {
    try { return Boolean(readPendingPurchase(purchaseStorageKey())); }
    catch (_) { return true; }
  }
  function validatePurchaseReceipt(receipt, payload) {
    // PurchaseRead has no echoed key, tenant or items. The scoped server journal
    // binds this POST's immutable key/payload to its receipt; verify all available
    // business fields, never infer a match by looking for a similar purchase.
    const total = payload.items.reduce((sum, line) => sum + (line.line_total ?? line.quantity * line.unit_cost), 0);
    const paid = payload.paid_amount ?? 0;
    const remaining = total - paid;
    const status = remaining === 0 ? 'paid' : paid === 0 ? 'credit' : 'partial';
    const sameRate = payload.exchange_rate == null
      ? receipt?.exchange_rate === null
      : receipt?.exchange_rate != null && Number.isFinite(Number(receipt.exchange_rate)) &&
        Number(receipt.exchange_rate) === Number(payload.exchange_rate);
    if (!receipt || Array.isArray(receipt) || typeof receipt !== 'object' ||
        !Number.isSafeInteger(receipt.id) || receipt.id <= 0 ||
        ![total, paid, remaining, receipt.total_amount, receipt.paid_amount, receipt.remaining_amount].every(Number.isSafeInteger) ||
        receipt.supplier_id !== (payload.supplier_id ?? null) ||
        receipt.total_amount !== total || receipt.paid_amount !== paid ||
        receipt.remaining_amount !== remaining || receipt.status !== status ||
        receipt.original_amount !== (payload.original_amount ?? total) ||
        receipt.original_currency !== (payload.original_currency || 'XOF').toUpperCase() ||
        receipt.due_date !== (payload.due_date ?? null) || !sameRate ||
        typeof receipt.created_at !== 'string' || !Number.isFinite(Date.parse(receipt.created_at))) {
      const error = new Error('Confirmation incertaine : reçu incomplet ou incohérent.');
      error.confirmationUncertain = true;
      throw error;
    }
    return receipt;
  }
  function renderPendingPurchase() {
    const button = $('purchaseRetryBtn');
    if (!button) return;
    let pending = false;
    try { pending = Boolean(readPendingPurchase(purchaseStorageKey())); button.hidden = !pending; }
    catch (_) { button.hidden = true; }
    button.disabled = submittingPurchase || draftBlocked || !can('purchase.create');
    if ($('purchaseSubmitBtn')) $('purchaseSubmitBtn').disabled = pending || draftBlocked || submittingPurchase || !can('purchase.create');
    if ($('purchaseSubmitBtn')) $('purchaseSubmitBtn').hidden = pending;
    for (const id of [...draftFields, 'purchaseSupplier', 'purchaseAddLineBtn', 'purchaseCreateSupplierBtn', 'purchaseProduct', 'purchaseOpenProductsBtn', 'purchaseCreateProductBtn']) {
      if ($(id)) $(id).disabled = pending || !can('purchase.create') || (id === 'purchaseSupplier' && (supplierLoadState !== 'ready' || !can('supplier.read')));
    }

  }
  async function sendPurchase(payload = null) {
    if (submittingPurchase || !can('purchase.create') || draftBlocked) return;
    submittingPurchase = true;
    const button = $('purchaseSubmitBtn');
    button.disabled = true;
    const before = currentContext();
    let operationKey = null, operationRaw = null, confirmedId = null;
    try {
      const storageKey = purchaseStorageKey();
      operationKey = storageKey;
      const submit = async () => {
        if (before !== currentContext()) throw new Error('La boutique a changé. Reprends l’achat dans sa boutique.');
        let pending = readPendingPurchase(storageKey);
        if (pending && payload && JSON.stringify(pending.payload) !== JSON.stringify(payload)) {
          throw new Error('Un achat attend confirmation. Utilise « Reprendre l’achat en attente » avant de créer un autre achat.');
        }
        if (!pending) {
          if (!payload) return;
          pending = {key: crypto.randomUUID(), payload, origin: {
            merchant_id: state.merchant.id, shop_id: state.merchant.shop_id, user_id: state.merchant.user_id
          }};
          // Fail closed if browser storage is unavailable. Never send an
          // operation whose identity cannot survive a lost response/reload.
          const serialized = JSON.stringify(pending);
          localStorage.setItem(storageKey, serialized);
          if (localStorage.getItem(storageKey) !== serialized) throw new Error('Conservation locale non vérifiée. Aucun achat envoyé.');
        }
        operationRaw = localStorage.getItem(storageKey);
        if (!operationRaw || JSON.stringify(JSON.parse(operationRaw)) !== JSON.stringify(pending)) {
          throw new Error('L’achat en attente a changé. Vérifie les autres onglets avant de reprendre.');
        }
        const originalDraftKey = draftKey();
        const originalDraft = localStorage.getItem(originalDraftKey);
        if (pending.origin && (Number(pending.origin.merchant_id) !== Number(state.merchant.id) ||
            Number(pending.origin.shop_id) !== Number(state.merchant.shop_id) ||
            Number(pending.origin.user_id || 0) !== Number(state.merchant.user_id || 0))) {
          throw sessionFailure('Cet achat appartient à un autre compte ou une autre boutique. Il est conservé.', 403);
        }
        renderPendingPurchase();
        const receipt = validatePurchaseReceipt(await api('/pwa/purchases', {
            method: 'POST',
            requireJsonResponse: true,
            body: JSON.stringify({...pending.payload, idempotency_key: pending.key}),
          }), pending.payload);
        confirmedId = receipt.id;
        // A late body belongs only to the context and operation that sent it.
        // Keep the original pending entry if the session expired or changed.
        if (before !== currentContext()) return;
        if (!sessionIsUnexpired()) {
          logout('Session expirée. Reconnecte-toi pour retrouver la confirmation de cet achat.');
          return;
        }
        if (localStorage.getItem(storageKey) !== operationRaw) {
          purchaseMessage('Achat #' + receipt.id + ' confirmé. Une autre opération locale est conservée ; vérifie les autres onglets.');
          return;
        }
        // Serialized under the existing Web Lock; never erase another tab's draft.
        const unchangedDraft = localStorage.getItem(originalDraftKey) === originalDraft;
        if (unchangedDraft && originalDraft !== null) localStorage.removeItem(originalDraftKey);
        localStorage.removeItem(storageKey);
        if (unchangedDraft) {
          purchaseCart.clear();
          $('purchasePaymentMode').value = 'paid';
          $('purchasePaidAmount').value = '0';
          $('purchaseDueDate').value = '';
          renderPurchaseCart();
        } else {
          purchaseCart.clear();
          restoreDraft();
          renderPurchaseCart();
        }
        purchaseMessage('Achat #' + receipt.id + ' enregistré. Stock mis à jour.');
        toast('Achat #' + receipt.id + ' enregistré. Stock mis à jour.');
        commercialReceipt('Achat reçu', {...receipt,channel:pending.payload.paid_amount>0?pending.payload.payment_channel:'aucun'});
        try { await refresh(); await loadPurchasingData(); }
        catch (_) { toast('Achat enregistré. Actualise pour voir les nouveaux totaux.'); }
      };
      // The browser lock also serializes two tabs sharing this shop outbox.
      if (globalThis.navigator?.locks) {
        await navigator.locks.request(storageKey, {ifAvailable: true}, async lock => {
          if (!lock) throw new Error('Un achat est déjà en cours dans un autre onglet.');
          await submit();
        });
      } else {
        throw new Error('Mets à jour ton navigateur pour enregistrer les achats en sécurité.');
      }
    } catch (error) {
      if (before !== currentContext()) return;
      let retained = false;
      try { retained = Boolean(operationRaw && localStorage.getItem(operationKey) === operationRaw); } catch (_) {}
      const message = confirmedId
        ? 'Achat #' + confirmedId + ' confirmé. Nettoyage local non terminé : ne crée pas un nouvel achat ; fais vérifier la reprise.'
        : retained
          ? (error.status ? businessError(error) : 'Confirmation incertaine. L’achat et sa clé sont conservés. Reprends le même achat pour obtenir son reçu.')
          : 'Conservation de l’achat non vérifiable. Ne ressaisis pas : conserve les informations affichées et demande un rapprochement en lecture seule.';
      purchaseMessage(message);
      if (retained && [400,422].includes(error.status)) {
        let correct = $('purchaseCorrectRefused');
        if (!correct) { correct=document.createElement('button');correct.id='purchaseCorrectRefused';correct.type='button';$('purchaseRetryBtn').after(correct); }
        correct.hidden=false;correct.textContent='Corriger l’achat refusé sans écriture';
        correct.onclick=()=>{ if(before===currentContext() && localStorage.getItem(operationKey)===operationRaw) {localStorage.setItem(operationKey+':refused:'+JSON.parse(operationRaw).key,operationRaw);localStorage.removeItem(operationKey);correct.hidden=true;renderPendingPurchase();purchaseMessage('Corrige puis confirme un nouvel envoi.');}};
      }
      toast(message);
    } finally {
      submittingPurchase = false;
      button.disabled = false;
      renderPendingPurchase();
    }
  }
  $('purchaseRetryBtn')?.addEventListener('click', () => sendPurchase());

  $('purchaseSubmitBtn')?.addEventListener('click', async () => {
    if (submittingPurchase) return;
    if (!can('purchase.create')) return toast('Permission insuffisante.');
    if (!purchaseCart.size) return purchaseMessage('Ajoute au moins un produit.');
    if (draftBlocked || hasPendingPurchase()) return purchaseMessage('Reprends d’abord l’achat en attente ou résous le problème de stockage.');

    const supplierId = Number($('purchaseSupplier').value) || null;

    const total = purchaseTotal();
    const paidAmount = Number($('purchasePaidAmount').value || 0);
    if (!Number.isSafeInteger(paidAmount) || paidAmount < 0 || paidAmount > total) {
      return purchaseMessage('Le montant payé doit être entier, entre zéro et le total de l’achat.');
    }

    const remaining = total - paidAmount;
    if (remaining > 0 && !supplierId) {
      purchaseMessage('Choisis ou crée un fournisseur pour le montant restant à payer.');
      $('purchaseSupplier').focus();
      return;
    }
    const dueDate = $('purchaseDueDate').value || null;
    if (remaining > 0 && !dueDate) {
      purchaseMessage('Il reste ' + money(remaining) + ' à payer. Choisis une échéance pour la dette fournisseur.');
      $('purchaseDueDate').setAttribute('aria-invalid', 'true');
      $('purchaseDueDate').focus();
      return;
    }
    purchaseMessage('');
    $('purchaseDueDate').removeAttribute('aria-invalid');
    const paymentEffectiveAt=paidAmount>0?new Date().toISOString():null;
    if (!await commercialConfirm('Confirmer l’achat reçu', {date:paymentEffectiveAt,total, paid:paidAmount, remaining, channel:paidAmount > 0 ? $('purchasePaymentChannel').value : 'aucun', lines:[...purchaseCart.values()].map(l=>l.quantity+' × '+l.product.name+' · '+money(l.unit_cost))})) return;

    await sendPurchase({
          supplier_id: supplierId,
          items: [...purchaseCart.values()].map((line) => ({
            product_id: line.product.id,
            quantity: line.quantity,
            unit_cost: line.unit_cost,
          })),
          paid_amount: paidAmount,
          payment_effective_at: paymentEffectiveAt,
          payment_channel: $('purchasePaymentChannel').value,
          due_date: remaining > 0 ? dueDate : null,
          original_amount: total,
          original_currency: state.currencyContext?.shop_currency || 'XOF',
          exchange_rate: null,
    });
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
    const purchase = purchases.find((item) => Number(item.id) === Number(purchaseId));
    if (!purchase) return toast('Achat introuvable.');

    selectedPayablePurchaseId = purchase.id;
    $('supplierPaymentTitle').textContent = 'Paiement · ' + supplierName(purchase.supplier_id);
    $('supplierPaymentMeta').textContent =
      'Achat #' + purchase.id + ' · reste ' + operationMoney(purchase.remaining_amount,purchase.currency_code) +
      ' · échéance ' + fmtDueDate(purchase.due_date) +
      ' · paiement partiel possible';
    $('supplierPaymentAmount').value = String(purchase.remaining_amount);
    $('supplierPaymentAmount').max = String(purchase.remaining_amount);
    $('supplierPaymentReference').value = '';
    $('supplierPaymentSheet').hidden = false;
    PaymentJournal.open('supplier', purchase.id);
  }

  function closeSupplierPayment() {
    $('supplierPaymentSheet').hidden = true;
    selectedPayablePurchaseId = null;
  }

  $('supplierPaymentCloseBtn')?.addEventListener('click', closeSupplierPayment);

  $('supplierPaymentSubmitBtn')?.addEventListener('click', async () => {
    const purchase = purchases.find(
      (item) => Number(item.id) === Number(selectedPayablePurchaseId)
    );
    if (!purchase) return toast('Achat introuvable.');

    const amount = Number($('supplierPaymentAmount').value);
    if (!Number.isFinite(amount) || amount <= 0) return toast('Montant invalide.');


    const button = $('supplierPaymentSubmitBtn');
    button.disabled = true;
    try {
      const confirmed = await PaymentJournal.send('supplier', {purchase_id:purchase.id,supplier_id:purchase.supplier_id,amount,
        channel:$('supplierPaymentChannel').value,reference:$('supplierPaymentReference').value.trim() || null});
      if (!confirmed) return;

      closeSupplierPayment();
      await loadPurchasingData();
      toast(
        amount === Number(purchase.remaining_amount || 0)
          ? 'Dette fournisseur soldée.'
          : 'Paiement fournisseur enregistré.'
      );
    } catch (error) {
      PaymentJournal.open('supplier', purchase.id);
      toast(error.message || 'Impossible d’enregistrer le paiement.');
    } finally {
      button.disabled = false;
    }
  });

  const originalRender = render;
  render = function() {
    if (supplierContext !== currentContext()) {
      supplierContext = currentContext();
      purchaseCart.clear();
      purchases = [];
      restoredSupplier = '';
      restoredProduct = '';
      catalogRequest++;
      $('purchaseSupplier').value = '';
      $('purchasePaymentMode').value = 'paid';
      $('purchasePaymentChannel').value = 'cash';
      $('purchaseProductSearch').value = '';
      $('purchaseQty').value = '1';
      $('purchaseUnitCost').value = '0';
      $('purchaseUnit').textContent = 'unité';
      $('purchaseCatalogStatus').textContent = '';
      $('purchaseProductEditor').hidden = true;
      $('purchaseOpenProductsBtn').setAttribute('aria-expanded', 'false');
      $('purchaseNewProduct').hidden = true;
      $('purchaseNewProductName').value = '';
      $('purchaseNewProductUnit').value = 'unité';
      $('purchaseNewProductCost').value = '0';
      $('purchaseNewProductStatus').textContent = '';
      $('supplierName').value = '';
      $('supplierPhone').value = '';
      if ($('purchasePaidAmount')) $('purchasePaidAmount').value = '0';
      if ($('purchaseDueDate')) $('purchaseDueDate').value = '';
      suppliers = [];
      supplierLoadState = 'idle';
      loadedShopId = null;
      loadingPurchasingData = false;
      supplierLoadId++;
      resetSupplierGuide();
      purchaseMessage('');
      restoreDraft();
    }
    originalRender();
    PaymentJournal.render();
    syncPurchaseSelectors();
    syncPurchaseDetailsVisibility();
    renderSupplierWorkspace();
    renderSupplierDebtDashboard();
    renderPurchases();
    renderPurchaseCart();
    renderPendingPurchase();
    if(state.finance)renderFinanceOverview(state.finance);

    const currentShopId = state.merchant?.shop_id ?? null;
    if (
      token &&
      state.merchant &&
      currentShopId !== loadedShopId &&
      !loadingPurchasingData
    ) {
      loadPurchasingData();
    }
  };

  document.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-open-tab]');
    if (tab && tab.dataset.openTab !== 'suppliers') resetSupplierGuide();
    if (tab && (tab.dataset.openTab === 'suppliers' || tab.dataset.openTab === 'purchases')) {
      loadPurchasingData();
    }
  });

  $('purchaseDueDate')?.addEventListener('input', () => {
    purchaseMessage('');
    $('purchaseDueDate').removeAttribute('aria-invalid');
  });

  $('purchaseOpenProductsBtn')?.addEventListener('click', () => {
    if (!can('purchase.create')) return;
    $('purchaseProductEditor').hidden = false;
    $('purchaseOpenProductsBtn').setAttribute('aria-expanded', 'true');
    $('purchaseProductSearch').focus();
    void loadPurchaseProducts();
  });
  $('purchaseRefreshProductsBtn')?.addEventListener('click', loadPurchaseProducts);
  $('purchaseProductSearch')?.addEventListener('input', () => { syncPurchaseSelectors(); saveDraft(); });
  $('purchaseCreateProductBtn')?.addEventListener('click', () => {
    if (!can('product.create')) return;
    $('purchaseNewProduct').hidden = false;
    $('purchaseNewProductName').value = $('purchaseProductSearch').value.trim();
    $('purchaseNewProductUnit').value = $('purchaseUnit').textContent || 'unité';
    $('purchaseNewProductCost').value = $('purchaseUnitCost').value;
    saveDraft();
    $('purchaseNewProductName').focus();
  });
  $('purchaseCancelProductBtn')?.addEventListener('click', () => { if (!creatingProduct) { $('purchaseNewProduct').hidden = true; saveDraft(); $('purchaseCreateProductBtn').focus(); } });
  $('purchaseSaveProductBtn')?.addEventListener('click', async () => {
    if (creatingProduct || !can('product.create')) return;
    const name = $('purchaseNewProductName').value.trim(), unit = $('purchaseNewProductUnit').value.trim();
    if (!name || !unit) { $('purchaseNewProductStatus').textContent = 'Renseigne le nom et l’unité du produit.'; return; }
    const cost = Number($('purchaseNewProductCost').value);
    if (!Number.isSafeInteger(cost) || cost < 0) { $('purchaseNewProductStatus').textContent = 'Saisis un prix d’achat entier, positif ou nul.'; return; }
    const before = currentContext();
    creatingProduct = true;
    $('purchaseSaveProductBtn').disabled = true;
    try {
      const product = await api('/pwa/products', {method:'POST', body:JSON.stringify({name, unit, stock:0, purchase_price:cost, price:0, threshold:0})});
      if (before !== currentContext()) return;
      state.products.push(product);
      $('purchaseProductSearch').value = '';
      syncPurchaseSelectors();
      $('purchaseProduct').value = String(product.id);
      $('purchaseUnit').textContent = product.unit;
      $('purchaseUnitCost').value = String(product.purchase_price || 0);
      $('purchaseNewProduct').hidden = true;
      $('purchaseNewProductStatus').textContent = '';
      $('purchaseCatalogStatus').textContent = 'Produit créé avec un stock nul. Coût conservé : ' + money(cost) + '. Vérifie puis ajoute-le au panier.';
      $('purchaseUnitCost').focus();
      saveDraft();
    } catch (error) {
      if (before !== currentContext()) return;
      $('purchaseNewProductStatus').textContent = error.status ? businessError(error) : 'Création non confirmée. Actualise les produits et recherche ce nom avant de le recréer.';
    } finally { creatingProduct = false; $('purchaseSaveProductBtn').disabled = false; }
  });
  for (const id of draftFields) $(id)?.addEventListener('input', () => { updatePayment(); saveDraft(); });
  $('purchasePaymentMode')?.addEventListener('change', () => { updatePayment(); saveDraft(); });

  supplierContext = currentContext();
  restoreDraft();
  syncPurchaseSelectors();
  renderPurchaseCart();
  renderPendingPurchase();
  syncPurchaseDetailsVisibility();
  loadPurchasingData();
})();
