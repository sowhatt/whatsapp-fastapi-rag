const $ = (id) => document.getElementById(id);
const fmt = (n) => new Intl.NumberFormat('fr-FR').format(Number(n || 0)) + ' FCFA';
const ROLE_LABELS = {
  OWNER: 'Propriétaire',
  MANAGER: 'Manager',
  SELLER: 'Vendeur',
  STOCK_MANAGER: 'Gestionnaire stock',
  ACCOUNTANT: 'Comptable',
};

let token = localStorage.getItem('whatzabi_token') || '';
let state = { products: [], customers: [], sales: [], merchant: null, shops: [] };

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers.Authorization = 'Bearer ' + token;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && path !== '/auth/login') {
    logout();
    throw new Error('Session expirée');
  }
  let body = null;
  try {
    body = await response.json();
  } catch {}
  if (!response.ok) throw new Error(body?.detail || 'Erreur serveur');
  return body;
}

function toast(message) {
  const element = $('toast');
  element.textContent = message;
  element.hidden = false;
  setTimeout(() => (element.hidden = true), 2500);
}

function showTab(name) {
  document.querySelectorAll('.panel').forEach((element) =>
    element.classList.toggle('active', element.id === name),
  );
  document.querySelectorAll('.tabs button').forEach((element) =>
    element.classList.toggle('active', element.dataset.tab === name),
  );
}

function logout() {
  token = '';
  localStorage.removeItem('whatzabi_token');
  state = { products: [], customers: [], sales: [], merchant: null, shops: [] };
  $('appView').hidden = true;
  $('loginView').hidden = false;
}

function renderIdentity() {
  const merchant = state.merchant || {};
  $('shopName').textContent = merchant.shop_name || 'Mon commerce';
  $('merchantPhone').textContent = merchant.whatsapp_number || '';
  $('activeShopName').textContent = merchant.active_shop_name || merchant.shop_name || 'Commerce principal';
  $('userName').textContent = merchant.user_name || 'Compte commerçant';
  $('roleBadge').textContent = ROLE_LABELS[merchant.role] || merchant.role || 'Propriétaire';

  const selectorWrap = $('shopSelectorWrap');
  const selector = $('shopSelector');
  const canSwitch = state.shops.length > 1;
  selectorWrap.hidden = !canSwitch;
  selector.innerHTML = state.shops
    .map((shop) => `<option value="${shop.id}" ${shop.id === merchant.shop_id ? 'selected' : ''}>${esc(shop.name)} — ${esc(ROLE_LABELS[shop.role] || shop.role)}</option>`)
    .join('');
}

function render() {
  const products = state.products;
  const customers = state.customers;
  const sales = state.sales;

  renderIdentity();
  $('statProducts').textContent = products.length;
  $('statCustomers').textContent = customers.length;
  $('statSales').textContent = sales.length;
  $('statDue').textContent = fmt(sales.reduce((sum, sale) => sum + Number(sale.remaining_amount || 0), 0));

  $('productList').innerHTML = products.length
    ? products
        .map(
          (product) => `<article class="item"><div class="item-main"><div class="item-title">${esc(product.name)}</div><div class="item-meta">Stock boutique: ${product.stock} ${esc(product.unit)} · Seuil: ${product.threshold}</div></div><div class="money">${fmt(product.price)}</div></article>`,
        )
        .join('')
    : '<article class="card muted">Aucun produit.</article>';

  $('customerList').innerHTML = customers.length
    ? customers
        .map(
          (customer) => `<article class="item"><div class="item-main"><div class="item-title">${esc(customer.name)}</div><div class="item-meta">${esc(customer.phone || 'Sans téléphone')}</div></div><div class="money">Dette ${fmt(customer.debt)}</div></article>`,
        )
        .join('')
    : '<article class="card muted">Aucun client.</article>';

  $('saleList').innerHTML = sales.length
    ? sales
        .map(
          (sale) => `<article class="item"><div class="item-main"><div class="item-title">Vente #${sale.sale_number ?? sale.id}</div><div class="item-meta"><span class="badge">${esc(sale.status)}</span> · payé ${fmt(sale.paid_amount)}</div></div><div class="money">${fmt(sale.total_amount)}</div></article>`,
        )
        .join('')
    : '<article class="card muted">Aucune vente.</article>';

  $('saleCustomer').innerHTML =
    '<option value="">Client</option>' +
    customers.map((customer) => `<option value="${customer.id}">${esc(customer.name)}</option>`).join('');

  $('saleProduct').innerHTML =
    '<option value="">Produit</option>' +
    products
      .map(
        (product) => `<option value="${product.id}">${esc(product.name)} — stock ${product.stock} — ${fmt(product.price)}</option>`,
      )
      .join('');
}

function esc(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (match) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  })[match]);
}

async function selectShop(shopId, { silent = false } = {}) {
  const data = await api('/auth/select-shop', {
    method: 'POST',
    body: JSON.stringify({ shop_id: Number(shopId) }),
  });
  token = data.access_token;
  localStorage.setItem('whatzabi_token', token);
  state.merchant = data.merchant;
  if (!silent) toast('Boutique active : ' + (data.merchant.active_shop_name || 'boutique sélectionnée'));
}

async function loadContext() {
  let merchant = await api('/auth/me');
  let shops = await api('/auth/shops');

  if (merchant.user_id && !merchant.shop_id && shops.length) {
    await selectShop(shops[0].id, { silent: true });
    merchant = await api('/auth/me');
    shops = await api('/auth/shops');
  }

  state.merchant = merchant;
  state.shops = shops;
}

async function refresh() {
  await loadContext();
  const [products, customers, sales] = await Promise.all([
    api('/pwa/products'),
    api('/pwa/customers'),
    api('/pwa/sales'),
  ]);
  state.products = products;
  state.customers = customers;
  state.sales = sales;
  render();
}

async function boot() {
  if (!token) return;
  try {
    await refresh();
    $('loginView').hidden = true;
    $('appView').hidden = false;
  } catch {
    logout();
  }
}

$('loginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('loginError').textContent = '';
  try {
    const data = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        whatsapp_number: $('phone').value.trim(),
        password: $('password').value,
      }),
    });
    token = data.access_token;
    localStorage.setItem('whatzabi_token', token);
    $('password').value = '';
    await refresh();
    $('loginView').hidden = true;
    $('appView').hidden = false;
  } catch (error) {
    $('loginError').textContent = error.message;
  }
});

$('shopSelector').addEventListener('change', async (event) => {
  const previousShopId = state.merchant?.shop_id;
  try {
    await selectShop(event.target.value);
    await refresh();
    showTab('dashboard');
  } catch (error) {
    if (previousShopId) event.target.value = String(previousShopId);
    toast(error.message);
  }
});

$('logoutBtn').addEventListener('click', logout);

document.querySelectorAll('[data-tab]').forEach((button) =>
  button.addEventListener('click', () => showTab(button.dataset.tab)),
);

document.querySelectorAll('[data-open-tab]').forEach((button) =>
  button.addEventListener('click', () => showTab(button.dataset.openTab)),
);

$('productForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await api('/pwa/products', {
      method: 'POST',
      body: JSON.stringify({
        name: $('productName').value,
        unit: $('productUnit').value,
        stock: Number($('productStock').value),
        price: Number($('productPrice').value),
        purchase_price: Number($('productPurchasePrice').value),
        threshold: Number($('productThreshold').value),
      }),
    });
    event.target.reset();
    $('productUnit').value = 'unité';
    $('productStock').value = '0';
    $('productPrice').value = '0';
    $('productPurchasePrice').value = '0';
    $('productThreshold').value = '0';
    await refresh();
    toast('Produit ajouté dans la boutique active');
  } catch (error) {
    toast(error.message);
  }
});

$('customerForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await api('/pwa/customers', {
      method: 'POST',
      body: JSON.stringify({
        name: $('customerName').value,
        phone: $('customerPhone').value || null,
        debt: 0,
      }),
    });
    event.target.reset();
    await refresh();
    toast('Client ajouté');
  } catch (error) {
    toast(error.message);
  }
});

$('saleForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const product = state.products.find((item) => item.id === Number($('saleProduct').value));
    if (!product) throw new Error('Choisissez un produit');
    await api('/pwa/sales', {
      method: 'POST',
      body: JSON.stringify({
        customer_id: Number($('saleCustomer').value),
        items: [{ product_id: product.id, quantity: Number($('saleQty').value) }],
        paid_amount: Number($('salePaid').value),
        payment_channel: $('saleChannel').value,
      }),
    });
    event.target.reset();
    $('saleQty').value = '1';
    $('salePaid').value = '0';
    await refresh();
    toast('Vente enregistrée dans la boutique active');
  } catch (error) {
    toast(error.message);
  }
});

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/auth/sw.js').catch(() => {});
boot();
