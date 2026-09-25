const $ = (id) => document.getElementById(id);
function currencyMeta(code) {
  const context = state?.currencyContext || {};
  const currencies = context.currencies || [];
  return currencies.find((item) => item.code === code) || null;
}

function fmt(n) {
  const code = state?.currencyContext?.shop_currency || 'XOF';
  const meta = currencyMeta(code);
  const decimals = Number(meta?.decimals ?? (code === 'XOF' ? 0 : 2));
  const value = Number(n || 0);
  const formatted = new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
  return formatted + ' ' + (meta?.symbol || code);
}
const ROLE_LABELS = {
  OWNER: 'Propriétaire',
  MANAGER: 'Manager',
  SELLER: 'Vendeur',
  STOCK_MANAGER: 'Gestionnaire stock',
  ACCOUNTANT: 'Comptable',
};

const ROLE_PERMISSIONS = {
  OWNER: ['*'],
  MANAGER: [
    'sale.create',
    'sale.cancel',
    'sale.read',
    'stock.read',
    'stock.adjust',
    'product.read',
    'product.create',
    'product.update',
    'customer.read',
    'customer.create',
    'payment.create',
    'report.read',
    'staff.read',
  ],
  SELLER: [
    'sale.create',
    'sale.read',
    'stock.read',
    'product.read',
    'customer.read',
    'customer.create',
    'payment.create',
  ],
  STOCK_MANAGER: [
    'stock.read',
    'stock.adjust',
    'product.read',
    'product.create',
    'product.update',
  ],
  ACCOUNTANT: [
    'sale.read',
    'stock.read',
    'product.read',
    'customer.read',
    'report.read',
  ],
};

function can(permission) {
  const role = state.merchant?.role;
  const permissions = ROLE_PERMISSIONS[role] || [];
  return permissions.includes('*') || permissions.includes(permission);
}

function renderPermissions() {
  const productCreate = can('product.create');
  const saleCreate = can('sale.create');

  $('productCreateCard').hidden = !productCreate;
  $('quickAddSale').hidden = !saleCreate;
}

let token = localStorage.getItem('whatzabi_token') || '';
let state = { products: [], customers: [], sales: [], merchant: null, shops: [], currencyContext: null };
let editingProductId = null;
let invoiceDraftQueue = [];
let invoiceDraftPosition = 0;

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
  document.querySelectorAll('.tabs [data-tab]').forEach((element) =>
    element.classList.toggle('active', element.dataset.tab === name),
  );
}


function resetProductForm() {
  editingProductId = null;
  $('productForm').reset();
  $('productUnit').value = 'unité';
  $('productStock').value = '0';
  $('productPrice').value = '0';
  $('productPurchasePrice').value = '0';
  $('productThreshold').value = '0';
  $('productType').value = '';
  $('productBrand').value = '';
  $('productVariant').value = '';
  $('productPackaging').value = '';
  $('productFormTitle').textContent = 'Ajouter un produit';
  $('productSubmitBtn').textContent = 'Ajouter le produit';
  $('productCancelEditBtn').hidden = true;
}

function fillProductForm(values = {}) {
  $('productName').value = values.name || '';
  $('productUnit').value = values.unit || 'unité';
  $('productType').value = values.product_type || '';
  $('productBrand').value = values.brand || '';
  $('productVariant').value = values.variant || '';
  $('productPackaging').value = values.packaging || '';
  $('productStock').value = String(values.stock ?? values.quantity ?? 0);
  $('productPrice').value = String(values.price ?? 0);
  $('productPurchasePrice').value = String(values.purchase_price ?? 0);
  $('productThreshold').value = String(values.threshold ?? 0);
}

window.whatzabiOpenProductDraft = function(candidate) {
  resetProductForm();
  fillProductForm(candidate || {});
  setSmartCatalogStatus(
    'Produit reconnu. Vérifie le nom, complète le prix de vente, le prix d’achat, le stock et le seuil avant de créer la fiche.',
  );
  showTab('products');
  $('productCreateCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
  $('productPrice').focus();
};

window.whatzabiEditProduct = function(productId) {
  if (!can('product.update')) {
    toast('Ton rôle ne permet pas de modifier un produit.');
    return;
  }

  const product = state.products.find((item) => item.id === Number(productId));
  if (!product) {
    toast('Produit introuvable dans la boutique active.');
    return;
  }

  editingProductId = product.id;
  fillProductForm(product);
  $('productFormTitle').textContent = 'Modifier le produit';
  $('productSubmitBtn').textContent = 'Enregistrer les modifications';
  $('productCancelEditBtn').hidden = false;
  setSmartCatalogStatus(
    `Modification de « ${product.name} ». Le stock affiché est celui de la boutique active.`,
  );
  showTab('products');
  $('productCreateCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
};


function openInvoiceDraftItem() {
  const item = invoiceDraftQueue[invoiceDraftPosition];
  if (!item) return false;

  const candidate = item.candidate || item;
  const existingId = Number(item.existing_product_id || 0);
  const quantity = Math.max(0, Number(candidate.quantity || 0));
  const existing = existingId
    ? state.products.find((product) => product.id === existingId)
    : null;

  resetProductForm();

  if (existing) {
    editingProductId = existing.id;
    fillProductForm({
      ...existing,
      name: candidate.name || existing.name,
      brand: candidate.brand || existing.brand,
      variant: candidate.variant || existing.variant,
      packaging: candidate.packaging || existing.packaging,
      purchase_price: candidate.purchase_price ?? existing.purchase_price ?? 0,
      stock: Number(existing.stock || 0) + quantity,
    });
    $('productFormTitle').textContent = 'Facture · Mettre à jour ' + existing.name;
    $('productSubmitBtn').textContent = 'Valider la ligne et continuer';
  } else {
    fillProductForm({
      ...candidate,
      stock: quantity,
      price: 0,
      threshold: 0,
    });
    $('productFormTitle').textContent = 'Facture · Nouveau produit';
    $('productSubmitBtn').textContent = 'Créer le produit et continuer';
  }

  $('productCancelEditBtn').hidden = false;
  const conversionInfo =
    candidate.invoice_original_price && candidate.invoice_original_currency
      ? ' Prix facture : ' + candidate.invoice_original_price + ' ' +
        candidate.invoice_original_currency + ' → ' +
        candidate.purchase_price + ' ' +
        (state.currencyContext?.shop_currency || candidate.currency || '') +
        ' (taux ' + candidate.invoice_exchange_rate +
        ', ' + candidate.invoice_rate_source + ').'
      : '';

  setSmartCatalogStatus(
    'Facture : ligne ' + (invoiceDraftPosition + 1) + '/' + invoiceDraftQueue.length + '. ' +
    (existing
      ? 'Le stock proposé inclut la quantité achetée. Vérifie avant de valider.'
      : 'Complète notamment le prix de vente avant de créer le produit.') +
    conversionInfo
  );

  showTab('products');
  $('productCreateCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (!existing) $('productPrice').focus();
  return true;
}

window.whatzabiOpenInvoiceDrafts = function(items) {
  const prepared = Array.isArray(items)
    ? items.filter((item) => item?.candidate?.name || item?.name)
    : [];

  if (!prepared.length) {
    toast('Aucune ligne de facture sélectionnée.');
    return;
  }

  invoiceDraftQueue = prepared;
  invoiceDraftPosition = 0;
  openInvoiceDraftItem();
};

function logout() {
  token = '';
  localStorage.removeItem('whatzabi_token');
  state = { products: [], customers: [], sales: [], merchant: null, shops: [], currencyContext: null };
  $('appView').hidden = true;
  $('loginView').hidden = false;
}

function renderCurrencyPanel() {
  const context = state.currencyContext;
  if (!context) return;

  const select = $('shopCurrencySelect');
  if (select) {
    select.innerHTML = (context.currencies || [])
      .map((item) =>
        `<option value="${esc(item.code)}" ${item.code === context.shop_currency ? 'selected' : ''}>${esc(item.code)} — ${esc(item.name)} (${esc(item.symbol || item.code)})</option>`
      )
      .join('');
  }

  const meta = currencyMeta(context.shop_currency);
  if ($('currencyShopStatus')) {
    $('currencyShopStatus').textContent =
      'Devise active : ' + context.shop_currency +
      (meta?.symbol ? ' (' + meta.symbol + ')' : '');
  }

  if ($('productPriceCurrency')) {
    $('productPriceCurrency').textContent = meta?.symbol || context.shop_currency;
  }
  if ($('productPurchaseCurrency')) {
    $('productPurchaseCurrency').textContent = meta?.symbol || context.shop_currency;
  }
}

async function loadCurrencyRates() {
  const list = $('currencyRatesList');
  const base = state.currencyContext?.shop_currency || 'EUR';

  if (list) {
    list.innerHTML = '<p class="muted empty-state">Chargement des taux…</p>';
  }

  try {
    const rows = await api('/pwa/currencies/rates?base=' + encodeURIComponent(base));
    if (!list) return;

    list.innerHTML = rows.length
      ? rows.map((row) =>
          `<article class="activity-row">
            <div>
              <strong>1 ${esc(row.base)} = ${esc(row.rate)} ${esc(row.quote)}</strong>
              <span>${esc(row.source)} · ${esc(row.date)}</span>
            </div>
          </article>`
        ).join('')
      : '<p class="muted empty-state">Aucun taux disponible.</p>';
  } catch (error) {
    if (list) {
      list.innerHTML = '<p class="error">' + esc(error.message) + '</p>';
    }
  }
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
  renderPermissions();
  renderCurrencyPanel();
  const revenue = sales.reduce(
    (sum, sale) => sum + Number(sale.total_amount || 0),
    0,
  );

  const customerDebt = customers.reduce(
    (sum, customer) => sum + Number(customer.debt || 0),
    0,
  );

  const customersWithDebt = customers.filter(
    (customer) => Number(customer.debt || 0) > 0,
  ).length;

  const lowStockProducts = products.filter(
    (product) => Number(product.stock || 0) <= Number(product.threshold || 0),
  );

  $('statRevenue').textContent = fmt(revenue);
  $('statSales').textContent = sales.length;
  $('statDebt').textContent = fmt(customerDebt);
  $('statDebtCustomers').textContent =
    customersWithDebt + (customersWithDebt > 1 ? ' clients' : ' client');
  $('statLowStock').textContent = lowStockProducts.length;

  $('activityRevenue').textContent = fmt(revenue);
  $('activityDebt').textContent = fmt(customerDebt);

  $('recentActivity').innerHTML = sales.length
    ? sales
        .slice(0, 4)
        .map(
          (sale) => `<article class="recent-row">
            <div>
              <strong>Vente #${sale.sale_number ?? sale.id}</strong>
              <span>${esc(sale.status)} · payé ${fmt(sale.paid_amount)}</span>
            </div>
            <strong>${fmt(sale.total_amount)}</strong>
          </article>`,
        )
        .join('')
    : '<p class="muted empty-state">Aucune activité récente.</p>';

  $('activityStock').innerHTML = products.length
    ? products
        .map((product) => {
          const stock = Number(product.stock || 0);
          const threshold = Number(product.threshold || 0);

          const status =
            stock <= 0
              ? '<span class="stock-state stock-out">Rupture</span>'
              : stock <= threshold
                ? '<span class="stock-state stock-low">Faible</span>'
                : '<span class="stock-state stock-ok">OK</span>';

          return `<article class="activity-row">
            <div>
              <strong>${esc(product.name)}</strong>
              <span>Stock ${stock} ${esc(product.unit)}</span>
            </div>
            ${status}
          </article>`;
        })
        .join('')
    : '<p class="muted empty-state">Aucun produit.</p>';

  $('activitySales').innerHTML = sales.length
    ? sales
        .slice(0, 8)
        .map(
          (sale) => `<article class="activity-row">
            <div>
              <strong>Vente #${sale.sale_number ?? sale.id}</strong>
              <span>${esc(sale.status)}</span>
            </div>
            <strong>${fmt(sale.total_amount)}</strong>
          </article>`,
        )
        .join('')
    : '<p class="muted empty-state">Aucune vente.</p>';

  $('productList').innerHTML = products.length
    ? products
        .map(
          (product) => `<article class="item">
            <div class="item-main">
              <div class="item-title">${esc(product.name)}</div>
              <div class="item-meta">Stock boutique: ${product.stock} ${esc(product.unit)} · Seuil: ${product.threshold}</div>
            </div>
            <div>
              <div class="money">${fmt(product.price)}</div>
              ${can('product.update') ? `<button type="button" class="ghost" data-edit-product="${product.id}">Modifier</button>` : ''}
            </div>
          </article>`,
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
          (sale) => `<button type="button" class="item sale-item-button" data-sale-actions="${sale.id}">
            <div class="item-main">
              <div class="item-title">Vente #${sale.sale_number ?? sale.id}</div>
              <div class="item-meta"><span class="badge">${esc(sale.status)}</span> · payé ${fmt(sale.paid_amount)}</div>
            </div>
            <div class="sale-item-end">
              <div class="money">${fmt(sale.total_amount)}</div>
              <span aria-hidden="true">›</span>
            </div>
          </button>`,
        )
        .join('')
    : '<article class="card muted">Aucune vente.</article>';

  $('saleCustomer').innerHTML =
    '<option value="">Vente comptoir — sans client</option>' +
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


let selectedSaleActionId = null;

function saleStatusLabel(status) {
  const labels = {
    paid: 'Payée',
    credit: 'À crédit',
    partial: 'Paiement partiel',
    cancelled: 'Annulée',
  };
  return labels[status] || status || '';
}

function openSaleActions(saleId) {
  const sale = state.sales.find((item) => Number(item.id) === Number(saleId));
  if (!sale) {
    toast('Vente introuvable dans la boutique active.');
    return;
  }

  selectedSaleActionId = sale.id;
  $('saleActionTitle').textContent =
    'Vente #' + (sale.sale_number ?? sale.id);
  $('saleActionMeta').textContent =
    saleStatusLabel(sale.status) + ' · ' + fmt(sale.total_amount);

  const cancelBtn = $('saleCancelBtn');
  cancelBtn.hidden =
    !can('sale.cancel') || String(sale.status) === 'cancelled';

  $('saleActionSheet').hidden = false;
}

function closeSaleActions() {
  $('saleActionSheet').hidden = true;
  selectedSaleActionId = null;
}

function receiptEscape(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (match) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  })[match]);
}

async function generateSaleReceipt(saleId) {
  const sale = state.sales.find((item) => Number(item.id) === Number(saleId));
  if (!sale) {
    toast('Vente introuvable.');
    return;
  }

  // Open synchronously so mobile browsers do not block the receipt window.
  const receiptWindow = window.open('', '_blank');
  if (!receiptWindow) {
    toast('Autorise les fenêtres contextuelles pour générer le reçu.');
    return;
  }

  receiptWindow.document.write(
    '<!doctype html><meta charset="utf-8"><title>Reçu Whatzabi</title>' +
    '<p style="font-family:system-ui;padding:24px">Préparation du reçu…</p>'
  );

  try {
    const [items, payments] = await Promise.all([
      api('/pwa/sales/' + sale.id + '/items'),
      api('/pwa/sales/' + sale.id + '/payments'),
    ]);

    const customer = sale.customer_id
      ? state.customers.find((item) => Number(item.id) === Number(sale.customer_id))
      : null;

    const merchant = state.merchant || {};
    const shopName =
      merchant.active_shop_name ||
      merchant.shop_name ||
      'Commerce';

    const rows = (items || []).map((item) => {
      const product = state.products.find(
        (entry) => Number(entry.id) === Number(item.product_id)
      );
      const name = product?.name || ('Produit #' + item.product_id);
      return `
        <tr>
          <td>${receiptEscape(name)}</td>
          <td style="text-align:center">${receiptEscape(item.quantity)}</td>
          <td style="text-align:right">${receiptEscape(fmt(item.unit_price))}</td>
          <td style="text-align:right">${receiptEscape(fmt(item.line_total))}</td>
        </tr>
      `;
    }).join('');

    const paymentText = (payments || []).length
      ? (payments || []).map((payment) =>
          receiptEscape(payment.channel || 'paiement') +
          ' : ' + receiptEscape(fmt(payment.amount))
        ).join('<br>')
      : 'Aucun paiement enregistré';

    const receiptNumber = sale.sale_number ?? sale.id;
    const cancelled = String(sale.status) === 'cancelled';

    receiptWindow.document.open();
    receiptWindow.document.write(`
      <!doctype html>
      <html lang="fr">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Reçu #${receiptEscape(receiptNumber)}</title>
        <style>
          body{font-family:Arial,sans-serif;max-width:760px;margin:0 auto;padding:28px;color:#111}
          header{border-bottom:2px solid #111;padding-bottom:14px;margin-bottom:18px}
          h1{font-size:24px;margin:0 0 6px}
          .muted{color:#666}
          table{width:100%;border-collapse:collapse;margin:18px 0}
          th,td{padding:10px 6px;border-bottom:1px solid #ddd;font-size:14px}
          th{text-align:left}
          .totals{margin-left:auto;max-width:330px}
          .totals div{display:flex;justify-content:space-between;padding:5px 0}
          .total{font-size:20px;font-weight:700;border-top:2px solid #111;margin-top:5px;padding-top:10px!important}
          .cancelled{border:2px solid #b42318;color:#b42318;padding:8px 12px;font-weight:700;display:inline-block;margin-top:10px}
          .actions{margin-top:28px}
          button{padding:12px 18px;font-size:16px}
          @media print{.actions{display:none} body{padding:0}}
        </style>
      </head>
      <body>
        <header>
          <h1>${receiptEscape(shopName)}</h1>
          <div>Reçu de vente #${receiptEscape(receiptNumber)}</div>
          <div class="muted">Généré par Whatzabi</div>
          ${cancelled ? '<div class="cancelled">VENTE ANNULÉE</div>' : ''}
        </header>

        <section>
          <div><strong>Client :</strong> ${receiptEscape(customer?.name || 'Vente comptoir')}</div>
          <div><strong>Statut :</strong> ${receiptEscape(saleStatusLabel(sale.status))}</div>
        </section>

        <table>
          <thead>
            <tr>
              <th>Produit</th>
              <th style="text-align:center">Qté</th>
              <th style="text-align:right">Prix</th>
              <th style="text-align:right">Total</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>

        <div class="totals">
          <div class="total"><span>Total</span><span>${receiptEscape(fmt(sale.total_amount))}</span></div>
          <div><span>Payé</span><span>${receiptEscape(fmt(sale.paid_amount))}</span></div>
          <div><span>Reste</span><span>${receiptEscape(fmt(sale.remaining_amount))}</span></div>
        </div>

        <p><strong>Paiement</strong><br>${paymentText}</p>

        <p class="muted">
          Ce document est un reçu de vente Whatzabi. Il ne constitue pas une facture
          normalisée ou fiscale tant que le module de facturation réglementaire
          applicable n'est pas activé.
        </p>

        <div class="actions">
          <button onclick="window.print()">Imprimer / Enregistrer en PDF</button>
        </div>
      </body>
      </html>
    `);
    receiptWindow.document.close();
    receiptWindow.focus();
  } catch (error) {
    receiptWindow.close();
    toast(error.message || 'Impossible de générer le reçu.');
  }
}

async function cancelSaleFromActions(saleId) {
  const sale = state.sales.find((item) => Number(item.id) === Number(saleId));
  if (!sale) {
    toast('Vente introuvable.');
    return;
  }

  if (!can('sale.cancel')) {
    toast('Ton rôle ne permet pas d’annuler une vente.');
    return;
  }

  const reason = window.prompt(
    'Motif de l’annulation de la vente #' +
    (sale.sale_number ?? sale.id) +
    ' :',
    ''
  );

  if (reason === null) return;
  if (!reason.trim()) {
    toast('Le motif d’annulation est obligatoire.');
    return;
  }

  if (!window.confirm(
    'Confirmer l’annulation ? Le stock sera réintégré et l’opération sera tracée.'
  )) {
    return;
  }

  try {
    await api('/pwa/sales/' + sale.id + '/cancel', {
      method: 'POST',
      body: JSON.stringify({ reason: reason.trim() }),
    });

    closeSaleActions();
    await refresh();
    toast('Vente annulée. Stock réintégré.');
  } catch (error) {
    toast(error.message || 'Impossible d’annuler la vente.');
  }
}

document.addEventListener('click', (event) => {
  const saleButton = event.target.closest('[data-sale-actions]');
  if (saleButton) {
    openSaleActions(saleButton.dataset.saleActions);
  }
});

$('saleActionCloseBtn')?.addEventListener('click', closeSaleActions);
$('saleReceiptBtn')?.addEventListener('click', () => {
  if (selectedSaleActionId != null) {
    generateSaleReceipt(selectedSaleActionId);
  }
});
$('saleCancelBtn')?.addEventListener('click', () => {
  if (selectedSaleActionId != null) {
    cancelSaleFromActions(selectedSaleActionId);
  }
});

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
  const [currencyContext, products, customers, sales] = await Promise.all([
    api('/pwa/currencies/context'),
    api('/pwa/products'),
    api('/pwa/customers'),
    api('/pwa/sales'),
  ]);
  state.currencyContext = currencyContext;
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

$('shopCurrencySelect')?.addEventListener('change', async (event) => {
  const previous = state.currencyContext?.shop_currency || 'XOF';
  try {
    await api('/pwa/currencies/shop', {
      method: 'PUT',
      body: JSON.stringify({ currency_code: event.target.value }),
    });
    await refresh();
    await loadCurrencyRates();
    toast('Devise boutique mise à jour');
  } catch (error) {
    event.target.value = previous;
    toast(error.message);
  }
});

$('currencyRefreshBtn')?.addEventListener('click', async () => {
  await loadCurrencyRates();
});


document.querySelectorAll('[data-tab]').forEach((button) =>
  button.addEventListener('click', () => showTab(button.dataset.tab)),
);

document.querySelectorAll('[data-open-tab]').forEach((button) =>
  button.addEventListener('click', () => {
    showTab(button.dataset.openTab);
    if (button.dataset.openTab === 'currencies') {
      loadCurrencyRates();
    }
  }),
);


document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-edit-product]');
  if (!button) return;
  window.whatzabiEditProduct(Number(button.dataset.editProduct));
});

$('productCancelEditBtn').addEventListener('click', () => {
  const hadInvoiceQueue = invoiceDraftQueue.length > 0;
  invoiceDraftQueue = [];
  invoiceDraftPosition = 0;
  resetProductForm();
  setSmartCatalogStatus('');
  if (hadInvoiceQueue) toast('Traitement de la facture annulé.');
});

$('productForm').addEventListener('submit', async (event) => {
  event.preventDefault();

  const payload = {
    name: $('productName').value,
    product_type: $('productType').value || null,
    brand: $('productBrand').value || null,
    variant: $('productVariant').value || null,
    packaging: $('productPackaging').value || null,
    unit: $('productUnit').value,
    stock: Number($('productStock').value),
    price: Number($('productPrice').value),
    purchase_price: Number($('productPurchasePrice').value),
    threshold: Number($('productThreshold').value),
  };

  const wasEditing = editingProductId !== null;
  const path = wasEditing
    ? `/pwa/products/${editingProductId}`
    : '/pwa/products';

  try {
    await api(path, {
      method: wasEditing ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });

    const processingInvoice = invoiceDraftQueue.length > 0;
    const invoiceLineCount = invoiceDraftQueue.length;

    resetProductForm();
    setSmartCatalogStatus('');
    await refresh();

    if (processingInvoice) {
      invoiceDraftPosition += 1;

      if (invoiceDraftPosition < invoiceDraftQueue.length) {
        toast('Ligne validée. Ligne suivante…');
        openInvoiceDraftItem();
        return;
      }

      invoiceDraftQueue = [];
      invoiceDraftPosition = 0;
      toast('Facture traitée : ' + invoiceLineCount + ' ligne(s) validée(s).');
      return;
    }

    toast(
      wasEditing
        ? 'Produit modifié dans la boutique active'
        : 'Produit ajouté dans la boutique active',
    );
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
    const quantity = Number($('saleQty').value);
    const selectedCustomer = $('saleCustomer').value;
    const customerId = selectedCustomer ? Number(selectedCustomer) : null;

    let paidAmount = Number($('salePaid').value);
    if (customerId === null) {
      paidAmount = Number(product.price) * quantity;
    }

    await api('/pwa/sales', {
      method: 'POST',
      body: JSON.stringify({
        customer_id: customerId,
        items: [{ product_id: product.id, quantity }],
        paid_amount: paidAmount,
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

function scannerComingSoon() {
  if (!can('product.create')) {
    toast('Ton rôle ne permet pas de créer un produit.');
    return;
  }

  $('catalogCameraInput').click();
}

async function imageFileToJpeg(file) {
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(
      new Error('Impossible de lire la photo.')
    );

    reader.readAsDataURL(file);
  });

  const image = await new Promise((resolve, reject) => {
    const element = new Image();

    element.onload = () => resolve(element);
    element.onerror = () => reject(
      new Error('Format de photo non lisible.')
    );

    element.src = dataUrl;
  });

  const maxSide = 1600;
  const ratio = Math.min(
    1,
    maxSide / Math.max(image.width, image.height),
  );

  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(image.width * ratio));
  canvas.height = Math.max(1, Math.round(image.height * ratio));

  const context = canvas.getContext('2d');
  context.drawImage(
    image,
    0,
    0,
    canvas.width,
    canvas.height,
  );

  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error('Impossible de préparer la photo.'));
      },
      'image/jpeg',
      0.86,
    );
  });
}

function setSmartCatalogStatus(message) {
  const status = $('catalogScanStatus');
  status.textContent = message;
  status.hidden = !message;
}

async function analyzeCatalogPhoto(file) {
  setSmartCatalogStatus('Analyse du produit en cours…');
  toast('Whatzabi analyse le produit…');

  const jpeg = await imageFileToJpeg(file);

  const form = new FormData();
  form.append('image', jpeg, 'whatzabi-product.jpg');

  const response = await fetch('/pwa/catalog/analyze', {
    method: 'POST',
    headers: {
      Authorization: 'Bearer ' + token,
    },
    body: form,
  });

  let body = null;
  try {
    body = await response.json();
  } catch {}

  if (response.status === 401) {
    logout();
    throw new Error('Session expirée');
  }

  if (!response.ok) {
    throw new Error(
      body?.detail || 'Impossible d’analyser le produit.',
    );
  }

  if (body.status === 'unresolved' || !body.candidate?.name) {
    throw new Error(
      body.message || 'Produit non reconnu. Reprends une photo.',
    );
  }

  if (body.existing_product) {
    showTab('products');
    setSmartCatalogStatus(
      `Déjà au catalogue : ${body.existing_product.name}.`,
    );
    toast(`Produit déjà présent : ${body.existing_product.name}`);
    return;
  }

  const candidate = body.candidate;

  $('productName').value = candidate.name || '';
  $('productUnit').value = candidate.unit || 'unité';
  $('productType').value = candidate.product_type || '';
  $('productBrand').value = candidate.brand || '';
  $('productVariant').value = candidate.variant || '';
  $('productPackaging').value = candidate.packaging || '';

  const confidence = Math.round(
    Number(candidate.confidence || 0) * 100,
  );

  const details = [
    candidate.brand,
    candidate.variant,
    candidate.packaging,
    candidate.barcode
      ? `code-barres ${candidate.barcode}`
      : null,
  ].filter(Boolean);

  const sourceLabel =
    candidate.source === 'barcode_public'
      ? 'code-barres'
      : 'analyse visuelle';

  setSmartCatalogStatus(
    `Reconnu par ${sourceLabel} — confiance ${confidence}%`
    + (details.length ? ` — ${details.join(' · ')}` : '')
    + '. Vérifie les informations, complète prix et stock, puis ajoute le produit.',
  );

  showTab('products');

  $('productCreateCard').scrollIntoView({
    behavior: 'smooth',
    block: 'start',
  });

  toast(`Produit proposé : ${candidate.name}`);
}



$('catalogCameraInput').addEventListener('change', async (event) => {
  const file = event.target.files?.[0];

  // Permet de rescanner ensuite exactement le même fichier.
  event.target.value = '';

  if (!file) return;

  try {
    await analyzeCatalogPhoto(file);
  } catch (error) {
    setSmartCatalogStatus(error.message);
    showTab('products');
    toast(error.message);
  }
});

$('quickAddPurchase').addEventListener('click', () => {
  toast('Module achats : interface PWA à brancher');
});

$('moreSuppliers').addEventListener('click', () => {
  toast('Fournisseurs : interface PWA à brancher');
});

$('morePurchases').addEventListener('click', () => {
  toast('Achats : interface PWA à brancher');
});

$('moreFinancial').addEventListener('click', () => {
  showTab('activity');
});

$('moreCalculator').addEventListener('click', () => {
  toast('Calculatrice Whatzabi : à brancher');
});

$('moreSettings').addEventListener('click', () => {
  toast('Paramètres : à brancher');
});

let voiceRecorder = null;
let voiceStream = null;
let voiceChunks = [];
let voiceMimeType = '';

function openVoiceSheet() {
  $('voiceSheet').hidden = false;
  $('voiceTranscriptBox').hidden = true;
  $('voiceReviewActions').hidden = true;
  $('voiceRecordBtn').hidden = false;
  $('voiceRecordBtn').textContent = '🎙️ Commencer';
  $('voiceStatus').textContent = 'Appuie sur le micro et parle naturellement.';
  $('voiceTranscript').textContent = '';
  $('voiceOrb').classList.remove('recording');
}

function cleanupVoiceStream() {
  if (voiceStream) {
    voiceStream.getTracks().forEach((track) => track.stop());
    voiceStream = null;
  }
}

function closeVoiceSheet() {
  if (voiceRecorder && voiceRecorder.state === 'recording') {
    voiceRecorder.stop();
  }
  cleanupVoiceStream();
  $('voiceSheet').hidden = true;
}

function preferredVoiceMimeType() {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
  ];

  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || '';
}

async function startVoiceRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    toast('Le micro n’est pas disponible sur ce navigateur.');
    return;
  }

  try {
    voiceStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    voiceChunks = [];
    voiceMimeType = preferredVoiceMimeType();

    voiceRecorder = voiceMimeType
      ? new MediaRecorder(voiceStream, { mimeType: voiceMimeType })
      : new MediaRecorder(voiceStream);

    voiceRecorder.addEventListener('dataavailable', (event) => {
      if (event.data && event.data.size > 0) {
        voiceChunks.push(event.data);
      }
    });

    voiceRecorder.addEventListener('stop', sendVoiceRecording);

    voiceRecorder.start();

    $('voiceStatus').textContent = 'J’écoute…';
    $('voiceRecordBtn').textContent = '⏹ Terminer';
    $('voiceOrb').classList.add('recording');
  } catch (error) {
    cleanupVoiceStream();
    $('voiceStatus').textContent = 'Impossible d’accéder au microphone.';
    toast('Autorise l’accès au microphone pour utiliser l’assistant vocal.');
  }
}

function stopVoiceRecording() {
  if (!voiceRecorder || voiceRecorder.state !== 'recording') return;

  $('voiceStatus').textContent = 'Transcription en cours…';
  $('voiceRecordBtn').disabled = true;
  $('voiceOrb').classList.remove('recording');

  voiceRecorder.stop();
}

async function sendVoiceRecording() {
  cleanupVoiceStream();

  const actualType =
    voiceRecorder?.mimeType ||
    voiceMimeType ||
    'audio/webm';

  const blob = new Blob(voiceChunks, { type: actualType });

  if (!blob.size) {
    $('voiceStatus').textContent = 'Aucun son enregistré.';
    $('voiceRecordBtn').disabled = false;
    $('voiceRecordBtn').textContent = '🎙️ Recommencer';
    return;
  }

  const extension = actualType.includes('mp4') ? 'm4a' : 'webm';

  const form = new FormData();
  form.append('audio', blob, `whatzabi-voice.${extension}`);

  try {
    const response = await fetch('/pwa/voice/transcribe', {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + token,
      },
      body: form,
    });

    let body = null;
    try {
      body = await response.json();
    } catch {}

    if (response.status === 401) {
      logout();
      throw new Error('Session expirée');
    }

    if (!response.ok) {
      throw new Error(body?.detail || 'Impossible de transcrire le vocal');
    }

    $('voiceTranscript').textContent = body.text;
    $('voiceTranscriptBox').hidden = false;
    $('voiceStatus').textContent = 'Vérifie ce que j’ai compris.';
    $('voiceRecordBtn').disabled = false;
    $('voiceRecordBtn').hidden = true;
    $('voiceReviewActions').hidden = false;
  } catch (error) {
    $('voiceStatus').textContent = error.message;
    $('voiceRecordBtn').hidden = false;
    $('voiceRecordBtn').disabled = false;
    $('voiceRecordBtn').textContent = '🎙️ Recommencer';
  }
}

$('voiceNavBtn').addEventListener('click', openVoiceSheet);

$('voiceCloseBtn').addEventListener('click', closeVoiceSheet);

$('voiceCancelBtn').addEventListener('click', closeVoiceSheet);

$('voiceRetryBtn').addEventListener('click', () => {
  $('voiceTranscriptBox').hidden = true;
  $('voiceReviewActions').hidden = true;
  $('voiceRecordBtn').hidden = false;
  $('voiceRecordBtn').disabled = false;
  $('voiceRecordBtn').textContent = '🎙️ Commencer';
  $('voiceStatus').textContent = 'Appuie sur le micro et parle naturellement.';
});

const VOICE_QUANTITIES = {
  un: 1,
  une: 1,
  deux: 2,
  trois: 3,
  quatre: 4,
  cinq: 5,
  six: 6,
  sept: 7,
  huit: 8,
  neuf: 9,
  dix: 10,
  onze: 11,
  douze: 12,
  treize: 13,
  quatorze: 14,
  quinze: 15,
  seize: 16,
  vingt: 20,
};

const VOICE_STOPWORDS = new Set([
  'je',
  'j',
  'ai',
  'vendu',
  'vends',
  'vendre',
  'vente',
  'mets',
  'mettre',
  'ajoute',
  'ajouter',
  'enregistre',
  'enregistrer',
  'de',
  'du',
  'des',
  'le',
  'la',
  'les',
  'un',
  'une',
  'deux',
  'trois',
  'quatre',
  'cinq',
  'six',
  'sept',
  'huit',
  'neuf',
  'dix',
  'onze',
  'douze',
]);

function normalizeVoiceText(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9\s'-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function extractVoiceQuantity(text) {
  const tokens = normalizeVoiceText(text).split(' ').filter(Boolean);

  for (const token of tokens) {
    if (/^\d+$/.test(token)) {
      const value = Number(token);
      if (Number.isFinite(value) && value > 0) return value;
    }

    if (VOICE_QUANTITIES[token]) {
      return VOICE_QUANTITIES[token];
    }
  }

  return 1;
}

function voiceMeaningfulTokens(value) {
  return normalizeVoiceText(value)
    .split(' ')
    .filter(
      (token) =>
        token.length >= 2 &&
        !VOICE_STOPWORDS.has(token) &&
        !/^\d+$/.test(token),
    );
}

function voiceProductScore(transcript, product) {
  const normalizedTranscript = normalizeVoiceText(transcript);
  const normalizedName = normalizeVoiceText(product?.name);

  if (!normalizedName) return 0;

  // Le nom complet du catalogue apparaît dans le vocal.
  if (normalizedTranscript.includes(normalizedName)) {
    return 100 + normalizedName.length;
  }

  const transcriptTokens = voiceMeaningfulTokens(transcript);
  const productTokens = voiceMeaningfulTokens(product?.name);

  let score = 0;

  for (const productToken of productTokens) {
    for (const spokenToken of transcriptTokens) {
      if (spokenToken === productToken) {
        score += 10;
        break;
      }

      // Ex: "coca" peut reconnaître "coca-cola".
      if (
        spokenToken.length >= 4 &&
        productToken.length >= 4 &&
        (
          spokenToken.startsWith(productToken) ||
          productToken.startsWith(spokenToken)
        )
      ) {
        score += 6;
        break;
      }
    }
  }

  return score;
}

function findVoiceProductCandidates(transcript) {
  return (Array.isArray(state.products) ? state.products : [])
    .map((product) => ({
      product,
      score: voiceProductScore(transcript, product),
    }))
    .filter((candidate) => candidate.score > 0)
    .sort((a, b) => b.score - a.score);
}

function showVoiceProblem(message) {
  $('voiceStatus').textContent = message;
  $('voiceStatus').scrollIntoView({
    behavior: 'smooth',
    block: 'nearest',
  });
}


function splitVoiceSaleSegments(transcript) {
  const normalized = String(transcript || '')
    .replace(/\s+(?:et|puis|avec)\s+/gi, ' | ')
    .replace(/[;,]+/g, ' | ');

  return normalized
    .split('|')
    .map((part) => part.trim())
    .filter(Boolean);
}

function resolveVoiceSegment(segment) {
  const quantity = extractVoiceQuantity(segment);
  const candidates = findVoiceProductCandidates(segment);

  if (!candidates.length) {
    return {
      ok: false,
      reason: `Produit introuvable : « ${segment} ».`,
    };
  }

  const best = candidates[0];
  const second = candidates[1];

  if (second && second.score === best.score) {
    const names = candidates
      .filter((candidate) => candidate.score === best.score)
      .slice(0, 3)
      .map((candidate) => candidate.product.name)
      .join(', ');

    return {
      ok: false,
      reason: `Plusieurs produits possibles pour « ${segment} » : ${names}.`,
    };
  }

  if (!Number.isFinite(quantity) || quantity < 1) {
    return {
      ok: false,
      reason: `Quantité non comprise pour « ${segment} ».`,
    };
  }

  return {
    ok: true,
    product: best.product,
    quantity,
  };
}

function resolveVoiceSale(transcript) {
  const segments = splitVoiceSaleSegments(transcript);
  const resolved = [];

  for (const segment of segments) {
    const result = resolveVoiceSegment(segment);
    if (!result.ok) return result;

    const existing = resolved.find(
      (line) => Number(line.product.id) === Number(result.product.id)
    );

    if (existing) {
      existing.quantity += result.quantity;
    } else {
      resolved.push({
        product: result.product,
        quantity: result.quantity,
      });
    }
  }

  return {
    ok: resolved.length > 0,
    lines: resolved,
    reason: resolved.length ? null : 'Aucun produit compris.',
  };
}

$('voiceContinueBtn').addEventListener('click', () => {
  const transcript = $('voiceTranscript').textContent.trim();

  if (!transcript) {
    showVoiceProblem('Je n’ai aucun texte à traiter. Recommence le vocal.');
    return;
  }

  if (!can('sale.create')) {
    showVoiceProblem('Ton rôle ne permet pas d’enregistrer une vente.');
    return;
  }

  const resolution = resolveVoiceSale(transcript);

  if (!resolution.ok) {
    showVoiceProblem(resolution.reason || 'Je n’ai pas compris la vente.');
    return;
  }

  if (typeof window.whatzabiExpressAddVoiceLines !== 'function') {
    showVoiceProblem('Le panier Vente Express est indisponible.');
    return;
  }

  try {
    const lines = resolution.lines.map((line) => ({
      product_id: line.product.id,
      quantity: line.quantity,
    }));

    const result = window.whatzabiExpressAddVoiceLines(lines);

    closeVoiceSheet();

    if (typeof window.whatzabiExpressOpen === 'function') {
      window.whatzabiExpressOpen();
    } else {
      showTab('sales');
    }

    const summary = resolution.lines
      .map((line) => `${line.quantity} × ${line.product.name}`)
      .join(' · ');

    toast(
      'Vente vocale prête : ' + summary +
      (result?.total != null ? ' · Total ' + fmt(result.total) : '')
    );
  } catch (error) {
    showVoiceProblem(error?.message || 'Impossible de préparer la vente vocale.');
  }
});

$('voiceRecordBtn').addEventListener('click', () => {
  if (voiceRecorder && voiceRecorder.state === 'recording') {
    stopVoiceRecording();
  } else {
    startVoiceRecording();
  }
});
