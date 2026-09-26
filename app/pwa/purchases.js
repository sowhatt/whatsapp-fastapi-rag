(() => {
  const purchaseCart = new Map();
  let suppliers = [];
  let purchases = [];
  let selectedPayablePurchaseId = null;
  let loadedShopId = null;
  let loadingPurchasingData = false;

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
        '<option value="">Choisir un fournisseur</option>' +
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

    const total = purchaseTotal();
    const paidInput = $('purchasePaidAmount');
    if (paidInput) {
      paidInput.max = String(total);
      if (Number(paidInput.value || 0) > total) {
        paidInput.value = String(total);
      }
    }
  }

  function supplierName(id) {
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
        ? suppliers.map((supplier) => `
            <article class="item">
              <div class="item-main">
                <div class="item-title">${esc(supplier.name)}</div>
                <div class="item-meta">${esc(supplier.phone || 'Sans téléphone')}</div>
              </div>
              <div class="money">Dette ${money(supplier.debt)}</div>
            </article>
          `).join('')
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
                <small>Reste ${money(purchase.remaining_amount)}</small>
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

  async function loadPurchasingData() {
    if (!token || loadingPurchasingData) return;
    loadingPurchasingData = true;
    try {
      const results = await Promise.all([
        can('supplier.read') ? api('/pwa/suppliers') : Promise.resolve([]),
        can('purchase.read') ? api('/pwa/purchases') : Promise.resolve([]),
      ]);
      suppliers = results[0] || [];
      purchases = results[1] || [];
      loadedShopId = state.merchant?.shop_id ?? null;
      syncPurchaseSelectors();
      renderSupplierWorkspace();
      renderPurchases();
      renderPurchaseCart();
    } catch (error) {
      toast(error.message || 'Impossible de charger les achats.');
    } finally {
      loadingPurchasingData = false;
    }
  }

  $('supplierForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!can('supplier.create')) return toast('Permission insuffisante.');

    try {
      await api('/pwa/suppliers', {
        method: 'POST',
        body: JSON.stringify({
          name: $('supplierName').value.trim(),
          phone: $('supplierPhone').value.trim() || null,
          debt: 0,
        }),
      });
      event.target.reset();
      await loadPurchasingData();
      toast('Fournisseur ajouté.');
    } catch (error) {
      toast(error.message);
    }
  });

  $('purchaseAddLineBtn')?.addEventListener('click', () => {
    const productId = Number($('purchaseProduct').value);
    const product = state.products.find((item) => Number(item.id) === productId);
    const quantity = Number($('purchaseQty').value);
    const unitCost = Number($('purchaseUnitCost').value);

    if (!product) return toast('Choisis un produit.');
    if (!Number.isFinite(quantity) || quantity <= 0) return toast('Quantité invalide.');
    if (!Number.isFinite(unitCost) || unitCost < 0) return toast('Coût unitaire invalide.');

    purchaseCart.set(product.id, {
      product,
      quantity,
      unit_cost: unitCost,
    });

    $('purchaseQty').value = '1';
    $('purchaseUnitCost').value = String(product.purchase_price || 0);
    renderPurchaseCart();
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
      purchaseCart.delete(Number(remove.dataset.purchaseRemove));
      renderPurchaseCart();
      return;
    }

    const due = event.target.closest('[data-purchase-due-days]');
    if (due) {
      setPurchaseDueDays(due.dataset.purchaseDueDays);
      return;
    }

    const pay = event.target.closest('[data-supplier-pay]');
    if (pay) {
      openSupplierPayment(Number(pay.dataset.supplierPay));
    }
  });

  $('purchaseSubmitBtn')?.addEventListener('click', async () => {
    if (!can('purchase.create')) return toast('Permission insuffisante.');
    if (!purchaseCart.size) return toast('Ajoute au moins un produit.');

    const supplierId = Number($('purchaseSupplier').value);
    if (!supplierId) return toast('Choisis un fournisseur.');

    const total = purchaseTotal();
    const paidAmount = Number($('purchasePaidAmount').value || 0);
    if (!Number.isFinite(paidAmount) || paidAmount < 0 || paidAmount > total) {
      return toast('Montant payé invalide.');
    }

    const remaining = total - paidAmount;
    const dueDate = $('purchaseDueDate').value || null;
    if (remaining > 0 && !dueDate) {
      return toast('Choisis une échéance pour la dette fournisseur.');
    }

    const button = $('purchaseSubmitBtn');
    button.disabled = true;

    try {
      await api('/pwa/purchases', {
        method: 'POST',
        body: JSON.stringify({
          supplier_id: supplierId,
          items: [...purchaseCart.values()].map((line) => ({
            product_id: line.product.id,
            quantity: line.quantity,
            unit_cost: line.unit_cost,
          })),
          paid_amount: paidAmount,
          payment_channel: $('purchasePaymentChannel').value,
          due_date: remaining > 0 ? dueDate : null,
          original_amount: total,
          original_currency: state.currencyContext?.shop_currency || 'XOF',
          exchange_rate: null,
        }),
      });

      purchaseCart.clear();
      $('purchasePaidAmount').value = '0';
      $('purchaseDueDate').value = '';
      await refresh();
      await loadPurchasingData();
      toast('Achat enregistré. Stock mis à jour.');
    } catch (error) {
      toast(error.message || 'Impossible d’enregistrer l’achat.');
    } finally {
      button.disabled = false;
    }
  });

  function openSupplierPayment(purchaseId) {
    const purchase = purchases.find((item) => Number(item.id) === Number(purchaseId));
    if (!purchase) return toast('Achat introuvable.');

    selectedPayablePurchaseId = purchase.id;
    $('supplierPaymentTitle').textContent = 'Paiement · ' + supplierName(purchase.supplier_id);
    $('supplierPaymentMeta').textContent =
      'Achat #' + purchase.id + ' · reste ' + money(purchase.remaining_amount) +
      ' · échéance ' + fmtDueDate(purchase.due_date);
    $('supplierPaymentAmount').value = String(purchase.remaining_amount);
    $('supplierPaymentAmount').max = String(purchase.remaining_amount);
    $('supplierPaymentReference').value = '';
    $('supplierPaymentSheet').hidden = false;
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
    if (amount > Number(purchase.remaining_amount || 0)) {
      return toast('Le paiement dépasse le reste dû.');
    }

    const button = $('supplierPaymentSubmitBtn');
    button.disabled = true;
    try {
      await api('/pwa/supplier-payments', {
        method: 'POST',
        body: JSON.stringify({
          purchase_id: purchase.id,
          supplier_id: purchase.supplier_id,
          amount,
          channel: $('supplierPaymentChannel').value,
          reference: $('supplierPaymentReference').value.trim() || null,
        }),
      });

      closeSupplierPayment();
      await loadPurchasingData();
      toast(
        amount === Number(purchase.remaining_amount || 0)
          ? 'Dette fournisseur soldée.'
          : 'Paiement fournisseur enregistré.'
      );
    } catch (error) {
      toast(error.message || 'Impossible d’enregistrer le paiement.');
    } finally {
      button.disabled = false;
    }
  });

  const originalRender = render;
  render = function() {
    originalRender();
    syncPurchaseSelectors();
    renderSupplierWorkspace();
    renderPurchases();
    renderPurchaseCart();

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
    if (tab && (tab.dataset.openTab === 'suppliers' || tab.dataset.openTab === 'purchases')) {
      loadPurchasingData();
    }
  });

  loadPurchasingData();
})();