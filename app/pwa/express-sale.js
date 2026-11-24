(() => {
  const cart = new Map();
  let editingPriceId = null;
  let query = '';
  let frequentProductIds = [];
  let showAllFrequentProducts = false;
  let expressStep = 'products';

  const money = (n) => fmt(Number(n || 0));
  const total = () => [...cart.values()].reduce((sum, line) => sum + Number(line.unitPrice ?? line.product.price ?? 0) * line.quantity, 0);

  function isCreditMode() {
    const channel = $('expressChannel')?.value;
    return channel === 'credit' || channel === 'partial';
  }

  function setDueDateDays(days) {
    const input = $('expressDueDate');
    if (!input) return;
    const date = new Date();
    date.setDate(date.getDate() + Number(days || 0));
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, '0');
    const dd = String(date.getDate()).padStart(2, '0');
    input.value = yyyy + '-' + mm + '-' + dd;
  }

  function syncCreditFields() {
    const credit = isCreditMode();
    const wrap = $('expressCreditFields');
    const due = $('expressDueDate');
    const customer = $('expressCustomer');
    if (wrap) wrap.hidden = !credit;
    if (due) due.required = credit;
    if (customer) customer.required = credit;
    if (credit && due && !due.value) setDueDateDays(30);
  }

  function normalizeSearch(value) {
    return String(value || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLocaleLowerCase('fr')
      .trim();
  }

  function productSearchScore(product, q) {
    const name = normalizeSearch(product?.name);
    const brand = normalizeSearch(product?.brand);
    const variant = normalizeSearch(product?.variant);
    const packaging = normalizeSearch(product?.packaging);
    const haystack = [name, brand, variant, packaging].filter(Boolean).join(' ');

    if (!q) return 0;
    if (name === q) return 100;
    if (name.startsWith(q)) return 80;
    if (name.includes(q)) return 60;
    if (haystack.includes(q)) return 40;

    const tokens = q.split(/\s+/).filter(Boolean);
    const matched = tokens.filter((token) => haystack.includes(token)).length;
    return matched ? matched * 10 : 0;
  }

  function availableProducts() {
    const q = normalizeSearch(query);
    const products = Array.isArray(state.products) ? state.products : [];
    if (!q) return products.slice(0, 20);

    return products
      .map((product) => ({
        product,
        score: productSearchScore(product, q),
      }))
      .filter((entry) => entry.score > 0)
      .sort((a, b) => b.score - a.score || String(a.product.name).localeCompare(String(b.product.name), 'fr'))
      .slice(0, 30)
      .map((entry) => entry.product);
  }

  function suggestionProducts() {
    const q = normalizeSearch(query);

    if (!q) return [];

    return (Array.isArray(state.products) ? state.products : [])
      .map((product) => ({
        product,
        score: productSearchScore(product, q),
      }))
      .filter((entry) => entry.score > 0)
      .sort(
        (a, b) =>
          b.score - a.score ||
          String(a.product.name).localeCompare(
            String(b.product.name),
            'fr'
          )
      )
      .slice(0, 5)
      .map((entry) => entry.product);
  }


  function frequentProducts() {
    const products = Array.isArray(state.products)
      ? state.products
      : [];

    const ranked = frequentProductIds
      .map((id) =>
        products.find(
          (product) => Number(product.id) === Number(id)
        )
      )
      .filter(Boolean);

    const rankedIds = new Set(
      ranked.map((product) => Number(product.id))
    );

    const fallback = products.filter(
      (product) => !rankedIds.has(Number(product.id))
    );

    return [...ranked, ...fallback]
      .slice(0, 10);
  }

  async function loadFrequentProducts() {
    try {
      const rows = await api('/pwa/sales/frequent-products?limit=20');
      frequentProductIds = (rows || []).map((row) => Number(row.product_id));
    } catch {
      frequentProductIds = [];
    }
    renderExpressSale();
  }

  window.whatzabiExpressRefreshFrequentProducts =
    loadFrequentProducts;

  function add(productId) {
    const product = state.products.find((p) => Number(p.id) === Number(productId));
    if (!product) return;
    if (Number(product.stock || 0) <= 0) return toast(product.name + ' est en rupture de stock');
    const current = cart.get(product.id);
    const nextQty = (current?.quantity || 0) + 1;
    if (nextQty > Number(product.stock || 0)) return toast('Stock insuffisant pour ' + product.name);
    cart.set(product.id, { ...current, product, quantity: nextQty });
    renderExpressSale();
  }

  function change(productId, delta) {
    const line = cart.get(Number(productId));
    if (!line) return;
    const nextQty = line.quantity + delta;
    if (nextQty <= 0) cart.delete(Number(productId));
    else if (nextQty <= Number(line.product.stock || 0)) line.quantity = nextQty;
    else return toast('Stock insuffisant pour ' + line.product.name);
    renderExpressSale();
  }


  function addQuantity(productId, quantity) {
    const product = state.products.find(
      (p) => Number(p.id) === Number(productId)
    );
    if (!product) {
      throw new Error('Produit introuvable dans la boutique active.');
    }

    const qty = Math.max(1, Number(quantity || 1));
    const current = cart.get(product.id);
    const nextQty = (current?.quantity || 0) + qty;
    const stock = Number(product.stock || 0);

    if (stock <= 0) {
      throw new Error(product.name + ' est en rupture de stock.');
    }

    if (nextQty > stock) {
      throw new Error(
        'Stock insuffisant pour ' + product.name +
        ' (disponible : ' + stock + ').'
      );
    }

    cart.set(product.id, { ...current, product, quantity: nextQty });
  }

  window.whatzabiExpressVoiceSearch = function(transcript) {
    let value = String(transcript || '').trim();

    value = value.replace(
      /^(cherche|recherche|trouve|affiche|montre(?:-moi)?)\s+/i,
      ''
    ).trim();

    if (!value) {
      throw new Error('Aucun produit à rechercher.');
    }

    query = value;

    const input = $('expressSearch');
    if (input) {
      input.value = value;
    }

    expressStep = 'products';
    showTab('sales');
    renderExpressSale();

    $('sales')?.scrollIntoView({
      behavior: 'smooth',
      block: 'start'
    });

    return {
      query: value,
      result_count: availableProducts().length,
    };
  };


  window.whatzabiExpressAddVoiceLines = function(lines) {
    const requested = Array.isArray(lines) ? lines : [];
    if (!requested.length) {
      throw new Error('Aucun produit vocal à ajouter.');
    }

    // Validation complète avant mutation du panier.
    const simulated = new Map();
    for (const line of requested) {
      const product = state.products.find(
        (p) => Number(p.id) === Number(line.product_id)
      );
      if (!product) {
        throw new Error('Produit vocal introuvable dans la boutique active.');
      }

      const qty = Math.max(1, Number(line.quantity || 1));
      const alreadyInCart = cart.get(product.id)?.quantity || 0;
      const alreadyRequested = simulated.get(product.id) || 0;
      const targetQty = alreadyInCart + alreadyRequested + qty;
      const stock = Number(product.stock || 0);

      if (stock <= 0) {
        throw new Error(product.name + ' est en rupture de stock.');
      }

      if (targetQty > stock) {
        throw new Error(
          'Stock insuffisant pour ' + product.name +
          ' (demandé : ' + targetQty +
          ', disponible : ' + stock + ').'
        );
      }

      simulated.set(product.id, alreadyRequested + qty);
    }

    for (const line of requested) {
      addQuantity(line.product_id, line.quantity);
    }

    query = '';
    if ($('expressSearch')) $('expressSearch').value = '';
    renderExpressSale();

    return {
      line_count: requested.length,
      total: total(),
      cart_size: cart.size,
    };
  };

  window.whatzabiExpressOpen = function() {
    expressStep = 'products';
    showTab('sales');
    renderExpressSale();
  };

  function cartStats() {
    const lines = [...cart.values()];

    return {
      products: lines.length,
      units: lines.reduce(
        (sum, line) => sum + Number(line.quantity || 0),
        0
      ),
      amount: total(),
    };
  }

  function setExpressStep(step) {
    if (!['products', 'cart', 'payment'].includes(step)) return;

    if ((step === 'cart' || step === 'payment') && !cart.size) {
      step = 'products';
    }

    expressStep = step;
    renderExpressSale();

    $('sales')?.scrollIntoView({
      behavior: 'smooth',
      block: 'start'
    });
  }

  function renderExpressSale() {
    const grid = $('expressProductGrid');
    const cartBox = $('expressCart');

    if (!grid || !cartBox) return;

    const products = availableProducts();
    const frequent = frequentProducts();
    const suggestions = suggestionProducts();
    const suggestionsBox = $('expressSuggestions');
    const frequentSection = $('expressFrequentSection');
    const frequentGrid = $('expressFrequentGrid');
    const frequentMore = $('expressFrequentMore');
    const allProductsSection =
      $('expressAllProductsSection');

    const productButton = (p, frequentClass = '') => {
      const out = Number(p.stock || 0) <= 0;
      const qty = cart.get(p.id)?.quantity || 0;

      return `
        <button
          type="button"
          class="express-product${frequentClass}${out ? ' out-of-stock' : ''}${qty ? ' in-cart' : ''}"
          data-add-product="${p.id}"
          aria-disabled="${out ? 'true' : 'false'}"
        >
          <span class="express-product-name">${esc(p.name)}</span>
          <strong>${money(p.price)}</strong>

          <small>
            ${out
              ? 'Rupture'
              : `Stock ${Number(p.stock || 0)} ${esc(p.unit || '')}`}
          </small>

          <span class="express-add">
            ${out
              ? 'Indisponible'
              : qty
                ? `✓ ${qty} au panier`
                : '+ Ajouter'}
          </span>
        </button>
      `;
    };

    if (suggestionsBox) {
      suggestionsBox.hidden =
        query.trim().length === 0 ||
        suggestions.length === 0;

      suggestionsBox.innerHTML = suggestions
        .map((product) => {
          const out = Number(product.stock || 0) <= 0;

          return `
            <button
              type="button"
              class="express-suggestion${out ? ' out-of-stock' : ''}"
              data-add-product="${product.id}"
              ${out ? 'disabled' : ''}
            >
              <span>
                <strong>${esc(product.name)}</strong>
                <small>
                  ${
                    out
                      ? 'Rupture'
                      : `Stock ${Number(product.stock || 0)} ${esc(product.unit || '')}`
                  }
                </small>
              </span>

              <strong>${money(product.price)}</strong>
            </button>
          `;
        })
        .join('');
    }

    if (allProductsSection) {
      allProductsSection.hidden =
        query.trim().length === 0 &&
        !showAllFrequentProducts;
    }

    if (frequentMore) {
      frequentMore.hidden =
        query.trim().length > 0 ||
        state.products.length <= 10;

      frequentMore.textContent =
        showAllFrequentProducts ? 'Voir moins' : 'Voir plus';
    }

    if (frequentSection && frequentGrid) {
      frequentSection.hidden =
        query.trim().length > 0 || frequent.length === 0;

      frequentGrid.innerHTML = frequent
        .map((p) => productButton(p, ' express-product-frequent'))
        .join('');
    }

    grid.innerHTML = products.length
      ? products.map((p) => productButton(p)).join('')
      : '<p class="muted express-empty">Aucun produit dans cette boutique.</p>';

    const lines = [...cart.values()];
    const stats = cartStats();

    cartBox.innerHTML = lines.length
      ? lines.map(({ product, quantity, unitPrice }) => `
          <div class="express-line">

            <div class="express-line-main">
              <strong>${esc(product.name)}</strong>
              <small>${money(unitPrice ?? product.price)} × ${quantity}</small>

              ${unitPrice !== undefined && unitPrice !== Number(product.price)
                ? `<small>Prix catalogue : ${money(product.price)}</small>`
                : ''}

              <div class="express-price-actions">
                <button
                  type="button"
                  data-price-edit="${product.id}">
                  Modifier le prix
                </button>

                ${unitPrice !== undefined
                  ? `<button type="button"
                       data-price-reset="${product.id}">
                       Prix catalogue
                     </button>`
                  : ''}
              </div>

              ${editingPriceId === Number(product.id) ? `
                <form class="express-price-editor"
                      data-price-form="${product.id}">
                  <label for="expressPrice-${product.id}">
                    Nouveau prix unitaire
                  </label>

                  <input
                    id="expressPrice-${product.id}"
                    name="unitPrice"
                    type="number"
                    inputmode="numeric"
                    min="1"
                    step="1"
                    required
                    value="${Number(unitPrice ?? product.price)}">

                  <div>
                    <button type="submit">Appliquer</button>
                    <button type="button" data-price-cancel>
                      Annuler
                    </button>
                  </div>
                </form>
              ` : ''}
            </div>

            <strong class="express-line-total">
              ${money(Number(unitPrice ?? product.price ?? 0) * quantity)}
            </strong>

            <div class="qty-controls">

              <button type="button"
                data-cart-minus="${product.id}"
                aria-label="Retirer une unité">
                −
              </button>

              <strong>${quantity}</strong>

              <button type="button"
                data-cart-plus="${product.id}"
                aria-label="Ajouter une unité">
                +
              </button>

              <button type="button"
                class="express-remove"
                data-cart-remove="${product.id}"
                aria-label="Supprimer du panier">
                🗑
              </button>

            </div>
          </div>
        `).join('')
      : '<p class="muted express-empty">Votre panier est vide.</p>';

    /* Navigation entre les 3 étapes */

    const catalogStep = $('expressCatalogStep');
    const cartStep = $('expressCartStep');
    const paymentStep = $('expressPaymentStep');
    const cartBar = $('expressCartBar');

    if (catalogStep) {
      catalogStep.hidden = expressStep !== 'products';
    }

    if (cartStep) {
      cartStep.hidden = expressStep !== 'cart';
    }

    if (paymentStep) {
      paymentStep.hidden = expressStep !== 'payment';
    }

    if (cartBar) {
      cartBar.hidden =
        expressStep !== 'products' || lines.length === 0;
    }

    /* Bandeau panier */

    if ($('expressCartBarCount')) {
      $('expressCartBarCount').textContent =
        `${stats.products} produit${stats.products > 1 ? 's' : ''}`;
    }

    if ($('expressCartBarUnits')) {
      $('expressCartBarUnits').textContent =
        `${stats.units} unité${stats.units > 1 ? 's' : ''}`;
    }

    if ($('expressCartBarTotal')) {
      $('expressCartBarTotal').textContent = money(stats.amount);
    }

    /* Vue panier */

    if ($('expressTotal')) {
      $('expressTotal').textContent = money(stats.amount);
    }

    if ($('expressCartSummary')) {
      $('expressCartSummary').textContent =
        `${stats.units} unité${stats.units > 1 ? 's' : ''}`;
    }

    if ($('expressCartSummaryTotal')) {
      $('expressCartSummaryTotal').textContent = money(stats.amount);
    }

    const validate = $('expressValidateCart');

    if (validate) {
      validate.disabled = lines.length === 0;
      validate.textContent = lines.length
        ? `Valider le panier · ${money(stats.amount)}`
        : 'Panier vide';
    }

    /* Paiement */

    if ($('expressPaymentTotal')) {
      $('expressPaymentTotal').textContent = money(stats.amount);
    }

    const checkoutButton = $('expressCheckout');

    if (checkoutButton) {
      checkoutButton.disabled = lines.length === 0;
      checkoutButton.textContent = lines.length
        ? `Encaisser · ${money(stats.amount)}`
        : 'Panier vide';
    }
  }

  async function checkout() {
    if (!cart.size) return;
    const customerValue = $('expressCustomer').value;
    const customerId = customerValue ? Number(customerValue) : null;
    const channel = $('expressChannel').value;
    const amount = total();
    const dueDate = $('expressDueDate')?.value || null;
    let paidAmount = amount;
    if (channel === 'credit') {
      if (!customerId) return toast('Choisissez un client pour une vente à crédit');
      if (!dueDate) return toast('Choisissez une date d’échéance');
      paidAmount = 0;
    } else if (channel === 'partial') {
      if (!customerId) return toast('Choisissez un client pour un paiement partiel');
      if (!dueDate) return toast('Choisissez une date d’échéance');
      const raw = window.prompt(`Montant encaissé sur ${money(amount)}`, '0');
      if (raw === null) return;
      paidAmount = Number(raw);
      if (!Number.isFinite(paidAmount) || paidAmount < 0 || paidAmount > amount) return toast('Montant payé invalide');
    }
    const offlineManager =
      window.WhatzabiOfflineSales;

    if (!offlineManager) {
      return toast(
        'Service de vente hors ligne indisponible'
      );
    }

    const offlineSaleId =
      offlineManager.uuid();

    const salePayload = {
      customer_id: customerId,
      items: [...cart.values()].map(
        ({ product, quantity, unitPrice }) => ({
          product_id: product.id,
          quantity,
          ...(unitPrice !== undefined
            ? { unit_price: unitPrice }
            : {}),
        })
      ),
      paid_amount: paidAmount,
      payment_channel:
        channel === 'credit' ||
        channel === 'partial'
          ? 'cash'
          : channel,
      due_date:
        channel === 'credit' ||
        channel === 'partial'
          ? dueDate
          : null,
      offline_sale_id: offlineSaleId,
    };

    const merchantId =
      Number(state.merchant?.id || 0);

    const shopId =
      Number(state.merchant?.shop_id || 0);

    $('expressCheckout').disabled = true;

    try {
      await api('/pwa/sales', {
        method: 'POST',
        body: JSON.stringify(
          salePayload
        ),
      });

      cart.clear();
      editingPriceId = null;
      expressStep = 'products';
      query = '';
      $('expressSearch').value = '';

      if ($('expressDueDate')) {
        $('expressDueDate').value = '';
      }

      await refresh();

      syncExpressCustomers();
      renderExpressSale();

      toast(
        'Vente express enregistrée'
      );

      await loadFrequentProducts();
    } catch (error) {
      /*
       * Une réponse HTTP signifie que le serveur
       * a bien répondu : validation, droits,
       * stock insuffisant, conflit, etc.
       *
       * Elle ne doit donc jamais devenir une
       * "vente offline".
       */
      if (error?.isHttpError) {
        toast(error.message);
        renderExpressSale();
        return;
      }

      /*
       * Seules les vraies erreurs réseau sont
       * sauvegardées dans IndexedDB.
       */
      if (!merchantId || !shopId) {
        toast(
          'Connexion perdue. Sélectionne une boutique avant une vente hors ligne.'
        );

        renderExpressSale();
        return;
      }

      try {
        await offlineManager.enqueue({
          offline_sale_id:
            offlineSaleId,
          merchant_id:
            merchantId,
          shop_id:
            shopId,
          payload:
            salePayload,
        });

        cart.clear();
      editingPriceId = null;
        expressStep = 'products';
        query = '';
        $('expressSearch').value = '';

        if ($('expressDueDate')) {
          $('expressDueDate').value = '';
        }

        syncExpressCustomers();
        renderExpressSale();

        toast(
          'Vente enregistrée hors ligne — synchronisation automatique au retour du réseau'
        );
      } catch (offlineError) {
        toast(
          'Impossible de sauvegarder la vente hors ligne : ' +
          offlineError.message
        );

        renderExpressSale();
      }
    }
  }

  function syncExpressCustomers() {
    const select = $('expressCustomer');
    if (!select) return;
    const selected = select.value;
    select.innerHTML = '<option value="">Vente comptoir — sans client</option>' + state.customers.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
    if ([...select.options].some((o) => o.value === selected)) select.value = selected;
  }

  document.addEventListener('click', (event) => {
    const edit = event.target.closest('[data-price-edit]');

    if (edit) {
      editingPriceId = Number(edit.dataset.priceEdit);
      renderExpressSale();

      $('expressPrice-' + editingPriceId)?.focus();
      $('expressPrice-' + editingPriceId)?.select();
      return;
    }

    if (event.target.closest('[data-price-cancel]')) {
      editingPriceId = null;
      return renderExpressSale();
    }

    const reset = event.target.closest('[data-price-reset]');

    if (reset) {
      const line = cart.get(Number(reset.dataset.priceReset));
      if (line) delete line.unitPrice;

      editingPriceId = null;
      return renderExpressSale();
    }
    const addBtn = event.target.closest('[data-add-product]');
    if (addBtn) return add(addBtn.dataset.addProduct);

    const plus = event.target.closest('[data-cart-plus]');
    if (plus) return change(plus.dataset.cartPlus, 1);

    const minus = event.target.closest('[data-cart-minus]');
    if (minus) return change(minus.dataset.cartMinus, -1);

    const remove = event.target.closest('[data-cart-remove]');
    if (remove) {
      cart.delete(Number(remove.dataset.cartRemove));
      return renderExpressSale();
    }
  });
  document.addEventListener('submit', (event) => {
    const form = event.target.closest('[data-price-form]');
    if (!form) return;

    event.preventDefault();

    const line = cart.get(Number(form.dataset.priceForm));
    if (!line) return;

    const raw = form.elements.unitPrice.value.trim();
    const price = Number(raw);

    if (!raw || !Number.isSafeInteger(price) || price <= 0) {
      return toast(
        'Saisissez un prix unitaire entier supérieur à zéro.'
      );
    }

    line.unitPrice = price;
    editingPriceId = null;
    renderExpressSale();
  });

  $('expressSearch')?.addEventListener('input', (event) => { query = event.target.value; renderExpressSale(); });

  $('expressFrequentMore')?.addEventListener('click', () => {
    showAllFrequentProducts = !showAllFrequentProducts;
    renderExpressSale();
  });
  $('expressChannel')?.addEventListener('change', syncCreditFields);
  $('expressCustomer')?.addEventListener('change', syncCreditFields);
  document.querySelectorAll('[data-due-days]').forEach((button) => {
    button.addEventListener('click', () => setDueDateDays(button.dataset.dueDays));
  });
  $('expressCartBar')?.addEventListener(
    'click',
    () => setExpressStep('cart')
  );

  $('expressBackToProducts')?.addEventListener(
    'click',
    () => setExpressStep('products')
  );

  $('expressValidateCart')?.addEventListener(
    'click',
    () => setExpressStep('payment')
  );

  $('expressBackToCart')?.addEventListener(
    'click',
    () => setExpressStep('cart')
  );

  $('expressCheckout')?.addEventListener('click', checkout);

  $('expressVoice')?.addEventListener(
    'click',
    () => $('voiceNavBtn')?.click()
  );
  window.whatzabiExpressAddScannedProduct = function(productId) {
    add(productId);
    expressStep = 'products';
    showTab('sales');
    renderExpressSale();
  };

  $('expressScan')?.addEventListener('click', () => {
    if (typeof window.whatzabiStartSaleBarcodeScan === 'function') {
      window.whatzabiStartSaleBarcodeScan();
    } else {
      toast('Scanner de vente indisponible.');
    }
  });

  const originalRender = render;
  render = function () {
    originalRender();
    syncExpressCustomers();
    renderExpressSale();
  };
  syncExpressCustomers();
  syncCreditFields();
  renderExpressSale();
  loadFrequentProducts();
})();