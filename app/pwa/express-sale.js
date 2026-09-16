(() => {
  const cart = new Map();
  let query = '';

  const money = (n) => fmt(Number(n || 0));
  const total = () => [...cart.values()].reduce((sum, line) => sum + Number(line.product.price || 0) * line.quantity, 0);

  function availableProducts() {
    const q = query.trim().toLocaleLowerCase('fr');
    const products = state.products.filter((p) => Number(p.stock || 0) > 0);
    if (!q) return products.slice(0, 20);
    return products.filter((p) => String(p.name || '').toLocaleLowerCase('fr').includes(q)).slice(0, 30);
  }

  function add(productId) {
    const product = state.products.find((p) => Number(p.id) === Number(productId));
    if (!product) return;
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

  function renderExpressSale() {
    const grid = $('expressProductGrid');
    const cartBox = $('expressCart');
    if (!grid || !cartBox) return;

    const products = availableProducts();
    grid.innerHTML = products.length ? products.map((p) => `
      <button type="button" class="express-product" data-add-product="${p.id}">
        <span class="express-product-name">${esc(p.name)}</span>
        <strong>${money(p.price)}</strong>
        <small>Stock ${Number(p.stock || 0)} ${esc(p.unit || '')}</small>
        <span class="express-add">+ Ajouter</span>
      </button>`).join('') : '<p class="muted express-empty">Aucun produit trouvé.</p>';

    const lines = [...cart.values()];
    cartBox.innerHTML = lines.length ? lines.map(({ product, quantity }) => `
      <div class="express-line">
        <div><strong>${esc(product.name)}</strong><small>${quantity} × ${money(product.price)}</small></div>
        <div class="qty-controls">
          <button type="button" data-cart-minus="${product.id}" aria-label="Retirer une unité">−</button>
          <strong>${quantity}</strong>
          <button type="button" data-cart-plus="${product.id}" aria-label="Ajouter une unité">+</button>
        </div>
        <strong>${money(Number(product.price || 0) * quantity)}</strong>
      </div>`).join('') : '<p class="muted express-empty">Touchez un produit pour l’ajouter au panier.</p>';

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
      await api('/pwa/sales', {
        method: 'POST',
        body: JSON.stringify({
          customer_id: customerId,
          items: [...cart.values()].map(({ product, quantity }) => ({ product_id: product.id, quantity })),
          paid_amount: paidAmount,
          payment_channel: channel === 'credit' || channel === 'partial' ? 'cash' : channel,
        }),
      });
      cart.clear();
      query = '';
      $('expressSearch').value = '';
      await refresh();
      syncExpressCustomers();
      renderExpressSale();
      toast('Vente express enregistrée');
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

  $('expressSearch')?.addEventListener('input', (event) => {
    query = event.target.value;
    renderExpressSale();
  });
  $('expressCheckout')?.addEventListener('click', checkout);

  const originalRender = render;
  render = function () {
    originalRender();
    syncExpressCustomers();
    renderExpressSale();
  };

  syncExpressCustomers();
  renderExpressSale();
})();