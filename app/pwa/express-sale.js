(() => {
  const cart = new Map();
  let query = '';
  let frequentProductIds = [];
  const money = (n) => fmt(Number(n || 0));
  const total = () => [...cart.values()].reduce((sum, line) => sum + Number(line.product.price || 0) * line.quantity, 0);

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

  function frequentProducts() {
    return frequentProductIds
      .map((id) => state.products.find((product) => Number(product.id) === Number(id)))
      .filter(Boolean)
      .slice(0, 8);
  }

  async function loadFrequentProducts() {
    try {
      const rows = await api('/pwa/sales/frequent-products?limit=8');
      frequentProductIds = (rows || []).map((row) => Number(row.product_id));
    } catch {
      frequentProductIds = [];
    }
    renderExpressSale();
  }

  function add(productId) {
    const product = state.products.find((p) => Number(p.id) === Number(productId));
    if (!product) return;
    if (Number(product.stock || 0) <= 0) return toast(product.name + ' est en rupture de stock');
    const current = cart.get(product.id);
    const nextQty = (current?.quantity || 0) + 1;
    if (nextQty > Number(product.stock || 0)) return toast('Stock insuffisant pour ' + product.name);
    cart.set(product.id, { product, quantity: nextQty });
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

    cart.set(product.id, { product, quantity: nextQty });
  }

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
    showTab('sales');
    renderExpressSale();
    $('expressCheckout')?.scrollIntoView({
      behavior:'smooth',
      block:'center'
    });
  };

  function renderExpressSale() {
    const grid = $('expressProductGrid');
    const cartBox = $('expressCart');
    if (!grid || !cartBox) return;
    const products = availableProducts();
    const frequent = frequentProducts();
    const frequentSection = $('expressFrequentSection');
    const frequentGrid = $('expressFrequentGrid');

    if (frequentSection && frequentGrid) {
      frequentSection.hidden = query.trim().length > 0 || frequent.length === 0;
      frequentGrid.innerHTML = frequent.map((p) => {
        const out = Number(p.stock || 0) <= 0;
        return `<button type="button" class="express-product express-product-frequent${out ? ' out-of-stock' : ''}" data-add-product="${p.id}" aria-disabled="${out ? 'true' : 'false'}"><span class="express-product-name">${esc(p.name)}</span><strong>${money(p.price)}</strong><small>${out ? 'Rupture' : `Stock ${Number(p.stock || 0)} ${esc(p.unit || '')}`}</small><span class="express-add">${out ? 'Indisponible' : '+1 au panier'}</span></button>`;
      }).join('');
    }

    grid.innerHTML = products.length ? products.map((p) => {
      const out = Number(p.stock || 0) <= 0;
      return `<button type="button" class="express-product${out ? ' out-of-stock' : ''}" data-add-product="${p.id}" aria-disabled="${out ? 'true' : 'false'}"><span class="express-product-name">${esc(p.name)}</span><strong>${money(p.price)}</strong><small>${out ? 'Rupture' : `Stock ${Number(p.stock || 0)} ${esc(p.unit || '')}`}</small><span class="express-add">${out ? 'Indisponible' : '+1 au panier'}</span></button>`;
    }).join('') : '<p class="muted express-empty">Aucun produit dans cette boutique.</p>';

    const lines = [...cart.values()];
    cartBox.innerHTML = lines.length ? lines.map(({ product, quantity }) => `<div class="express-line"><div><strong>${esc(product.name)}</strong><small>${quantity} × ${money(product.price)}</small></div><div class="qty-controls"><button type="button" data-cart-minus="${product.id}">−</button><strong>${quantity}</strong><button type="button" data-cart-plus="${product.id}">+</button></div><strong>${money(Number(product.price || 0) * quantity)}</strong></div>`).join('') : '<p class="muted express-empty">Touchez un produit pour l’ajouter au panier.</p>';
    $('expressTotal').textContent = money(total());
    $('expressCheckout').disabled = lines.length === 0;
    $('expressCheckout').textContent = lines.length ? `Encaisser ${money(total())}` : 'Panier vide';
  }

  async function checkout() {
    if (!cart.size) return;
    const customerValue = $('expressCustomer').value;
    const customerId = customerValue ? Number(customerValue) : null;
    const channel = $('expressChannel').value;
    const amount = total();
    let paidAmount = amount;
    if (channel === 'credit') {
      if (!customerId) return toast('Choisissez un client pour une vente à crédit');
      paidAmount = 0;
    } else if (channel === 'partial') {
      if (!customerId) return toast('Choisissez un client pour un paiement partiel');
      const raw = window.prompt(`Montant encaissé sur ${money(amount)}`, '0');
      if (raw === null) return;
      paidAmount = Number(raw);
      if (!Number.isFinite(paidAmount) || paidAmount < 0 || paidAmount > amount) return toast('Montant payé invalide');
    }
    $('expressCheckout').disabled = true;
    try {
      await api('/pwa/sales', { method: 'POST', body: JSON.stringify({ customer_id: customerId, items: [...cart.values()].map(({ product, quantity }) => ({ product_id: product.id, quantity })), paid_amount: paidAmount, payment_channel: channel === 'credit' || channel === 'partial' ? 'cash' : channel }) });
      cart.clear();
      query = '';
      $('expressSearch').value = '';
      await refresh();
      syncExpressCustomers();
      renderExpressSale();
      toast('Vente express enregistrée');
      await loadFrequentProducts();
    } catch (error) {
      toast(error.message);
      renderExpressSale();
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
    const addBtn = event.target.closest('[data-add-product]');
    if (addBtn) return add(addBtn.dataset.addProduct);
    const plus = event.target.closest('[data-cart-plus]');
    if (plus) return change(plus.dataset.cartPlus, 1);
    const minus = event.target.closest('[data-cart-minus]');
    if (minus) return change(minus.dataset.cartMinus, -1);
  });
  $('expressSearch')?.addEventListener('input', (event) => { query = event.target.value; renderExpressSale(); });
  $('expressCheckout')?.addEventListener('click', checkout);
  $('expressVoice')?.addEventListener('click', () => $('voiceNavBtn')?.click());
  window.whatzabiExpressAddScannedProduct = function(productId) {
    add(productId);
    showTab('sales');
    $('expressCheckout')?.scrollIntoView({ behavior:'smooth', block:'center' });
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
  renderExpressSale();
  loadFrequentProducts();
})();