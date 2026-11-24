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

function fmtSaleDate(value) {
  if (!value) return 'Date indisponible';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('fr-FR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

function fmtDueDate(value) {
  if (!value) return 'Sans échéance';
  const date = new Date(value + 'T00:00:00');
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('fr-FR', { dateStyle: 'medium' }).format(date);
}

function localDateKey(date = new Date()) {
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  return yyyy + '-' + mm + '-' + dd;
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
    'supplier.read',
    'supplier.create',
    'purchase.read',
    'purchase.create',
    'purchase.cancel',
    'supplier_payment.create',
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
    'supplier.read',
    'purchase.read',
    'purchase.create',
  ],
  ACCOUNTANT: [
    'sale.read',
    'stock.read',
    'product.read',
    'customer.read',
    'supplier.read',
    'purchase.read',
    'supplier_payment.create',
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
  if ($('quickAddPurchase')) {
    $('quickAddPurchase').hidden = !can('purchase.create');
  }
}

let token = localStorage.getItem('whatzabi_token') || '';
let state = {
  products: [],
  customers: [],
  sales: [],
  expenses: [],
  expensePeriod: 'month',
  merchant: null,
  shops: [],
  currencyContext: null,
  finance: null,
  financePeriod: 'month',
};
let editingProductId = null;
let invoiceDraftQueue = [];
let invoiceDraftPosition = 0;

async function api(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (token) {
    headers.Authorization = 'Bearer ' + token;
  }

  /*
   * Une erreur levée directement par fetch() correspond
   * à une vraie erreur réseau : elle n'est volontairement
   * pas transformée ici.
   */
  const response = await fetch(
    path,
    {
      ...options,
      headers,
    }
  );

  let body = null;

  try {
    body = await response.json();
  } catch {}

  if (!response.ok) {
    const detail =
      typeof body?.detail === 'string'
        ? body.detail
        : (
            body?.detail
              ? JSON.stringify(body.detail)
              : 'Erreur serveur'
          );

    const error = new Error(
      response.status === 401 &&
      path !== '/auth/login'
        ? 'Session expirée'
        : detail
    );

    error.status = response.status;
    error.isHttpError = true;
    error.body = body;

    if (
      response.status === 401 &&
      path !== '/auth/login'
    ) {
      logout();
    }

    throw error;
  }

  return body;
}

function toast(message) {
  const element = $('toast');
  element.textContent = message;
  element.hidden = false;
  setTimeout(() => (element.hidden = true), 2500);
}

function showTab(name) {
  if (
    name === 'stockIntelligence' &&
    !stockIntelligenceLoading &&
    (
      !stockIntelligenceData ||
      stockIntelligenceShopKey !== String(state.merchant?.shop_id)
    )
  ) {
    void loadStockIntelligence();
  }

  document.querySelectorAll('.panel').forEach((element) =>
    element.classList.toggle('active', element.id === name),
  );
  document.querySelectorAll('.tabs [data-tab]').forEach((element) =>
    element.classList.toggle('active', element.dataset.tab === name),
  );
}



const FINANCE_PERIOD_LABELS = {
  today: "Aujourd'hui",
  week: 'Cette semaine',
  month: 'Ce mois',
  all: 'Toutes les données',
};

function financePercent(value) {
  const number = Number(value || 0);

  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(number) + ' %';
}

function setFinanceStatus(message = '', isError = false) {
  const element = $('financeStatus');
  if (!element) return;

  if (!message) {
    element.hidden = true;
    element.textContent = '';
    element.classList.remove('finance-status-error');
    return;
  }

  element.hidden = false;
  element.textContent = message;
  element.classList.toggle(
    'finance-status-error',
    Boolean(isError),
  );
}

function renderFinancePeriodButtons() {
  document
    .querySelectorAll('[data-finance-period]')
    .forEach((button) => {
      button.classList.toggle(
        'active',
        button.dataset.financePeriod ===
          state.financePeriod,
      );
    });
}

function renderFinanceOverview(data) {
  if (!data) return;

  const activity = data.activity || {};
  const cashflow = data.cashflow || {};
  const receivables = data.receivables || {};
  const payables = data.payables || {};
  const stock = data.stock || {};
  const position = data.position || {};

  if ($('financeShopName')) {
    $('financeShopName').textContent =
      state.merchant?.active_shop_name ||
      state.merchant?.shop_name ||
      'Boutique active';
  }

  $('financeRevenue').textContent =
    fmt(activity.sales_total);

  $('financeGrossMargin').textContent =
    fmt(activity.gross_margin);

  $('financeMarginRate').textContent =
    financePercent(activity.gross_margin_rate);

  $('financeSalesPaid').textContent =
    fmt(activity.sales_paid);

  $('financeReceivables').textContent =
    fmt(receivables.total);

  $('financeOverdue').textContent =
    fmt(receivables.overdue) + ' en retard';

  $('financePayables').textContent =
    fmt(payables.total);

  $('financeExpenses').textContent =
    fmt(cashflow.expenses_total);

  $('financeCashflow').textContent =
    fmt(cashflow.net_cash_flow);

  $('financeStockValue').textContent =
    fmt(stock.value);

  $('financePotentialSales').textContent =
    fmt(stock.potential_sales_value);

  $('financeAssets').textContent =
    fmt(position.estimated_current_assets);

  $('financeLiabilities').textContent =
    fmt(position.estimated_current_liabilities);

  $('financeNetPosition').textContent =
    fmt(position.estimated_net_position);

  $('financePeriodLabel').textContent =
    FINANCE_PERIOD_LABELS[data.period] ||
    FINANCE_PERIOD_LABELS[state.financePeriod] ||
    'Période';

  renderFinancePeriodButtons();
}

let financeRequestId = 0;
function invalidateFinanceOverview() {
  financeRequestId++;
  state.finance = null;
  for (const id of ['financeShopName', 'financeRevenue', 'financeGrossMargin',
    'financeMarginRate', 'financeSalesPaid', 'financeReceivables', 'financeOverdue',
    'financePayables', 'financeExpenses', 'financeCashflow', 'financeStockValue',
    'financePotentialSales', 'financeAssets', 'financeLiabilities', 'financeNetPosition']) {
    if ($(id)) $(id).textContent = '—';
  }
  setFinanceStatus();
}

async function loadFinanceOverview(
  period = state.financePeriod || 'month',
) {
  if (!can('report.read')) {
    toast(
      "Tu n'as pas accès à l'analyse financière."
    );
    showTab('more');
    return;
  }

  invalidateFinanceOverview();
  const requestId = financeRequestId;
  const origin = {token, merchant:state.merchant?.id, shop:state.merchant?.shop_id};
  const current = () => requestId === financeRequestId && origin.token === token &&
    origin.merchant === state.merchant?.id && origin.shop === state.merchant?.shop_id;
  state.financePeriod = period;
  renderFinancePeriodButtons();

  setFinanceStatus(
    "Chargement de l'analyse financière…"
  );

  try {
    const data = await api(
      '/pwa/finance/overview?period=' +
        encodeURIComponent(period),
      {cache:'no-store'},
    );

    if (!current()) return;
    state.finance = data;
    renderFinanceOverview(data);
    setFinanceStatus();
  } catch (error) {
    if (!current()) return;
    console.error(
      'Finance overview error:',
      error
    );

    setFinanceStatus(
      error.message ||
        "Impossible de charger l'analyse financière.",
      true,
    );
  }
}

function resetProductForm() {
  editingProductId = null;
  $('productForm').reset();
  $('productStock').disabled = false;
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

  $('productStock').disabled = true;

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
      stock: Number(existing.stock || 0),
    });

    $('productStock').disabled = true;

    $('productFormTitle').textContent =
      'Facture · Réapprovisionner ' + existing.name;

    $('productSubmitBtn').textContent =
      quantity > 0
        ? `Valider et ajouter ${quantity} au stock`
        : 'Valider la ligne et continuer';
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
      ? (
          quantity > 0
            ? `${quantity} ${existing.unit || 'unité'} seront ajoutés au stock après validation.`
            : 'Aucune quantité positive à ajouter au stock.'
        )
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
  state = { products: [], customers: [], sales: [], merchant: null, shops: [], currencyContext: null, finance: null, financePeriod: 'month' };
  $('appView').hidden = true;
  $('loginView').hidden = false;

  if ($('offlineSyncBadge')) {
    $('offlineSyncBadge').hidden = true;
  }
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

function normalizeProductSearch(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase('fr')
    .trim();
}


function render() {
  const activeStockShop = state.merchant?.shop_id;
  if (
    activeStockShop &&
    stockIntelligenceShopKey !== String(activeStockShop) &&
    !stockIntelligenceLoading
  ) {
    void loadStockIntelligence(true);
  }

  const products = state.products;
  const customers = state.customers;
  const sales = state.sales;

  const validSales = sales.filter(
    (sale) => String(sale.status) !== 'cancelled',
  );

  renderIdentity();
  renderPermissions();
  renderCurrencyPanel();

  const revenue = validSales.reduce(
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

  const lowStockProducts = products.filter((product) => {
    const stock = Number(product.stock || 0);
    const threshold = Number(product.threshold || 0);

    return stock <= 0 || (threshold > 0 && stock <= threshold);
  });

  $('statRevenue').textContent = fmt(revenue);
  $('statSales').textContent = validSales.length;
  $('statDebt').textContent = fmt(customerDebt);
  $('statDebtCustomers').textContent =
    customersWithDebt + (customersWithDebt > 1 ? ' clients' : ' client');
  // KPI désormais alimenté par Stock Intelligent V1.

  if ($('criticalStockCount')) {
    $('criticalStockCount').textContent =
      lowStockProducts.length +
      (lowStockProducts.length > 1 ? ' produits' : ' produit');
  }

  if ($('criticalStockItems')) {
    $('criticalStockItems').innerHTML = lowStockProducts.length
      ? lowStockProducts
          .sort((a, b) => {
            const stockA = Number(a.stock || 0);
            const stockB = Number(b.stock || 0);

            if (stockA !== stockB) return stockA - stockB;

            return String(a.name || '').localeCompare(
              String(b.name || ''),
              'fr',
            );
          })
          .map((product) => {
            const stock = Number(product.stock || 0);
            const threshold = Number(product.threshold || 0);

            const status = stock <= 0
              ? '<span class="stock-state stock-out">Rupture</span>'
              : '<span class="stock-state stock-low">Faible</span>';

            return `<article class="activity-row">
              <div>
                <strong>${esc(product.name)}</strong>
                <span>Stock ${stock} ${esc(product.unit)} · seuil configuré ${threshold}</span>
              </div>
              ${status}
            </article>`;
          })
          .join('')
      : '<p class="muted empty-state">Aucune alerte selon les seuils configurés.</p>';
  }

  $('activityRevenue').textContent = fmt(revenue);
  $('activityDebt').textContent = fmt(customerDebt);

  $('recentActivity').innerHTML = sales.length
    ? sales
        .slice(0, 4)
        .map(
          (sale) => `<button type="button" class="recent-row sale-row-button" data-sale-actions="${sale.id}">
            <div>
              <strong>Vente #${sale.sale_number ?? sale.id}</strong>
              <span>${esc(sale.status)} · ${esc(fmtSaleDate(sale.created_at))}</span>
              <small class="sale-payment-summary">
                Total ${fmt(sale.total_amount)} ·
                Payé ${fmt(sale.paid_amount)} ·
                Reste ${fmt(sale.remaining_amount)}
              </small>
            </div>
            <strong>${fmt(sale.total_amount)}</strong>
          </button>`,
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
          (sale) => `<button type="button" class="activity-row sale-row-button" data-sale-actions="${sale.id}">
            <div>
              <strong>Vente #${sale.sale_number ?? sale.id}</strong>
              <span>${esc(sale.status)} · ${esc(fmtSaleDate(sale.created_at))}</span>
            </div>
            <strong>${fmt(sale.total_amount)}</strong>
          </button>`,
        )
        .join('')
    : '<p class="muted empty-state">Aucune vente.</p>';

  const productSearchValue = normalizeProductSearch(
    $('productSearch')?.value || '',
  );

  const filteredProducts = productSearchValue
    ? products.filter((product) => {
        const searchable = normalizeProductSearch([
          product.name,
          product.brand,
          product.variant,
          product.packaging,
          product.unit,
        ].filter(Boolean).join(' '));

        return searchable.includes(productSearchValue);
      })
    : products;

  if ($('productSearchCount')) {
    $('productSearchCount').textContent =
      filteredProducts.length +
      (filteredProducts.length > 1 ? ' produits' : ' produit');
  }

  $('productList').innerHTML = filteredProducts.length
    ? filteredProducts
        .map(
          (product) => `<article class="item product-stock-row">
            <div class="item-main">
              <div class="item-title">${esc(product.name)}</div>
              <div class="item-meta">
                Stock boutique: ${product.stock} ${esc(product.unit)}
                · Seuil: ${product.threshold}
              </div>
            </div>

            <div class="product-stock-end">
              <div class="money">${fmt(product.price)}</div>

              ${can('product.update') ? `
                <div class="product-stock-actions">
                  <button
                    type="button"
                    class="primary product-stock-action"
                    data-restock-product="${product.id}"
                  >
                    Réapprovisionner
                  </button>

                  <button
                    type="button"
                    class="ghost product-stock-action"
                    data-edit-product="${product.id}"
                  >
                    Modifier
                  </button>
                </div>
              ` : ''}
            </div>
          </article>`,
        )
        .join('')
    : (
        productSearchValue
          ? '<article class="card muted">Aucun produit trouvé.</article>'
          : '<article class="card muted">Aucun produit.</article>'
      );


  const todayKey = localDateKey();
  const receivables = sales
    .filter((sale) =>
      Number(sale.remaining_amount || 0) > 0 &&
      String(sale.status) !== 'cancelled' &&
      sale.customer_id != null
    )
    .sort((a, b) => {
      const dueA = a.due_date || '9999-12-31';
      const dueB = b.due_date || '9999-12-31';
      if (dueA !== dueB) return dueA.localeCompare(dueB);
      return Number(b.id) - Number(a.id);
    });

  const overdue = receivables.filter((sale) => sale.due_date && sale.due_date < todayKey);
  const dueToday = receivables.filter((sale) => sale.due_date === todayKey);
  const upcoming = receivables.filter((sale) => !sale.due_date || sale.due_date > todayKey);
  const receivableTotal = receivables.reduce(
    (sum, sale) => sum + Number(sale.remaining_amount || 0),
    0,
  );

  if ($('receivableTotal')) $('receivableTotal').textContent = fmt(receivableTotal);
  if ($('receivableOverdue')) $('receivableOverdue').textContent = fmt(
    overdue.reduce((sum, sale) => sum + Number(sale.remaining_amount || 0), 0)
  );
  if ($('receivableToday')) $('receivableToday').textContent = fmt(
    dueToday.reduce((sum, sale) => sum + Number(sale.remaining_amount || 0), 0)
  );
  if ($('receivableUpcoming')) $('receivableUpcoming').textContent = fmt(
    upcoming.reduce((sum, sale) => sum + Number(sale.remaining_amount || 0), 0)
  );

  if ($('receivableList')) {
    $('receivableList').innerHTML = receivables.length
      ? receivables.map((sale) => {
          const customer = customers.find(
            (item) => Number(item.id) === Number(sale.customer_id)
          );
          const overdueSale = sale.due_date && sale.due_date < todayKey;
          const dueTodaySale = sale.due_date === todayKey;
          const dueState = overdueSale
            ? '<span class="receivable-state receivable-overdue">En retard</span>'
            : dueTodaySale
              ? '<span class="receivable-state receivable-today">Aujourd’hui</span>'
              : '<span class="receivable-state receivable-upcoming">À venir</span>';

          return `
            <article class="receivable-row">
              <div class="receivable-main">
                <div class="receivable-title">
                  <strong>${esc(customer?.name || 'Client')}</strong>
                  ${dueState}
                </div>
                <span>Vente #${sale.sale_number ?? sale.id} · échéance ${esc(fmtDueDate(sale.due_date))}</span>
                <small>Total ${fmt(sale.total_amount)} · payé ${fmt(sale.paid_amount)}</small>
              </div>
              <div class="receivable-end">
                <strong>${fmt(sale.remaining_amount)}</strong>
                ${can('payment.create')
                  ? `<button type="button" class="primary receivable-pay-btn" data-receivable-pay="${sale.id}">Enregistrer paiement</button>`
                  : ''}
              </div>
            </article>
          `;
        }).join('')
      : '<p class="muted empty-state">Aucune créance ouverte.</p>';
  }

  $('customerList').innerHTML = customers.length
    ? customers
        .map((customer) => {
          const debt = Number(customer.debt || 0);
          return `<article class="item">
            <div class="item-main">
              <div class="item-title">${esc(customer.name)}</div>
              <div class="item-meta">${esc(customer.phone || 'Sans téléphone')}</div>
            </div>
            ${debt > 0 && can('payment.create')
              ? `<button type="button" class="debt-link" data-customer-debt="${customer.id}">Dette ${fmt(debt)} ›</button>`
              : `<div class="money">Dette ${fmt(debt)}</div>`}
          </article>`;
        })
        .join('')
    : '<article class="card muted">Aucun client.</article>';

  $('saleList').innerHTML = sales.length
    ? sales
        .map(
          (sale) => `<button type="button" class="item sale-item-button" data-sale-actions="${sale.id}">
            <div class="item-main">
              <div class="item-title">Vente #${sale.sale_number ?? sale.id}</div>
              <div class="item-meta"><span class="badge">${esc(sale.status)}</span> · ${esc(fmtSaleDate(sale.created_at))} · payé ${fmt(sale.paid_amount)}</div>
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
    fmtSaleDate(sale.created_at) + ' · ' +
    saleStatusLabel(sale.status) + ' · ' +
    fmt(sale.total_amount);

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
    const shareLines = (items || []).map((item) => {
      const product = state.products.find(
        (entry) => Number(entry.id) === Number(item.product_id)
      );
      const name = product?.name || ('Produit #' + item.product_id);
      return item.quantity + ' × ' + name + ' — ' + fmt(item.line_total);
    });
    const receiptShareText = [
      shopName,
      'Reçu de vente #' + receiptNumber,
      'Date : ' + fmtSaleDate(sale.created_at),
      'Client : ' + (customer?.name || 'Vente comptoir'),
      '',
      ...shareLines,
      '',
      'Total : ' + fmt(sale.total_amount),
      'Payé : ' + fmt(sale.paid_amount),
      'Reste : ' + fmt(sale.remaining_amount),
      'Statut : ' + saleStatusLabel(sale.status),
      '',
      'Généré par Whatzabi'
    ].join('\n');

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
          <div><strong>Date :</strong> ${receiptEscape(fmtSaleDate(sale.created_at))}</div>
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
          <button onclick="shareReceipt()">Partager le reçu</button>
          <button onclick="window.print()">Imprimer / Enregistrer en PDF</button>
          <button onclick="window.close()">Fermer le reçu</button>
        </div>

        <script>
          const RECEIPT_SHARE_TEXT = ${JSON.stringify(receiptShareText)};
          const RECEIPT_FILE_NAME =
            'recu-whatzabi-${String(receiptNumber).replace(/[^a-zA-Z0-9_-]/g, '-')}.html';

          async function shareReceipt() {
            const shareButton = document.querySelector(
              '.actions button:first-child'
            );
            const previousLabel = shareButton ? shareButton.textContent : '';

            try {
              if (shareButton) shareButton.textContent = 'Préparation…';

              const html =
                '<!doctype html>\\n' +
                document.documentElement.outerHTML;
              const file = new File(
                [html],
                RECEIPT_FILE_NAME,
                { type: 'text/html' }
              );

              if (
                navigator.share &&
                navigator.canShare &&
                navigator.canShare({ files: [file] })
              ) {
                await navigator.share({
                  title: 'Reçu Whatzabi #${receiptEscape(receiptNumber)}',
                  text: RECEIPT_SHARE_TEXT,
                  files: [file]
                });
                return;
              }

              if (navigator.share) {
                await navigator.share({
                  title: 'Reçu Whatzabi #${receiptEscape(receiptNumber)}',
                  text: RECEIPT_SHARE_TEXT
                });
                return;
              }

              if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(RECEIPT_SHARE_TEXT);
                alert('Reçu copié. Tu peux maintenant le coller dans WhatsApp, SMS ou e-mail.');
                return;
              }

              alert('Le partage natif n’est pas disponible sur cet appareil.');
            } catch (error) {
              if (error?.name !== 'AbortError') {
                alert('Impossible de partager le reçu.');
              }
            } finally {
              if (shareButton) shareButton.textContent = previousLabel;
            }
          }
        </script>
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


let selectedReceivableSaleId = null;

function openReceivablePayment(saleId) {
  const sale = state.sales.find((item) => Number(item.id) === Number(saleId));
  if (!sale || Number(sale.remaining_amount || 0) <= 0) {
    toast('Créance introuvable ou déjà soldée.');
    return;
  }

  const customer = state.customers.find(
    (item) => Number(item.id) === Number(sale.customer_id)
  );

  selectedReceivableSaleId = sale.id;
  $('receivablePaymentTitle').textContent =
    'Paiement · ' + (customer?.name || 'Client');
  $('receivablePaymentMeta').textContent =
    'Vente #' + (sale.sale_number ?? sale.id) +
    ' · reste ' + fmt(sale.remaining_amount) +
    ' · échéance ' + fmtDueDate(sale.due_date) +
    ' · paiement partiel possible';
  $('receivablePaymentAmount').value = String(sale.remaining_amount);
  $('receivablePaymentAmount').max = String(sale.remaining_amount);
  $('receivablePaymentReference').value = '';
  $('receivablePaymentSheet').hidden = false;
}

function closeReceivablePayment() {
  $('receivablePaymentSheet').hidden = true;
  selectedReceivableSaleId = null;
}

async function submitReceivablePayment() {
  const sale = state.sales.find(
    (item) => Number(item.id) === Number(selectedReceivableSaleId)
  );
  if (!sale) {
    toast('Créance introuvable.');
    return;
  }

  const amount = Number($('receivablePaymentAmount').value);
  if (!Number.isFinite(amount) || amount <= 0) {
    toast('Montant de paiement invalide.');
    return;
  }
  if (amount > Number(sale.remaining_amount || 0)) {
    toast('Le paiement dépasse le reste dû.');
    return;
  }

  const button = $('receivablePaymentSubmitBtn');
  button.disabled = true;
  try {
    await api('/pwa/payments', {
      method: 'POST',
      body: JSON.stringify({
        sale_id: sale.id,
        customer_id: sale.customer_id,
        amount,
        channel: $('receivablePaymentChannel').value,
        reference: $('receivablePaymentReference').value.trim() || null,
      }),
    });

    closeReceivablePayment();
    await refresh();
    toast(
      amount === Number(sale.remaining_amount || 0)
        ? 'Créance soldée.'
        : 'Paiement enregistré. Créance mise à jour.'
    );
  } catch (error) {
    toast(error.message || 'Impossible d’enregistrer le paiement.');
  } finally {
    button.disabled = false;
  }
}

function openCustomerDebtPayment(customerId) {
  const customer = state.customers.find(
    (item) => Number(item.id) === Number(customerId)
  );
  const openSales = state.sales
    .filter((sale) =>
      Number(sale.customer_id) === Number(customerId) &&
      Number(sale.remaining_amount || 0) > 0 &&
      String(sale.status) !== 'cancelled'
    )
    .sort((a, b) => {
      const dueA = a.due_date || '9999-12-31';
      const dueB = b.due_date || '9999-12-31';
      if (dueA !== dueB) return dueA.localeCompare(dueB);
      return Number(a.id) - Number(b.id);
    });

  if (!openSales.length) {
    toast('Aucune créance ouverte pour ce client.');
    return;
  }

  showTab('customers');
  openReceivablePayment(openSales[0].id);

  if (openSales.length > 1) {
    toast(
      (customer?.name || 'Client') +
      ' a ' + openSales.length +
      ' créances ouvertes. Le paiement commence par la plus ancienne.'
    );
  }
}

document.addEventListener('click', (event) => {
  const debtButton = event.target.closest('[data-customer-debt]');
  if (debtButton) {
    openCustomerDebtPayment(debtButton.dataset.customerDebt);
    return;
  }

  const payButton = event.target.closest('[data-receivable-pay]');
  if (payButton) {
    openReceivablePayment(payButton.dataset.receivablePay);
  }
});

$('receivablePaymentCloseBtn')?.addEventListener('click', closeReceivablePayment);
$('receivablePaymentSubmitBtn')?.addEventListener('click', submitReceivablePayment);

async function selectShop(shopId, { silent = false } = {}) {
  const data = await api('/auth/select-shop', {
    method: 'POST',
    body: JSON.stringify({ shop_id: Number(shopId) }),
  });
  token = data.access_token;
  localStorage.setItem('whatzabi_token', token);
  state.merchant = data.merchant;

  // Invalider immédiatement les indicateurs de l'ancienne boutique.
  invalidateFinanceOverview();
  stockIntelligenceRequestId++;
  stockIntelligenceData = null;
  stock360Data = null;
  stock360ShowAll = false;
  stockIntelligenceShopKey = null;
  stockIntelligenceLoading = false;

  if ($('statLowStock')) $('statLowStock').textContent = '—';
  if ($('statStockInsight')) {
    $('statStockInsight').textContent = 'Actualisation du stock…';
  }
  if ($('stockIntelligenceList')) {
    $('stockIntelligenceList').innerHTML = '';
  }

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

  const previousShop = state.merchant?.shop_id;
  const previousMerchant = state.merchant?.id;

  state.merchant = merchant;
  state.shops = shops;

  if (String(previousShop) !== String(merchant.shop_id) || previousMerchant !== merchant.id) {
    invalidateFinanceOverview();
    stockIntelligenceRequestId++;
    stockIntelligenceData = null;
    stockIntelligenceShopKey = null;
    stockIntelligenceLoading = false;

    if ($('statLowStock')) {
      $('statLowStock').textContent = '—';
    }
    if ($('statStockInsight')) {
      $('statStockInsight').textContent = 'Actualisation du stock…';
    }
    if ($('stockIntelligenceList')) {
      $('stockIntelligenceList').innerHTML = '';
    }
  }
}

async function updateOfflineSyncBadge() {
  const badge = $('offlineSyncBadge');

  if (!badge) return;

  const manager =
    window.WhatzabiOfflineSales;

  const merchantId =
    state.merchant?.id;

  if (!manager || !merchantId) {
    badge.hidden = true;
    return;
  }

  try {
    const queue =
      await manager.summary(
        merchantId
      );

    badge.hidden = false;

    badge.classList.remove(
      'is-offline',
      'has-pending',
      'has-conflict',
      'has-blocked'
    );

    if (!navigator.onLine) {
      badge.classList.add(
        'is-offline'
      );

      badge.textContent =
        queue.pending > 0
          ? (
              'Hors ligne · ' +
              queue.pending +
              (
                queue.pending > 1
                  ? ' ventes en attente'
                  : ' vente en attente'
              )
            )
          : 'Hors ligne';

      return;
    }

    if (queue.conflict > 0) {
      badge.classList.add(
        'has-conflict'
      );

      badge.textContent =
        queue.conflict +
        (
          queue.conflict > 1
            ? ' ventes à vérifier'
            : ' vente à vérifier'
        );

      return;
    }

    if (queue.blocked > 0) {
      badge.classList.add(
        'has-blocked'
      );

      badge.textContent =
        queue.blocked +
        (
          queue.blocked > 1
            ? ' ventes bloquées'
            : ' vente bloquée'
        );

      return;
    }

    if (queue.pending > 0) {
      badge.classList.add(
        'has-pending'
      );

      badge.textContent =
        queue.pending +
        (
          queue.pending > 1
            ? ' ventes à synchroniser'
            : ' vente à synchroniser'
        );

      return;
    }

    badge.textContent = 'En ligne';
  } catch {
    badge.hidden = true;
  }
}


let offlineSyncUiRunning = false;


async function syncOfflineSales() {
  const manager =
    window.WhatzabiOfflineSales;

  if (
    offlineSyncUiRunning ||
    !manager ||
    !token ||
    !state.merchant?.id ||
    !navigator.onLine
  ) {
    await updateOfflineSyncBadge();
    return;
  }

  offlineSyncUiRunning = true;

  try {
    const result =
      await manager.sync();

    await updateOfflineSyncBadge();

    if (result?.synced > 0) {
      const count =
        Number(result.synced);

      /*
       * La vente synchronisée modifie le stock,
       * les ventes et potentiellement les créances.
       * On recharge donc le contexte serveur.
       *
       * refresh() ne rappelle pas syncOfflineSales(),
       * ce qui évite une boucle.
       */
      await refresh();

      toast(
        count +
        (
          count > 1
            ? ' ventes hors ligne synchronisées'
            : ' vente hors ligne synchronisée'
        )
      );

      await updateOfflineSyncBadge();
    }

    if (result?.conflicts > 0) {
      toast(
        result.conflicts +
        (
          result.conflicts > 1
            ? ' ventes hors ligne sont à vérifier'
            : ' vente hors ligne est à vérifier'
        )
      );
    }

    if (result?.blocked > 0) {
      toast(
        result.blocked +
        (
          result.blocked > 1
            ? ' ventes hors ligne sont bloquées'
            : ' vente hors ligne est bloquée'
        )
      );
    }
  } finally {
    offlineSyncUiRunning = false;
  }
}


window.addEventListener(
  'offline',
  () => {
    void updateOfflineSyncBadge();
  }
);


window.addEventListener(
  'online',
  () => {
    window.setTimeout(
      () => {
        void syncOfflineSales();
      },
      500
    );
  }
);


window.addEventListener(
  'whatzabi:offline-sales-changed',
  () => {
    void updateOfflineSyncBadge();
  }
);


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

  if (
    typeof window.whatzabiExpressRefreshFrequentProducts ===
    'function'
  ) {
    await window.whatzabiExpressRefreshFrequentProducts();
  }

  /*
   * Les dépenses ne sont chargées que pour les rôles disposant
   * de report.read. Un vendeur ne doit donc pas faire échouer refresh().
   */
  if (canReadExpenses()) {
    await Promise.all([
      loadExpenses(),
      loadHomeExpenseMetric(),
    ]);
  } else {
    state.expenses = [];
    renderExpenses();
  }
  if (state.finance && can('report.read')) {
    await loadFinanceOverview(state.financePeriod || 'month');
  }
}

async function boot() {
  if (!token) return;
  try {
    await refresh();
    $('loginView').hidden = true;
    $('appView').hidden = false;

    await updateOfflineSyncBadge();
    await syncOfflineSales();
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

    await updateOfflineSyncBadge();
    await syncOfflineSales();
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

    await updateOfflineSyncBadge();
    await syncOfflineSales();
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

    const targetId = button.dataset.scrollTarget;
    if (targetId) {
      requestAnimationFrame(() => {
        document.getElementById(targetId)?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        });
      });
    }
  }),
);


let restockProductId = null;

function closeProductRestock() {
  restockProductId = null;

  if ($('productRestockCard')) {
    $('productRestockCard').hidden = true;
  }

  if ($('productRestockForm')) {
    $('productRestockForm').reset();
  }

  if ($('productRestockQuantity')) {
    $('productRestockQuantity').value = '1';
  }
}

function openProductRestock(productId) {
  if (!can('product.update')) {
    toast('Ton rôle ne permet pas de réapprovisionner un produit.');
    return;
  }

  const product = state.products.find(
    (item) => Number(item.id) === Number(productId)
  );

  if (!product) {
    toast('Produit introuvable dans la boutique active.');
    return;
  }

  restockProductId = product.id;

  $('productRestockTitle').textContent =
    'Réapprovisionner ' + product.name;

  $('productRestockCurrent').textContent =
    'Stock actuel : ' +
    Number(product.stock || 0) +
    ' ' +
    (product.unit || 'unité');

  $('productRestockQuantity').value = '1';

  $('productRestockPurchasePrice').value =
    String(Number(product.purchase_price || 0));

  $('productRestockNote').value = '';

  $('productRestockCard').hidden = false;

  showTab('products');

  $('productRestockCard').scrollIntoView({
    behavior: 'smooth',
    block: 'start',
  });

  $('productRestockQuantity').focus();
}

$('productSearch')?.addEventListener(
  'input',
  () => render(),
);


document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-restock-product]');
  if (!button) return;

  openProductRestock(
    Number(button.dataset.restockProduct)
  );
});

$('productRestockCloseBtn')?.addEventListener(
  'click',
  closeProductRestock,
);

$('productRestockForm')?.addEventListener(
  'submit',
  async (event) => {
    event.preventDefault();

    if (!restockProductId) {
      toast('Produit introuvable.');
      return;
    }

    const quantity = Number(
      $('productRestockQuantity').value || 0
    );

    const purchasePrice = Number(
      $('productRestockPurchasePrice').value || 0
    );

    const note = String(
      $('productRestockNote').value || ''
    ).trim();

    if (!Number.isInteger(quantity) || quantity <= 0) {
      toast('Saisis une quantité entière supérieure à zéro.');
      return;
    }

    const button = $('productRestockSubmitBtn');

    try {
      button.disabled = true;
      button.textContent = 'Ajout au stock…';

      const product = await api(
        `/pwa/products/${restockProductId}/restock`,
        {
          method: 'POST',
          body: JSON.stringify({
            quantity,
            purchase_price: purchasePrice,
            note: note || null,
            source: 'manual',
          }),
        },
      );

      closeProductRestock();
      await refresh();

      toast(
        `Stock mis à jour : ${product.name} · ` +
        `${product.stock} ${product.unit}`
      );
    } catch (error) {
      toast(
        error.message ||
        'Réapprovisionnement impossible.'
      );
    } finally {
      button.disabled = false;
      button.textContent = 'Ajouter au stock';
    }
  },
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
  sessionStorage.removeItem('whatzabi_product_form_barcode');
  sessionStorage.removeItem('whatzabi_pending_barcode');
  sessionStorage.removeItem('whatzabi_catalog_selected');
  setSmartCatalogStatus('');
  if (hadInvoiceQueue) toast('Traitement de la facture annulé.');
});

$('productForm').addEventListener('submit', async (event) => {
  event.preventDefault();

  const wasEditing = editingProductId !== null;

  const processingInvoice = invoiceDraftQueue.length > 0;
  const currentInvoiceItem = processingInvoice
    ? invoiceDraftQueue[invoiceDraftPosition]
    : null;

  const invoiceCandidate =
    currentInvoiceItem?.candidate || currentInvoiceItem || null;

  const invoiceExistingProductId = Number(
    currentInvoiceItem?.existing_product_id || 0
  );

  const invoiceRestockQuantity = Math.max(
    0,
    Number(invoiceCandidate?.quantity || 0)
  );

  const payload = {
    name: $('productName').value,
    product_type: $('productType').value || null,
    brand: $('productBrand').value || null,
    variant: $('productVariant').value || null,
    packaging: $('productPackaging').value || null,
    unit: $('productUnit').value,
    price: Number($('productPrice').value),
    purchase_price: Number($('productPurchasePrice').value),
    threshold: Number($('productThreshold').value),
  };

  if (!wasEditing) {
    payload.stock = Number($('productStock').value);
  }
  const path = wasEditing
    ? `/pwa/products/${editingProductId}`
    : '/pwa/products';

  const normalizedNewName = normalizeProductSearch(payload.name);

  const existingProduct = state.products.find(
    (product) =>
      Number(product.id) !== Number(editingProductId) &&
      normalizeProductSearch(product.name) === normalizedNewName
  );

  if (existingProduct) {
    toast(
      `Produit déjà présent : ${existingProduct.name}. ` +
      'Utilise sa fiche existante.'
    );

    const existingProductElement =
      document.querySelector(
        `[data-restock-product="${existingProduct.id}"]`
      );

    existingProductElement?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    });

    return;
  }

  try {
    const savedProduct = await api(path, {
      method: wasEditing ? 'PATCH' : 'POST',
      body: JSON.stringify(payload),
    });

    const invoiceLineCount = invoiceDraftQueue.length;

    if (
      processingInvoice &&
      wasEditing &&
      invoiceExistingProductId > 0 &&
      invoiceRestockQuantity > 0
    ) {
      await api(
        `/pwa/products/${savedProduct.id}/restock`,
        {
          method: 'POST',
          body: JSON.stringify({
            quantity: invoiceRestockQuantity,
            purchase_price: Number(
              $('productPurchasePrice').value || 0
            ),
            note:
              'Réapprovisionnement depuis justificatif fournisseur',
            source: 'invoice',
          }),
        },
      );
    }

    const pendingBarcode = wasEditing
      ? ''
      : String(
          sessionStorage.getItem('whatzabi_product_form_barcode') || ''
        ).trim();

    if (pendingBarcode && savedProduct?.id) {
      const response = await fetch(
        '/pwa/catalog/barcode/' +
          encodeURIComponent(pendingBarcode) +
          '/associate',
        {
          method: 'POST',
          headers: {
            Authorization: 'Bearer ' + token,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            product_id: Number(savedProduct.id),
          }),
        },
      );

      let barcodeBody = null;
      try {
        barcodeBody = await response.json();
      } catch {}

      if (!response.ok) {
        sessionStorage.removeItem('whatzabi_product_form_barcode');
        sessionStorage.removeItem('whatzabi_pending_barcode');
        sessionStorage.removeItem('whatzabi_catalog_selected');

        resetProductForm();
        setSmartCatalogStatus('');
        await refresh();

        toast(
          'Produit créé, mais le code-barres n’a pas pu être associé. ' +
          'Rescanne le code pour terminer l’association.'
        );
        return;
      }

      sessionStorage.removeItem('whatzabi_product_form_barcode');
      sessionStorage.removeItem('whatzabi_pending_barcode');
      sessionStorage.removeItem('whatzabi_catalog_selected');
    }

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

$('quickAddPurchase')?.addEventListener('click', () => {
  showTab('purchases');
});

$('moreFinancial').addEventListener('click', async () => {
  if (!can('report.read')) {
    toast(
      "Tu n'as pas accès à l'analyse financière."
    );
    return;
  }

  showTab('finance');
  await loadFinanceOverview(
    state.financePeriod || 'month'
  );
});


document
  .querySelectorAll('[data-finance-period]')
  .forEach((button) => {
    button.addEventListener('click', async () => {
      const period =
        button.dataset.financePeriod || 'month';

      await loadFinanceOverview(period);
    });
  });

$('financeRefreshBtn')?.addEventListener(
  'click',
  async () => {
    await loadFinanceOverview(
      state.financePeriod || 'month'
    );
  },
);

$('moreCalculator').addEventListener('click', () => {
  toast('Calculatrice Whatzabi : à brancher');
});

function setSettingsStatus(message = '', isError = false) {
  const element = $('settingsStatus');
  if (!element) return;

  element.hidden = !message;
  element.textContent = message;
  element.classList.toggle('settings-error', Boolean(isError));
}

async function loadCommerceSettings() {
  setSettingsStatus('Chargement…');

  try {
    const data = await api('/pwa/settings/commerce');

    $('settingsBusinessName').value = data.shop_name || '';
    $('settingsBusinessType').value =
      data.business_type || 'general_retail';

    const country = data.country_code || '';
    const countrySelect = $('settingsCountry');

    if (
      [...countrySelect.options].some(
        (option) => option.value === country
      )
    ) {
      countrySelect.value = country;
    } else {
      countrySelect.value = 'OTHER';
    }

    $('settingsActiveShop').textContent =
      data.active_shop_name || '—';

    $('settingsShopName').textContent =
      data.active_shop_name || 'Boutique active';

    $('settingsCurrency').textContent =
      data.currency_code || '—';

    $('settingsWhatsapp').value =
      data.whatsapp_number || '';

    $('settingsAddress').value =
      data.active_shop_address || '';

    const editable =
      ['OWNER', 'MANAGER'].includes(
        String(data.role || '').toUpperCase()
      );

    $('settingsBusinessName').disabled = !editable;
    $('settingsBusinessType').disabled = !editable;
    $('settingsCountry').disabled = !editable;
    $('settingsAddress').disabled = !editable;
    $('settingsSaveBtn').hidden = !editable;

    setSettingsStatus(
      editable
        ? ''
        : 'Consultation uniquement : modification réservée au propriétaire ou au manager.'
    );
  } catch (error) {
    setSettingsStatus(
      error.message || 'Impossible de charger les paramètres.',
      true
    );
  }
}

$('moreSettings').addEventListener('click', async () => {
  showTab('settings');
  await loadCommerceSettings();
});

$('commerceSettingsForm')?.addEventListener(
  'submit',
  async (event) => {
    event.preventDefault();

    const button = $('settingsSaveBtn');
    button.disabled = true;
    setSettingsStatus('Enregistrement…');

    try {
      const data = await api(
        '/pwa/settings/commerce',
        {
          method: 'PATCH',
          body: JSON.stringify({
            shop_name:
              $('settingsBusinessName').value.trim(),
            business_type:
              $('settingsBusinessType').value,
            country_code:
              $('settingsCountry').value,
            active_shop_address:
              $('settingsAddress').value.trim() || null,
          }),
        }
      );

      if (state.merchant) {
        state.merchant.shop_name = data.shop_name;
      }

      setSettingsStatus('✓ Paramètres enregistrés.');
      toast('Paramètres enregistrés');

      await loadCommerceSettings();
    } catch (error) {
      setSettingsStatus(
        error.message || "Échec de l'enregistrement.",
        true
      );
    } finally {
      button.disabled = false;
    }
  }
);

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

  const normalizedTranscript = transcript
    .toLocaleLowerCase('fr')
    .trim();

  const explicitSaleCommand =
    /^(ajoute|ajouter|mets|mettre|vends|vendre)\b/i
      .test(normalizedTranscript);

  const leadingQuantity =
    /^(?:\d+|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze)\s+/i
      .test(normalizedTranscript);

  const explicitSearchCommand =
    /^(cherche|recherche|trouve|affiche|montre(?:-moi)?)\b/i
      .test(normalizedTranscript);

  const voiceSearch =
    explicitSearchCommand ||
    (!explicitSaleCommand && !leadingQuantity);

  if (voiceSearch) {
    if (
      typeof window.whatzabiExpressVoiceSearch !== 'function'
    ) {
      showVoiceProblem(
        'La recherche vocale Vente Express est indisponible.'
      );
      return;
    }

    try {
      const result =
        window.whatzabiExpressVoiceSearch(transcript);

      closeVoiceSheet();

      toast(
        `Recherche vocale : ${result.query}` +
        (
          result.result_count != null
            ? ` · ${result.result_count} résultat${
                result.result_count > 1 ? 's' : ''
              }`
            : ''
        )
      );

      return;
    } catch (error) {
      showVoiceProblem(
        error?.message ||
        'Impossible de lancer la recherche vocale.'
      );
      return;
    }
  }

  if (!can('sale.create')) {
    showVoiceProblem(
      'Ton rôle ne permet pas d’enregistrer une vente.'
    );
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

/* =========================================================
   WHATZABI — PWA EXPENSES
   ========================================================= */

const EXPENSE_CATEGORY_LABELS = {
  transport: 'Transport',
  loyer: 'Loyer',
  electricite: 'Électricité',
  salaire: 'Salaire',
  carburant: 'Carburant',
  livraison: 'Livraison',
  fournitures: 'Fournitures',
  taxes: 'Taxes',
  autre: 'Autre',
};

const EXPENSE_CHANNEL_LABELS = {
  cash: 'Espèces',
  mtn_momo: 'MTN MoMo',
  moov_money: 'Moov Money',
  bank: 'Banque',
};

function canReadExpenses() {
  return can('report.read');
}

function canCreateExpense() {
  return ['OWNER', 'MANAGER'].includes(
    String(state.merchant?.role || '').toUpperCase()
  );
}

function expenseDate(entry) {
  if (!entry?.created_at) return null;
  const date = new Date(entry.created_at);
  return Number.isNaN(date.getTime()) ? null : date;
}

function expenseMatchesPeriod(entry, period) {
  if (period === 'all') return true;

  const date = expenseDate(entry);
  if (!date) return false;

  const now = new Date();

  if (period === 'today') {
    return localDateKey(date) === localDateKey(now);
  }

  if (period === 'week') {
    const start = new Date(now);
    const day = start.getDay() || 7;
    start.setDate(start.getDate() - day + 1);
    start.setHours(0, 0, 0, 0);

    return date >= start && date <= now;
  }

  return (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth()
  );
}

function filteredExpenses() {
  return (state.expenses || []).filter((entry) =>
    expenseMatchesPeriod(entry, state.expensePeriod || 'month')
  );
}

function renderExpenses() {
  const panel = $('expenses');
  if (!panel) return;

  const allowed = canReadExpenses();
  panel.dataset.allowed = allowed ? 'true' : 'false';

  if ($('expensesShopName')) {
    $('expensesShopName').textContent =
      state.merchant?.active_shop_name ||
      state.merchant?.shop_name ||
      'Boutique active';
  }

  if ($('expenseAddBtn')) {
    $('expenseAddBtn').hidden = !canCreateExpense();
  }

  if ($('quickAddExpense')) {
    $('quickAddExpense').hidden = !canCreateExpense();
  }

  if ($('moreExpenses')) {
    $('moreExpenses').hidden = !allowed;
  }

  if ($('statExpensesCard')) {
    $('statExpensesCard').hidden = !allowed;
  }

  document.querySelectorAll('[data-expense-period]').forEach((button) => {
    button.classList.toggle(
      'active',
      button.dataset.expensePeriod === (state.expensePeriod || 'month')
    );
  });

  if (!allowed) return;

  const rows = filteredExpenses();

  const total = rows.reduce(
    (sum, entry) => sum + Number(entry.amount || 0),
    0
  );

  if ($('expensesTotal')) {
    $('expensesTotal').textContent = fmt(total);
  }

  if ($('expensesCount')) {
    $('expensesCount').textContent =
      rows.length + (rows.length > 1 ? ' dépenses' : ' dépense');
  }

  const list = $('expensesList');
  if (!list) return;

  list.innerHTML = rows.length
    ? rows.map((entry) => {
        const category =
          EXPENSE_CATEGORY_LABELS[entry.category] ||
          entry.category ||
          'Autre';

        const channel =
          EXPENSE_CHANNEL_LABELS[entry.channel] ||
          entry.channel ||
          '—';

        const date = expenseDate(entry);

        const formattedDate = date
          ? new Intl.DateTimeFormat('fr-FR', {
              dateStyle: 'medium',
              timeStyle: 'short',
            }).format(date)
          : 'Date indisponible';

        return `
          <article class="expense-row">
            <div class="expense-row-main">
              <span class="expense-category">${esc(category)}</span>
              <strong>${esc(entry.label || 'Dépense')}</strong>
              <small>${esc(channel)} · ${esc(formattedDate)}</small>
              ${
                entry.note
                  ? `<small class="expense-note">${esc(entry.note)}</small>`
                  : ''
              }
            </div>
            <strong class="expense-amount">− ${fmt(entry.amount)}</strong>
          </article>
        `;
      }).join('')
    : '<p class="muted empty-state">Aucune dépense sur cette période.</p>';
}

async function loadExpenses() {
  if (!canReadExpenses()) {
    state.expenses = [];
    renderExpenses();
    return;
  }

  state.expenses = await api('/pwa/expenses');
  renderExpenses();
}

async function loadHomeExpenseMetric() {
  if (!canReadExpenses()) {
    if ($('statExpensesCard')) $('statExpensesCard').hidden = true;
    return;
  }

  try {
    const finance = await api('/pwa/finance/overview?period=month');

    if ($('statExpenses')) {
      $('statExpenses').textContent =
        fmt(finance?.cashflow?.expenses_total || 0);
    }
  } catch (error) {
    console.warn('KPI dépenses indisponible', error);
  }
}


let expenseScanFile = null;
let expenseScanPreviewUrl = null;

const EXPENSE_SCAN_ALLOWED_CATEGORIES = new Set([
  'transport',
  'loyer',
  'electricite',
  'salaire',
  'carburant',
  'livraison',
  'fournitures',
  'taxes',
  'autre',
]);

const EXPENSE_SCAN_ALLOWED_CHANNELS = new Set([
  'cash',
  'mtn_momo',
  'moov_money',
  'bank',
]);

function setExpenseScanStatus(message = '', kind = '') {
  const box = $('expenseScanStatus');
  if (!box) return;

  if (!message) {
    box.hidden = true;
    box.textContent = '';
    box.className = 'expense-scan-status';
    return;
  }

  box.hidden = false;
  box.textContent = message;
  box.className = `expense-scan-status${kind ? ` ${kind}` : ''}`;
}

function clearExpenseScan() {
  expenseScanFile = null;

  if (expenseScanPreviewUrl) {
    URL.revokeObjectURL(expenseScanPreviewUrl);
    expenseScanPreviewUrl = null;
  }

  const previewBox = $('expenseScanPreviewBox');
  const preview = $('expenseScanPreview');

  if (previewBox) previewBox.hidden = true;

  if (preview) {
    preview.removeAttribute('src');
  }

  if ($('expenseScanCameraInput')) {
    $('expenseScanCameraInput').value = '';
  }

  if ($('expenseScanGalleryInput')) {
    $('expenseScanGalleryInput').value = '';
  }

  setExpenseScanStatus();
}

function selectExpenseScanFile(file) {
  if (!file) return;

  if (!String(file.type || '').startsWith('image/')) {
    setExpenseScanStatus(
      'Sélectionne une photo de reçu ou de facture.',
      'error'
    );
    return;
  }

  if (file.size > 12 * 1024 * 1024) {
    setExpenseScanStatus(
      'La photo est trop volumineuse. Maximum : 12 Mo.',
      'error'
    );
    return;
  }

  clearExpenseScan();
  expenseScanFile = file;
  expenseScanPreviewUrl = URL.createObjectURL(file);

  const preview = $('expenseScanPreview');
  const previewBox = $('expenseScanPreviewBox');

  if (preview) preview.src = expenseScanPreviewUrl;
  if (previewBox) previewBox.hidden = false;

  setExpenseScanStatus(
    'Photo prête. Appuie sur « Analyser le justificatif ».',
    'ready'
  );
}

async function prepareExpenseScanImage(file) {
  /*
   * Même principe que Smart Catalog :
   * on réduit la photo avant l'envoi pour accélérer l'analyse sur mobile.
   * Si la préparation échoue, on arrête l’analyse au lieu d’envoyer
   * un fichier potentiellement incompatible avec Safari/iPhone.
   */
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });

    const image = await new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = dataUrl;
    });

    const maxSide = 1600;
    const scale = Math.min(
      1,
      maxSide / Math.max(image.naturalWidth, image.naturalHeight)
    );

    const width = Math.max(1, Math.round(image.naturalWidth * scale));
    const height = Math.max(1, Math.round(image.naturalHeight * scale));

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;

    const context = canvas.getContext('2d');

    if (!context) {
      throw new Error('Impossible de préparer cette image.');
    }

    context.drawImage(image, 0, 0, width, height);

    const blob = await new Promise((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', 0.8);
    });

    if (!blob) {
      throw new Error('Impossible de convertir cette image en JPEG.');
    }

    return new File(
      [blob],
      'depense.jpg',
      { type: 'image/jpeg' }
    );
  } catch (error) {
    console.warn('Compression justificatif impossible', error);
    throw new Error(
      'Cette photo ne peut pas être préparée pour l’analyse. ' +
      'Réessaie avec une photo JPEG ou prends une nouvelle photo.'
    );
  }
}

function applyExpenseScanResult(result) {
  if (!result) return;

  if (result.amount != null && Number(result.amount) > 0) {
    $('expenseAmount').value = String(result.amount);
  }

  if (
    result.category &&
    EXPENSE_SCAN_ALLOWED_CATEGORIES.has(result.category)
  ) {
    $('expenseCategory').value = result.category;
  } else {
    $('expenseCategory').value = 'autre';
  }

  if (result.merchant_name) {
    $('expenseLabel').value = String(result.merchant_name).slice(0, 100);
  }

  /*
   * Important :
   * si le ticket ne prouve pas le moyen de paiement,
   * on laisse volontairement "À préciser".
   */
  if (
    result.payment_channel &&
    EXPENSE_SCAN_ALLOWED_CHANNELS.has(result.payment_channel)
  ) {
    $('expenseChannel').value = result.payment_channel;
  } else {
    $('expenseChannel').value = '';
  }

  const noteParts = [];

  if (result.note) {
    noteParts.push(String(result.note));
  }

  if (result.reference) {
    noteParts.push(`Réf. ${result.reference}`);
  }

  if (noteParts.length) {
    $('expenseNote').value = noteParts.join(' · ').slice(0, 255);
  }

  const details = [];

  if (result.document_date) {
    details.push(`Date lue : ${result.document_date}`);
  }

  if (result.currency) {
    details.push(`Devise : ${result.currency}`);
  }

  if (Number.isFinite(Number(result.confidence))) {
    details.push(
      `Confiance : ${Math.round(Number(result.confidence) * 100)} %`
    );
  }

  const suffix = details.length
    ? ` ${details.join(' · ')}.`
    : '';

  setExpenseScanStatus(
    `Analyse terminée.${suffix} Vérifie les champs puis enregistre la dépense.`,
    'success'
  );

  $('expenseAmount')?.focus();
}

async function analyzeExpenseScan() {
  if (!expenseScanFile) {
    setExpenseScanStatus(
      'Prends ou sélectionne d’abord une photo.',
      'error'
    );
    return;
  }

  const button = $('expenseScanAnalyzeBtn');

  try {
    if (button) {
      button.disabled = true;
      button.textContent = 'Analyse en cours…';
    }

    setExpenseScanStatus(
      'Lecture du reçu ou de la facture…',
      'loading'
    );

    const preparedFile = await prepareExpenseScanImage(expenseScanFile);
    const formData = new FormData();

    formData.append(
      'image',
      preparedFile,
      preparedFile.name || 'depense.jpg'
    );

    const token = localStorage.getItem('whatzabi_token');

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 45000);

    let response;

    try {
      response = await fetch('/pwa/expenses/scan', {
        method: 'POST',
        headers: token
          ? { Authorization: `Bearer ${token}` }
          : {},
        body: formData,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeoutId);
    }

    let payload = null;

    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }

    if (!response.ok) {
      throw new Error(
        payload?.detail ||
        'Impossible d’analyser le justificatif.'
      );
    }

    applyExpenseScanResult(payload?.result || {});
  } catch (error) {
    let message =
      error?.message ||
      'Analyse du justificatif impossible.';

    if (
      error?.name === 'AbortError' ||
      /load failed|failed to fetch|network/i.test(message)
    ) {
      message =
        'Impossible d’envoyer le justificatif. ' +
        'Vérifie la connexion puis réessaie.';
    }

    setExpenseScanStatus(
      message,
      'error'
    );
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = '✨ Analyser le justificatif';
    }
  }
}

function openExpenseForm() {
  if (!canCreateExpense()) {
    toast("Vous n'avez pas l'autorisation d'enregistrer une dépense.");
    return;
  }

  showTab('expenses');

  if ($('expenseFormCard')) {
    $('expenseFormCard').hidden = false;
  }

  if ($('expenseFormError')) {
    $('expenseFormError').textContent = '';
  }

  setTimeout(() => $('expenseAmount')?.focus(), 50);
}

function closeExpenseForm() {
  clearExpenseScan();

  if ($('expenseFormCard')) {
    $('expenseFormCard').hidden = true;
  }

  if ($('expenseFormError')) {
    $('expenseFormError').textContent = '';
  }
}

async function submitExpense(event) {
  event.preventDefault();

  const error = $('expenseFormError');
  if (error) error.textContent = '';

  const amount = Number($('expenseAmount')?.value || 0);
  const label = String($('expenseLabel')?.value || '').trim();
  const category = String($('expenseCategory')?.value || 'autre');
  const channel = String($('expenseChannel')?.value || '');
  const note = String($('expenseNote')?.value || '').trim();

  if (!Number.isFinite(amount) || amount <= 0) {
    if (error) error.textContent = 'Saisis un montant supérieur à zéro.';
    return;
  }

  if (!label) {
    if (error) error.textContent = 'Le libellé est obligatoire.';
    return;
  }

  if (!channel) {
    if (error) error.textContent = 'Choisis le mode de paiement.';
    return;
  }

  const button = $('expenseSubmitBtn');

  try {
    if (button) {
      button.disabled = true;
      button.textContent = 'Enregistrement…';
    }

    await api('/pwa/expenses', {
      method: 'POST',
      body: JSON.stringify({
        entry_type: 'expense',
        amount: Math.round(amount),
        channel,
        label,
        category,
        note: note || null,
      }),
    });

    $('expenseForm')?.reset();
    clearExpenseScan();
    closeExpenseForm();

    await Promise.all([
      loadExpenses(),
      loadHomeExpenseMetric(),
    ]);

    /*
     * Si Finance a déjà été ouverte, on recharge également son overview
     * afin que Dépenses / Flux net soient immédiatement cohérents.
     */
    if (typeof loadFinanceOverview === 'function' && state.finance) {
      await loadFinanceOverview(state.financePeriod || 'month');
    }

    toast('Dépense enregistrée');
  } catch (err) {
    if (error) {
      error.textContent = err.message || "Impossible d'enregistrer la dépense.";
    }
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = 'Enregistrer la dépense';
    }
  }
}

$('expenseScanCameraInput')?.addEventListener('change', (event) => {
  selectExpenseScanFile(event.target.files?.[0] || null);
});

$('expenseScanGalleryInput')?.addEventListener('change', (event) => {
  selectExpenseScanFile(event.target.files?.[0] || null);
});

$('expenseScanAnalyzeBtn')?.addEventListener('click', analyzeExpenseScan);
$('expenseScanClearBtn')?.addEventListener('click', clearExpenseScan);

$('quickAddExpense')?.addEventListener('click', openExpenseForm);
$('expenseAddBtn')?.addEventListener('click', openExpenseForm);
$('expenseFormCloseBtn')?.addEventListener('click', closeExpenseForm);
$('expenseForm')?.addEventListener('submit', submitExpense);

$('expensesRefreshBtn')?.addEventListener('click', async () => {
  try {
    await loadExpenses();
    toast('Dépenses actualisées');
  } catch (error) {
    toast(error.message || 'Actualisation impossible');
  }
});

document.querySelectorAll('[data-expense-period]').forEach((button) => {
  button.addEventListener('click', () => {
    state.expensePeriod = button.dataset.expensePeriod || 'month';
    renderExpenses();
  });
});


/* STOCK INTELLIGENT V1 */

let stock360Data = null;
let stock360ShowAll = false;
const STOCK_360_INITIAL_LIMIT = 20;

function stock360Number(value) {
  return new Intl.NumberFormat('fr-FR').format(
    Number(value || 0)
  );
}

function stock360Signed(value) {
  const number = Number(value || 0);

  if (number > 0) {
    return '+' + stock360Number(number);
  }

  return stock360Number(number);
}

function stock360TrafficLight(value) {
  if (value === 'red') {
    return {
      icon: '🔴',
      label: 'Urgent',
      css: 'is-red',
    };
  }

  if (value === 'orange') {
    return {
      icon: '🟠',
      label: 'Attention',
      css: 'is-orange',
    };
  }

  return {
    icon: '🟢',
    label: 'Sain',
    css: 'is-green',
  };
}

function stock360HasActivity(item) {
  const initial = Number(item.initial_stock || 0);
  const current = Number(item.current_stock || 0);

  const movements =
    Math.abs(Number(item.purchase_in || 0))
    + Math.abs(Number(item.restock_in || 0))
    + Math.abs(Number(item.other_entries || 0))
    + Math.abs(Number(item.sale_out || 0))
    + Math.abs(Number(item.other_exits || 0))
    + Math.abs(Number(item.adjustments || 0));

  return initial > 0 || current > 0 || movements > 0;
}


function stock360EffectiveTraffic(item) {
  if (!stock360HasActivity(item)) {
    return 'gray';
  }

  return item.traffic_light || 'green';
}


function stock360InitialDisplay(item) {
  if (!stock360HasActivity(item)) {
    return 'ND';
  }

  return stock360Number(item.initial_stock);
}


function stock360MovementDisplay(value, negative = false) {
  const number = Number(value || 0);

  if (number === 0) {
    return '·';
  }

  return negative
    ? `-${stock360Number(Math.abs(number))}`
    : stock360Number(number);
}


function renderStock360() {
  const body = $('stock360Body');

  if (!body) return;

  if (!stock360Data) {
    body.innerHTML = `
      <tr>
        <td colspan="11">
          Données Stock 360 indisponibles.
        </td>
      </tr>
    `;
    return;
  }

  const summary = stock360Data.summary || {};
  const items = stock360Data.items || [];

  const visibleItems =
    stock360ShowAll
      ? items
      : items.slice(0, STOCK_360_INITIAL_LIMIT);

  const negativeInitialCount = items.filter(
    item => Number(item.initial_stock || 0) < 0
  ).length;

  const toggle = $('stock360Toggle');

  if (toggle) {
    toggle.hidden =
      items.length <= STOCK_360_INITIAL_LIMIT;

    toggle.textContent =
      stock360ShowAll
        ? 'Voir moins'
        : (
            'Voir les autres produits'
            + (
                items.length > STOCK_360_INITIAL_LIMIT
                  ? ` (${items.length - STOCK_360_INITIAL_LIMIT})`
                  : ''
              )
          );
  }

  const note = $('stock360Note');

  if (note) {
    if (negativeInitialCount > 0) {
      note.textContent =
        '* Stock initial estimé à partir du stock actuel'
        + ' et des mouvements connus. '
        + `${negativeInitialCount} ouverture`
        + `${negativeInitialCount > 1 ? 's ont' : ' a'}`
        + ' été ramenée'
        + `${negativeInitialCount > 1 ? 's' : ''}`
        + ' à 0 car l’historique disponible ne permet pas'
        + ' de reconstituer une valeur initiale fiable.';
    } else {
      note.textContent =
        '* Stock initial estimé à partir du stock actuel'
        + ' et des mouvements connus.';
    }
  }

  const red = items.filter(
    item => stock360EffectiveTraffic(item) === 'red'
  ).length;

  const orange = items.filter(
    item => stock360EffectiveTraffic(item) === 'orange'
  ).length;
  const alerts = red + orange;

  if ($('stock360Alerts')) {
    $('stock360Alerts').textContent =
      String(alerts);
  }

  if ($('stock360AlertsDetail')) {
    $('stock360AlertsDetail').textContent =
      `${red} rouge${red > 1 ? 's' : ''}`
      + ` · ${orange} orange${orange > 1 ? 's' : ''}`;
  }

  if ($('stock360CostValue')) {
    $('stock360CostValue').textContent =
      fmt(summary.cost_value || 0);
  }

  if ($('stock360RetailValue')) {
    $('stock360RetailValue').textContent =
      fmt(summary.retail_value || 0);
  }

  if ($('stock360Margin')) {
    $('stock360Margin').textContent =
      fmt(summary.potential_margin || 0);
  }

  if (!items.length) {
    body.innerHTML = `
      <tr>
        <td colspan="11">
          Aucun produit dans cette boutique.
        </td>
      </tr>
    `;
    return;
  }

  body.innerHTML = visibleItems.map(item => {
    const light =
      stock360TrafficLight(item.traffic_light);

    const entries =
      Number(item.purchase_in || 0)
      + Number(item.restock_in || 0)
      + Number(item.other_entries || 0);

    const otherExits =
      Number(item.other_exits || 0);

    const adjustment =
      Number(item.adjustments || 0);

    const cover =
      item.days_of_cover == null
        ? '—'
        : (
            new Intl.NumberFormat(
              'fr-FR',
              {
                maximumFractionDigits: 1,
              }
            ).format(
              Number(item.days_of_cover)
            )
            + ' j'
          );

    return `
      <tr class="stock-360-row ${light.css}">
        <td class="stock-360-light">
          <span
            title="${esc(light.label)}"
            aria-label="${esc(light.label)}"
          >
            ${light.icon}
          </span>
        </td>

        <td class="stock-360-product">
          <strong>
            ${esc(item.product_name)}
          </strong>
          <small>
            ${esc(item.unit || 'unité')}
          </small>
        </td>

        <td>
          ${
            (() => {
              const rawInitial =
                Number(item.initial_stock || 0);

              const displayedInitial =
                Math.max(0, rawInitial);

              const title =
                rawInitial < 0
                  ? (
                      'Ouverture estimée négative : '
                      + 'historique incomplet. '
                      + 'Valeur affichée ramenée à 0.'
                    )
                  : 'Stock initial estimé';

              return `
                <span title="${esc(title)}">
                  ${stock360InitialDisplay(item)}
                </span>
              `;
            })()
          }
        </td>

        <td class="stock-360-positive">
          ${entries > 0
            ? '+' + stock360Number(entries)
            : '0'}
        </td>

        <td class="stock-360-negative">
          ${Number(item.sale_out || 0) > 0
            ? '-' + stock360Number(item.sale_out)
            : '0'}
        </td>

        <td class="stock-360-negative">
          ${otherExits > 0
            ? '-' + stock360Number(otherExits)
            : '0'}
        </td>

        <td class="${
          adjustment < 0
            ? 'stock-360-negative'
            : adjustment > 0
              ? 'stock-360-positive'
              : ''
        }">
          ${stock360Signed(adjustment)}
        </td>

        <td class="stock-360-current">
          ${stock360Number(item.current_stock)}
        </td>

        <td>
          ${stock360Number(item.threshold)}
        </td>

        <td>
          ${cover}
        </td>

        <td class="stock-360-money">
          ${fmt(item.cost_value || 0)}
        </td>
      </tr>
    `;
  }).join('');
}

let stockIntelligenceData = null;
let stockIntelligenceFilter = 'replenish';
let stockIntelligenceShopKey = null;
let stockIntelligenceLoading = false;
let stockIntelligenceRequestId = 0;

function stockIntelligenceStatus(message, error = false) {
  const element = $('stockIntelligenceStatus');
  if (!element) return;
  element.textContent = message;
  element.hidden = !message;
  element.classList.toggle('settings-error', error);
}

function renderStockIntelligence() {
  if (!stockIntelligenceData) return;

  const data = stockIntelligenceData;
  const summary = data.summary || {};
  const items = data.items || [];

  const toOrder =
    Number(summary.out_of_stock || 0) +
    Number(summary.replenish || 0);

  const recommendedUnits =
    Number(summary.recommended_units || 0);

  const dormant =
    Number(summary.dormant || 0);

  if ($('statLowStock')) {
    $('statLowStock').textContent = String(toOrder);
  }

  if ($('statStockInsight')) {
    $('statStockInsight').textContent =
      `${dormant} dormant(s) · Voir détail ›`;
  }

  $('stockIntelligenceToOrder').textContent =
    String(toOrder);

  $('stockIntelligenceDormant').textContent =
    String(dormant);

  $('stockIntelligenceValue').textContent =
    fmt(summary.stock_value || 0);

  $('stockIntelligenceShop').textContent =
    `${state.merchant?.active_shop_name || 'Boutique active'}`
    + ` · ${data.period_days || 30} derniers jours`;

  const priorityTitle = $('stockPriorityTitle');
  const priorityText = $('stockPriorityText');
  const priorityCard = $('stockPriorityCard');

  priorityCard.classList.remove(
    'is-ok',
    'is-warning',
    'is-dormant'
  );

  if (toOrder > 0 && recommendedUnits > 0) {
    priorityCard.classList.add('is-warning');

    priorityTitle.textContent =
      `${toOrder} produit${toOrder > 1 ? 's' : ''} à traiter`;

    priorityText.textContent =
      `${recommendedUnits} unité${recommendedUnits > 1 ? 's' : ''}`
      + ` recommandée${recommendedUnits > 1 ? 's' : ''}`
      + ` pour sécuriser le stock.`;

  } else if (toOrder > 0) {
    priorityCard.classList.add('is-warning');

    priorityTitle.textContent =
      `${toOrder} produit${toOrder > 1 ? 's' : ''} à surveiller`;

    priorityText.textContent =
      `Stock faible détecté. Aucune quantité d'achat`
      + ` n'est recommandée automatiquement pour le moment.`;

  } else if (dormant > 0) {
    priorityCard.classList.add('is-dormant');

    priorityTitle.textContent =
      `${dormant} produit${dormant > 1 ? 's' : ''} dormant${dormant > 1 ? 's' : ''}`;

    priorityText.textContent =
      `Aucune urgence de réapprovisionnement.`
      + ` Vérifie le capital immobilisé.`;

  } else {
    priorityCard.classList.add('is-ok');

    priorityTitle.textContent =
      'Stock sous contrôle';

    priorityText.textContent =
      'Aucune action prioritaire détectée aujourd’hui.';
  }

  document
    .querySelectorAll('[data-stock-filter]')
    .forEach(button => {
      button.classList.toggle(
        'active',
        button.dataset.stockFilter === stockIntelligenceFilter
      );
    });

  const filtered = items.filter(item => {
    if (stockIntelligenceFilter === 'replenish') {
      return ['out_of_stock', 'replenish'].includes(item.status);
    }

    return item.status === stockIntelligenceFilter;
  });

  const list = $('stockIntelligenceList');

  if (!filtered.length) {
    list.innerHTML = `
      <div class="stock-v2-empty">
        <strong>Rien à signaler</strong>
        <span>Aucun produit dans cette catégorie.</span>
      </div>
    `;
    return;
  }

  list.innerHTML = filtered.map(item => {
    const unit = esc(item.unit || 'unité');

    const stock = Number(item.stock || 0);
    const sold30 = Number(item.sold_30d || 0);

    const recommendation = Math.max(
      0,
      Number(item.recommended_quantity || 0)
    );

    const statusLabel =
      item.status === 'out_of_stock' ? 'Rupture' :
      item.status === 'replenish' ? 'À traiter' :
      item.status === 'fast' ? 'Rapide' :
      item.status === 'slow' ? 'Lent' :
      item.status === 'dormant' ? 'Dormant' :
      'Normal';

    const statusClass =
      item.status === 'out_of_stock' ? 'stock-out' :
      item.status === 'replenish' ? 'stock-low' :
      item.status === 'dormant' ? 'stock-dormant' :
      'stock-ok';

    let message = '';

    if (item.status === 'out_of_stock') {
      message = recommendation > 0
        ? `Rupture de stock · commander ${recommendation} ${unit}`
        : 'Rupture de stock · achat à évaluer';

    } else if (item.status === 'replenish') {
      message = recommendation > 0
        ? `Stock faible · commander ${recommendation} ${unit}`
        : 'Stock faible · à surveiller';

    } else if (item.status === 'dormant') {
      const dormantDuration =
        item.days_since_last_sale != null
          ? `${item.days_since_last_sale} jours sans vente`
          : 'Aucune vente récente';

      message =
        `${dormantDuration} · `
        + `${fmt(item.stock_value || 0)} immobilisés`;

    } else if (item.status === 'fast') {
      message =
        `${sold30} ${unit} vendu${sold30 > 1 ? 's' : ''}`
        + ` sur 30 jours`;

    } else if (item.status === 'slow') {
      message =
        `${sold30} ${unit} vendu${sold30 > 1 ? 's' : ''}`
        + ` sur 30 jours · rotation faible`;
    }

    const action =
      recommendation > 0
        ? `<div class="stock-v2-action">
             Commander ${recommendation} ${unit}
           </div>`
        : '';

    return `
      <article class="stock-v2-product">
        <div class="stock-v2-product-top">
          <strong>${esc(item.product_name)}</strong>
          <span class="stock-state ${statusClass}">
            ${statusLabel}
          </span>
        </div>

        <div class="stock-v2-stockline">
          <strong>${stock}</strong>
          <span>${unit} en stock</span>
          <span class="stock-v2-dot">•</span>
          <span>${sold30} vendu${sold30 > 1 ? 's' : ''} / 30 j</span>
        </div>

        <p class="stock-v2-message">
          ${message}
        </p>

        ${action}
      </article>
    `;
  }).join('');
}

async function loadStockIntelligence(silent = false) {
  const requestedShop = state.merchant?.shop_id;

  if (requestedShop == null) {
    stockIntelligenceData = null;
    stockIntelligenceShopKey = null;
    stockIntelligenceStatus('Sélectionne une boutique.');
    return;
  }

  const requestId = ++stockIntelligenceRequestId;
  stockIntelligenceLoading = true;
  stockIntelligenceShopKey = String(requestedShop);

  if (!silent) {
    stockIntelligenceStatus('Analyse du stock en cours…');
  }

  try {
    const [data, stock360] = await Promise.all([
      api(
        '/pwa/stock/intelligence?target_cover_days=30&safety_days=7'
      ),
      api(
        '/pwa/stock/360?target_cover_days=30&safety_days=7'
      ),
    ]);

    // Une réponse ancienne ne peut jamais remplacer la boutique active.
    if (
      requestId !== stockIntelligenceRequestId ||
      String(state.merchant?.shop_id) !== String(requestedShop)
    ) return;

    stockIntelligenceData = data;
    stock360Data = stock360;

    renderStockIntelligence();
    renderStock360();

    stockIntelligenceStatus('');
  } catch (error) {
    if (
      requestId !== stockIntelligenceRequestId ||
      String(state.merchant?.shop_id) !== String(requestedShop)
    ) return;

    stockIntelligenceData = null;
    stock360Data = null;

    if ($('stock360Body')) {
      $('stock360Body').innerHTML = `
        <tr>
          <td colspan="11">
            Stock 360 indisponible.
          </td>
        </tr>
      `;
    }

    if ($('statLowStock')) $('statLowStock').textContent = '—';
    if ($('statStockInsight')) {
      $('statStockInsight').textContent = 'Analyse indisponible';
    }
    if ($('stockIntelligenceList')) {
      $('stockIntelligenceList').innerHTML = '';
    }

    stockIntelligenceStatus(
      error.message || 'Analyse du stock indisponible.',
      true
    );
  } finally {
    if (requestId === stockIntelligenceRequestId) {
      stockIntelligenceLoading = false;
    }
  }
}

$('productStockIntelligenceLink')?.addEventListener(
  'click',
  () => {
    stockIntelligenceFilter = 'replenish';

    document
      .querySelectorAll('[data-stock-filter]')
      .forEach((button) => {
        button.classList.toggle(
          'active',
          button.dataset.stockFilter === 'replenish'
        );
      });

    showTab('stockIntelligence');

    if (stockIntelligenceData) {
      renderStockIntelligence();
    }
  },
);


document.querySelectorAll('[data-stock-filter]').forEach(button => {
  button.addEventListener('click', () => {
    stockIntelligenceFilter = button.dataset.stockFilter;
    renderStockIntelligence();
  });
});

$('stock360Toggle')?.addEventListener(
  'click',
  () => {
    stock360ShowAll = !stock360ShowAll;
    renderStock360();

    if (!stock360ShowAll) {
      document
        .querySelector('.stock-360-section')
        ?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        });
    }
  }
);


$('stockIntelligenceRefresh')?.addEventListener('click', () => {
  stockIntelligenceShopKey = null;
  void loadStockIntelligence();
});


// whatzabi-accounting-exports-v1
(() => {
  const menu = document.getElementById('moreExports');
  const dialog = document.getElementById('accountingExportDialog');
  const form = document.getElementById('accountingExportForm');
  const status = document.getElementById('accountingExportStatus');
  const sinceInput = document.getElementById('accountingExportSince');
  const untilInput = document.getElementById('accountingExportUntil');
  let controller = null;

  function context() {
    return {
      merchantId: state.merchant?.id,
      shopId: state.merchant?.shop_id,
      accessToken: token,
    };
  }

  function sameContext(before) {
    const now = context();
    return now.merchantId === before.merchantId &&
      now.shopId === before.shopId &&
      now.accessToken === before.accessToken &&
      can('report.read');
  }

  function syncAccess() {
    menu.hidden = !can('report.read');
    if (dialog.open && (!can('report.read') || !state.merchant?.shop_id)) {
      dialog.close();
    }
  }

  const previousPermissions = renderPermissions;
  renderPermissions = function (...args) {
    const result = previousPermissions.apply(this, args);
    syncAccess();
    return result;
  };
  syncAccess();

  menu.addEventListener('click', () => {
    if (!can('report.read')) {
      toast("Tu n'as pas l'autorisation d'exporter ces données.");
      return;
    }
    const shopId = state.merchant?.shop_id;
    if (!shopId) {
      toast("Sélectionne d'abord une boutique.");
      return;
    }

    const today = new Date().toISOString().slice(0, 10);
    sinceInput.value = today.slice(0, 8) + '01';
    untilInput.value = today;
    document.getElementById('accountingExportMode').value = 'summary';
    document.getElementById('accountingExportCancelled').checked = false;
    document.getElementById('accountingExportShop').textContent =
      'Boutique sélectionnée : ' +
      (state.merchant.shop_name || 'n° ' + shopId);
    status.textContent = '';
    dialog.showModal();
  });

  document.getElementById('accountingExportClose')
    .addEventListener('click', () => dialog.close());

  dialog.addEventListener('close', () => {
    controller?.abort();
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (controller || !form.reportValidity()) return;

    const kind = event.submitter?.value;
    if (!['sales', 'purchases', 'expenses'].includes(kind)) return;

    const before = context();
    if (!before.accessToken || !before.shopId || !can('report.read')) {
      status.textContent = 'Reconnecte-toi et sélectionne une boutique.';
      return;
    }
    if (sinceInput.value > untilInput.value) {
      status.textContent = 'La date de début dépasse la date de fin.';
      return;
    }

    const params = new URLSearchParams({
      since: sinceInput.value,
      until: untilInput.value,
      mode: kind === 'expenses' ? 'summary' :
        document.getElementById('accountingExportMode').value,
      include_cancelled: String(
        document.getElementById('accountingExportCancelled').checked
      ),
    });

    const controls = [...form.querySelectorAll('input, select, button')];
    controls.forEach((control) => { control.disabled = true; });
    status.textContent = 'Préparation du fichier…';
    controller = new AbortController();
    const activeController = controller;
    const timeout = setTimeout(() => activeController.abort(), 60000);

    try {
      const response = await fetch('/pwa/exports/' + kind + '.csv?' + params, {
        headers: { Authorization: 'Bearer ' + before.accessToken },
        cache: 'no-store',
        signal: activeController.signal,
      });

      if (!response.ok) {
        let body = null;
        try { body = await response.json(); } catch {}
        if (response.status === 401 && sameContext(before)) logout();
        throw new Error(
          typeof body?.detail === 'string' ? body.detail :
            'Export impossible (' + response.status + ').'
        );
      }

      if (!(response.headers.get('content-type') || '').includes('text/csv')) {
        throw new Error('Le serveur ne renvoie pas un fichier CSV.');
      }

      const blob = await response.blob();
      if (!dialog.open || !sameContext(before)) {
        throw new Error('La boutique ou la session a changé. Relance cet export.');
      }

      const disposition = response.headers.get('content-disposition') || '';
      const filename = disposition.match(/filename="([^"]+)"/)?.[1] ||
        'whatzabi-' + kind + '.csv';
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      status.textContent = 'Téléchargement lancé.';
    } catch (error) {
      if (dialog.open) {
        status.textContent = error.name === 'AbortError'
          ? 'Export interrompu. Réessaie.'
          : error.message || 'Export impossible. Vérifie ta connexion.';
      }
    } finally {
      clearTimeout(timeout);
      controller = null;
      controls.forEach((control) => { control.disabled = false; });
    }
  });
})();


// whatzabi-sale-photo-review-v1
(() => {
  const menu = document.getElementById('moreSalePhoto');
  if (!menu) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'sale-photo-dialog';
  dialog.setAttribute('aria-labelledby', 'salePhotoTitle');
  dialog.innerHTML = `
    <div class="sale-photo-head"><h2 id="salePhotoTitle">Importer les ventes papier</h2>
    <button type="button" data-close>Fermer</button></div>
    <p data-shop></p>
    <p>Photographie une page entière et nette. Vérifie les données avant tout enregistrement.</p>
    <div class="sale-photo-actions">
      <button type="button" data-camera>Prendre une photo</button>
      <button type="button" data-gallery>Choisir une photo</button>
      <input data-camera-input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" hidden>
      <input data-gallery-input type="file" accept="image/jpeg,image/png,image/webp" hidden>
    </div>
    <p>JPEG, PNG ou WebP · 20 Mo maximum avant compression, 12 Mo après.</p>
    <img data-preview alt="Photo du registre" hidden>
    <p data-status role="status" aria-live="polite"></p>
    <button type="button" data-retry hidden>Réessayer la lecture de la photo</button>
    <form data-review hidden>
      <div class="sale-photo-fields">
        <label>Date d’en-tête (indicative)<input data-date type="date"></label>
        <label>Total déclaré du document<input data-document-total type="number" min="0" step="1"></label>
        <label>Justification du total absent, corrigé ou différent<input data-total-reason maxlength="1000"></label>
        <label>Justification des ventes similaires (si signalées)<input data-duplicate-reason maxlength="1000"></label>
        <label>Règle validée pour décompter le stock historique<input data-stock-reason maxlength="1000"></label>
        <label>Devise<input data-currency maxlength="3" pattern="[A-Z]{3}" required></label>
        <label>Regroupement<select data-group required>
          <option value="">Choisir comment lire le registre</option>
          <option value="rows">Chaque ligne est une vente distincte</option>
          <option value="sheet">Toutes les lignes appartiennent à une seule vente</option>
        </select></label>
        <label>Stock<select data-stock required>
          <option value="">Choisir l'effet sur le stock</option>
          <option value="deduct">Décompter les quantités du stock actuel</option>
          <option value="keep">Stock déjà à jour : ne pas décompter</option>
        </select></label>
      </div>
      <p data-warnings></p>
      <p>Une case « Payé » vide reste inconnue : renseigne le montant après vérification.
      Pour une vente à crédit, choisis le client. Les paiements saisis seront datés du registre.
      Les montants doivent être entiers, dans la devise de la boutique.</p>
      <div data-daily-totals></div>
      <div data-lines></div>
      <p data-total></p>
      <details><summary>Voir le JSON corrigé</summary><pre data-json></pre></details>
      <label class="sale-photo-check"><input data-confirm type="checkbox" required>
        J'ai vérifié la date, les produits, les paiements, le regroupement et le stock.
        J’ai vérifié les éventuelles ventes similaires.</label>
      <button type="submit" class="primary">Valider et importer les ventes</button>
    </form>`;
  document.body.appendChild(dialog);
  const get = name => dialog.querySelector('[data-' + name + ']');
  const form = get('review');
  const status = get('status');
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[c]));
  let contextEpoch = 0;
  const context = () => ({
    epoch:contextEpoch,
    merchant:state.merchant?.id, shop:state.merchant?.shop_id, token
  });
  const same = before => before && before.epoch === contextEpoch &&
    before.merchant === state.merchant?.id &&
    before.shop === state.merchant?.shop_id &&
    before.token === token && can('sale.create');
  let origin = null, extraction = null, controller = null;
  let previewUrl = null, busy = false, pendingPhoto = null;
  let recoveryKey = null, pendingConfirmation = null;
  const storageKey = 'whatzabi.salePhoto.v2';
  const fields = ['date', 'currency', 'group', 'stock', 'document-total', 'total-reason', 'duplicate-reason', 'stock-reason'];
  const rowFields = ['sale-date', 'product', 'quantity', 'price', 'line-total', 'paid', 'channel', 'customer'];
  function forgetRecovery() {
    try { sessionStorage.removeItem(storageKey); } catch { /* Storage may be unavailable. */ }
  }
  function saveRecovery() {
    if (!extraction || !same(origin) || !recoveryKey) return;
    const saved = {
      key:recoveryKey, extraction, pendingConfirmation,
      fields:Object.fromEntries(fields.map(name => [name, get(name).value])),
      rows:[...get('lines').querySelectorAll('[data-row]')].map(field => ({
        index:field.dataset.row,
        values:Object.fromEntries(rowFields.map(name => [name, field.querySelector('[data-' + name + ']').value]))
      })),
      daily:[...get('daily-totals').querySelectorAll('[data-daily]')].map(field => field.value),
      dailyDates:[...get('daily-totals').querySelectorAll('[data-daily-date]')].map(field => field.value)
    };
    try { sessionStorage.setItem(storageKey, JSON.stringify(saved)); } catch { /* In-memory draft still works. */ }
  }
  async function restoreRecovery() {
    const before = origin;
    try {
      const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(
        JSON.stringify([before.merchant, before.shop, before.token])));
      if (!same(before)) return;
      recoveryKey = [...new Uint8Array(hash)].map(x => x.toString(16).padStart(2, '0')).join('');
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
      if (!saved) return;
      if (saved.key !== recoveryKey || !saved.extraction?.expires_at ||
          (!saved.pendingConfirmation && Date.parse(saved.extraction.expires_at) <= Date.now())) { forgetRecovery(); return; }
      if (extraction) { saveRecovery(); return; }
      renderDraft(saved.extraction);
      for (const name of fields) get(name).value = saved.fields[name] ?? '';
      for (const field of get('lines').querySelectorAll('[data-row]')) {
        const row = saved.rows.find(row => row.index === field.dataset.row);
        if (!row) { field.remove(); continue; }
        for (const name of rowFields) field.querySelector('[data-' + name + ']').value = row.values[name] ?? '';
      }
      [...get('daily-totals').querySelectorAll('[data-daily]')].forEach((field, index) => { field.value = saved.daily[index] ?? ''; });
      [...get('daily-totals').querySelectorAll('[data-daily-date]')].forEach((field, index) => { field.value = saved.dailyDates[index] ?? ''; });
      pendingConfirmation = saved.pendingConfirmation || null;
      get('confirm').checked = false;
      renderJson();
      setBusy(false);
      status.textContent = pendingConfirmation ?
        'Validation à vérifier : relance la même confirmation pour connaître le résultat.' :
        'Brouillon restauré sans photographie. Vérifie les données avant confirmation.';
    } catch { /* Recovery unavailable: never apply an unverified draft. */ }
  }

  function reset() {
    forgetRecovery();
    pendingConfirmation = null;
    extraction = null;
    form.hidden = true;
    form.reset();
    get('lines').replaceChildren();
    get('daily-totals').replaceChildren();
    get('json').textContent = '';
    get('total').textContent = '';
    get('warnings').textContent = '';
    get('preview').hidden = true;
    get('preview').removeAttribute('src');
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    pendingPhoto = null;
    get('retry').hidden = true;
  }
  function syncAccess() {
    menu.hidden = !can('sale.create');
    if (origin && !same(origin)) {
      contextEpoch += 1;
      controller?.abort();
      dialog.close();
      reset();
    }
  }
  const previous = renderPermissions;
  renderPermissions = function (...args) {
    const result = previous.apply(this, args);
    syncAccess();
    return result;
  };
  syncAccess();
  menu.addEventListener('click', async () => {
    if (!token || !can('sale.create') || !state.merchant?.shop_id) {
      toast('Sélectionne une boutique et reconnecte-toi.');
      return;
    }
    if (busy) return;
    if (origin && !same(origin)) {
      reset();
      status.textContent = '';
    }
    origin = context();
    get('shop').textContent = 'Boutique : ' +
      (state.merchant.active_shop_name || state.merchant.shop_name || origin.shop);
    dialog.showModal();
    await restoreRecovery();
  });
  get('close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    controller?.abort();
    saveRecovery();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    get('preview').removeAttribute('src');
    get('preview').hidden = true;
    // A failed extraction may retry its photo in memory; it is never persisted.
  });
  get('camera').addEventListener('click', () => get('camera-input').click());
  get('gallery').addEventListener('click', () => get('gallery-input').click());

  const httpErrors = {
    400:['invalid_request', 'Vérifie les données et la photo.'],
    401:['authentication_required', 'Session expirée. Reconnecte-toi pour poursuivre.'],
    403:['forbidden', 'Tu n’as pas accès à cet import.'],
    404:['not_found', 'Produit ou client inaccessible. Vérifie les lignes.'],
    409:['conflict', 'Vérifie la boutique et si cette photo a déjà été importée.'],
    413:['photo_too_large', 'Photo trop volumineuse : maximum 12 Mo après compression.'],
    415:['unsupported_photo', 'Photo JPEG, PNG ou WebP requise. Convertis HEIC en JPEG.'],
    422:['validation_error', 'Vérifie les champs obligatoires et leur format.'],
    503:['service_unavailable', 'Service de lecture indisponible. Réessaie dans un instant.'],
    504:['timeout', 'Le serveur a dépassé le délai de réponse. Réessaie.']
  };
  function photoError(code, message, requestId = null, statusCode = null) {
    return Object.assign(new Error(message), {
      name:'SalePhotoError', code, requestId, status:statusCode,
      retryable:['network', 'timeout', 'service_unavailable'].includes(code)
    });
  }
  function showError(error, confirming = false) {
    const known = error.name === 'SalePhotoError';
    status.textContent = (known ? error.message : 'Import impossible. Réessaie.') +
      (known && error.requestId ? ' Référence : ' + error.requestId + '.' : '') +
      (confirming ? ' Le brouillon est conservé dans cette session.' : '') +
      (confirming && (!known || error.retryable || error.code === 'invalid_response') ?
        ' Réessaie la même validation pour vérifier le résultat sans créer de doublon.' : '');
  }
  async function request(path, body, json = false) {
    if (!same(origin)) throw photoError('context_changed', 'La boutique ou la session a changé. Recommence.');
    const requestOrigin = origin;
    controller = new AbortController();
    const active = controller;
    let timedOut = false;
    let requestId = crypto.randomUUID();
    const timer = setTimeout(() => { timedOut = true; active.abort(); }, 90000);
    try {
      const response = await fetch(path, {
        method:'POST', cache:'no-store', signal:active.signal,
        headers:{
          Authorization:'Bearer ' + requestOrigin.token,
          'X-Request-ID':requestId,
          ...(json ? {'Content-Type':'application/json'} : {})
        },
        body:json ? JSON.stringify(body) : body
      });
      const returnedId = response.headers.get('X-Request-ID');
      if (/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(returnedId || '')) {
        requestId = returnedId;
      }
      if (!same(requestOrigin)) throw photoError('context_changed', 'La boutique ou la session a changé. Recommence.', requestId);
      if (!response.ok) {
        const [code, message] = httpErrors[response.status] ||
          ['http_error', 'Import impossible (HTTP ' + response.status + '). Réessaie ou contacte le support.'];
        // Only a fixed public business-error vocabulary can cross this boundary.
        const businessMessages = {
          total_reconciliation:'Total absent, corrigé ou incohérent : corrige les lignes ou saisis une justification (10 caractères minimum).',
          business_duplicate:'Ventes similaires détectées : vérifie le registre et justifie les ventes réellement distinctes.',
          historical_stock_rule:'Décris la règle autorisant le décompte historique du stock actuel.',
          mixed_sale_dates:'Une vente ne peut pas regrouper plusieurs journées.',
          draft_expired:'Brouillon expiré : reprends la lecture.',
          confirmed_payload_changed:'Brouillon déjà confirmé avec un contenu différent. Vérifie les ventes enregistrées.',
          source_already_imported:'Photo déjà importée. Reprends le brouillon d’origine.',
          source_changed:'La photo ne correspond pas au brouillon.',
          daily_total_duplicate:'Un seul sous-total par journée est permis.'
        };
        let errorBody;
        try { errorBody = await response.json(); } catch { /* HTML/empty proxy error. */ }
        const businessCode = response.status === 409 && errorBody?.error?.code;
        const candidates = businessCode === 'business_duplicate' && Array.isArray(errorBody?.error?.candidates) ?
          errorBody.error.candidates.filter(item => Number.isInteger(item.sale_number) && item.sale_number > 0).slice(0, 50) : [];
        const references = candidates.length ? ' Ventes à vérifier : ' +
          [...new Set(candidates.map(item => '#' + item.sale_number))].join(', ') + '.' : '';
        throw photoError(businessMessages[businessCode] ? businessCode : code,
          (businessMessages[businessCode] || message) + references, requestId, response.status);
      }
      let result;
      try {
        result = await response.json();
      } catch (error) {
        if (active.signal.aborted || error instanceof TypeError) throw error;
        throw photoError('invalid_response', 'Réponse du serveur illisible. Réessaie.', requestId);
      }
      if (!same(requestOrigin)) throw photoError('context_changed', 'La boutique ou la session a changé. Recommence.', requestId);
      if (!result || (json ?
        !Array.isArray(result.sale_ids) || !result.sale_ids.length ||
        !result.sale_ids.every(id => Number.isInteger(id) && id > 0) ||
        typeof result.already_imported !== 'boolean' :
        !Array.isArray(result.result?.lines) || !Array.isArray(result.result?.warnings) ||
        !result.result.lines.every(line => line && Array.isArray(line.warnings) &&
          Array.isArray(line.uncertain_fields)) ||
        !/^[a-f0-9-]{36}$/.test(result.draft_id || '') ||
        String(result.merchant_id) !== String(requestOrigin.merchant) ||
        !Number.isFinite(Date.parse(result.expires_at)) ||
        !/^[a-f0-9]{64}$/.test(result.source_sha256 || '') ||
        String(result.shop_id) !== String(requestOrigin.shop))) {
        throw photoError('invalid_response', 'Réponse du serveur incomplète. Réessaie.', requestId);
      }
      return result;
    } catch (error) {
      if (error.name === 'SalePhotoError') throw error;
      if (timedOut) throw photoError('timeout', 'Le délai de réponse est dépassé. Réessaie.', requestId);
      if (active.signal.aborted) throw photoError('cancelled', 'Opération interrompue. Réessaie.', requestId);
      throw photoError('network', 'Connexion interrompue. Vérifie le réseau puis réessaie.', requestId);
    } finally {
      clearTimeout(timer);
      if (controller === active) controller = null;
    }
  }
  async function convert(file) {
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file?.type)) {
      throw photoError('unsupported_photo', 'Choisis une photo JPEG, PNG ou WebP. Convertis HEIC en JPEG.');
    }
    if (!file.size) throw photoError('empty_photo', 'La photo est vide. Choisis une autre photo.');
    if (file.size > 20 * 1024 * 1024) {
      throw photoError('photo_too_large', 'Photo trop volumineuse : maximum 20 Mo avant compression.');
    }
    const url = URL.createObjectURL(file);
    try {
      const image = new Image();
      image.src = url;
      await image.decode();
      const scale = Math.min(1, 2400 / Math.max(image.width, image.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(image.width * scale);
      canvas.height = Math.round(image.height * scale);
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise(resolve =>
        canvas.toBlob(resolve, 'image/jpeg', 0.92));
      if (!blob || blob.size > 12 * 1024 * 1024) {
        throw photoError('photo_too_large', 'Impossible de préparer cette photo : maximum 12 Mo après compression.');
      }
      return blob;
    } catch (error) {
      if (error.name === 'SalePhotoError') throw error;
      throw photoError('unsupported_photo', 'Photo illisible. Choisis un JPEG, PNG ou WebP valide.');
    } finally {
      URL.revokeObjectURL(url);
    }
  }
  function setBusy(value) {
    busy = value;
    dialog.querySelectorAll('input, select, button').forEach(control => {
      if (!control.hasAttribute('data-close')) control.disabled = value ||
        (!!pendingConfirmation && control.type !== 'submit');
    });
  }
  async function selected(event) {
    const file = event?.target.files?.[0];
    if (event) event.target.value = '';
    if ((!file && !pendingPhoto) || busy || pendingConfirmation) return;
    setBusy(true);
    status.textContent = 'Lecture de la photo…';
    const before = origin;
    try {
      // A failed replacement must not erase corrections to the previous draft.
      const blob = file ? await convert(file) : pendingPhoto;
      if (!dialog.open || !same(before)) return;
      pendingPhoto = blob;
      get('retry').hidden = false;
      const data = new FormData();
      data.append('image', blob, 'registre.jpg');
      const result = await request('/pwa/sales/photo/extract', data);
      if (!dialog.open || !same(before) ||
          String(result.shop_id) !== String(before.shop)) return;
      if (!result.result.lines.length) {
        throw photoError('unreadable_photo', 'Aucune ligne lisible. Reprends la photo.');
      }
      reset();
      renderDraft(result);
      saveRecovery();
    } catch (error) {
      if (dialog.open && same(before)) {
        showError(error);
      }
    } finally {
      setBusy(false);
      get('retry').hidden = !pendingPhoto;
    }
  }
  get('camera-input').addEventListener('change', selected);
  get('gallery-input').addEventListener('change', selected);
  get('retry').addEventListener('click', () => selected());
  function renderDraft(result) {
      extraction = result;
      get('document-total').value = result.result.document_total ?? '';
      get('daily-totals').innerHTML = (result.result.daily_totals || []).map((item, index) =>
        `<label>Journée du sous-total<input data-daily-date="${index}" type="date" value="${escape(item.sale_date || '')}" required></label><label>Sous-total<input data-daily="${index}" type="number" min="0" step="1" value="${item.total ?? ''}"></label>`).join('');
      get('date').value = result.result.document_date || '';
      get('currency').value = result.result.currency ||
        state.currencyContext?.shop_currency || 'XOF';
      get('warnings').textContent = result.result.warnings.join(' ');
      get('lines').innerHTML = result.result.lines.map((line, index) => {
        const candidates = line.product_candidates || [];
        const seen = new Set(candidates.map(p => p.product_id));
        const products = [
          ...candidates,
          ...(state.products || []).filter(p => !seen.has(p.id)).map(p => ({
            product_id:p.id, name:p.name, stock:p.stock
          }))
        ];
        const labels = {
          sale_date:'Date à vérifier', description:'Produit à vérifier', quantity:'Quantité à vérifier',
          unit_price:'Prix à vérifier', line_total:'Total à vérifier',
          paid_amount:'Paiement à vérifier'
        };
        const warnings = [
          ...line.uncertain_fields.map(field => labels[field]), ...line.warnings
        ].join(' · ');
        return `<fieldset data-row="${index}">
          <legend>Ligne ${line.row_number} · ${escape(line.description || 'Produit illisible')}</legend>
          <p class="sale-photo-alert">${escape(warnings)}</p>
          <div class="sale-photo-fields">
          <label>Date de vente<input data-sale-date type="date" value="${escape(line.sale_date || '')}" required></label>
          <label>Produit du catalogue<select data-product required>
            <option value="">Sélectionner le produit</option>
            ${products.map(p => `<option value="${Number(p.product_id)}">${escape(p.name)} · stock ${Number(p.stock || 0)}</option>`).join('')}
          </select></label>
          <label>Quantité<input data-quantity type="number" min="1" max="1000000"
            step="1" value="${line.quantity ?? ''}" required></label>
          <label>Prix unitaire<input data-price type="number" min="1" max="2000000000"
            step="1" value="${line.unit_price ?? line.suggested_unit_price ?? ''}" required></label>
          <label>Total de ligne<input data-line-total type="number" min="1"
            max="2000000000" step="1" value="${line.line_total ?? ''}" required></label>
          <label>Montant payé<input data-paid type="number" min="0" max="2000000000"
            step="1" value="${line.paid_amount ?? ''}"
            placeholder="Inconnu : à renseigner" required></label>
          <label>Mode de paiement<select data-channel>
            <option value="">À préciser</option><option value="cash">Espèces</option>
            <option value="mobile_money">Mobile Money</option>
            <option value="card">Carte</option><option value="bank_transfer">Virement</option>
          </select></label>
          <label>Client si crédit<select data-customer>
            <option value="">Vente comptoir payée</option>
            ${(state.customers || []).map(c => `<option value="${Number(c.id)}">${escape(c.name)}</option>`).join('')}
          </select></label>
          </div><button type="button" data-exclude>Retirer cette ligne</button>
        </fieldset>`;
      }).join('');
      form.hidden = false;
      status.textContent = 'Lecture terminée. Vérifie chaque ligne. Rien n’est enregistré.';
      renderJson();
  }
  function payload() {
    const number = input => input.value === '' ? null : Number(input.value);
    return {
      draft_id:extraction.draft_id,
      confirmed:get('confirm').checked,
      shop_id:Number(origin.shop),
      source_sha256:extraction.source_sha256,
      document_date:get('date').value || null,
      document_total:number(get('document-total')),
      daily_totals:[...get('daily-totals').querySelectorAll('[data-daily]')].map((field, index) => ({sale_date:[...get('daily-totals').querySelectorAll('[data-daily-date]')][index].value, total:number(field)})),
      total_justification:get('total-reason').value.trim() || null,
      duplicate_justification:get('duplicate-reason').value.trim() || null,
      stock_justification:get('stock-reason').value.trim() || null,
      currency:get('currency').value.toUpperCase(),
      affect_stock:get('stock').value === 'deduct',
      rows:[...get('lines').querySelectorAll('[data-row]')].map(field => {
        const read = name => field.querySelector('[data-' + name + ']');
        const row = extraction.result.lines[Number(field.dataset.row)];
        return {
          row_number:row.row_number,
          sale_date:read('sale-date').value,
          sale_group:get('group').value === 'sheet' ? 'registre' : String(row.row_number),
          product_id:number(read('product')),
          quantity:number(read('quantity')),
          unit_price:number(read('price')),
          line_total:number(read('line-total')),
          paid_amount:number(read('paid')),
          customer_id:number(read('customer')),
          payment_channel:read('channel').value || null
        };
      })
    };
  }
  function renderJson() {
    if (!extraction) return;
    const data = payload();
    get('json').textContent = JSON.stringify(data, null, 2);
    get('total').textContent = 'Total des lignes retenues : ' +
      data.rows.reduce((sum,row) => sum + (row.line_total || 0), 0) +
      ' ' + data.currency + ' · Total déclaré : ' + (data.document_total ?? 'inconnu') +
      ' · Écart : ' + (data.document_total === null ? 'à justifier' : data.document_total - data.rows.reduce((sum,row) => sum + (row.line_total || 0), 0));
    saveRecovery();
  }
  form.addEventListener('input', event => {
    if (event.target !== get('confirm')) get('confirm').checked = false;
    renderJson();
  });
  form.addEventListener('change', event => {
    if (event.target === get('confirm')) {
      renderJson();
      return;
    }
    get('confirm').checked = false;
    if (get('stock').value === 'keep' && !can('stock.adjust')) {
      get('stock').value = '';
      status.textContent = 'Un manager ou propriétaire doit valider un import sans décompte du stock.';
    }
    renderJson();
  });
  get('lines').addEventListener('click', event => {
    if (event.target.hasAttribute('data-exclude')) {
      event.target.closest('[data-row]').remove();
      get('confirm').checked = false;
      renderJson();
    }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || (!pendingConfirmation && !form.reportValidity()) || !same(origin)) return;
    const data = pendingConfirmation || payload();
    if (!data.rows.length) {
      status.textContent = 'Conserve au moins une ligne.';
      return;
    }
    for (const row of data.rows) {
      if (row.quantity * row.unit_price !== row.line_total ||
          row.paid_amount > row.line_total) {
        status.textContent = 'Vérifie les montants de la ligne ' + row.row_number;
        return;
      }
      if (row.paid_amount > 0 && !row.payment_channel) {
        status.textContent = 'Précise le mode de paiement de la ligne ' + row.row_number;
        return;
      }
      if (row.paid_amount < row.line_total && !row.customer_id) {
        status.textContent = 'Choisis le client de la ligne ' + row.row_number;
        return;
      }
    }
    pendingConfirmation = data;
    saveRecovery();
    setBusy(true);
    status.textContent = 'Enregistrement des ventes…';
    try {
      const result = await request('/pwa/sales/photo/confirm', data, true);
      if (!dialog.open || !same(origin)) return;
      reset();
      status.textContent = result.already_imported ?
        'Cette photo était déjà importée. Aucun doublon créé.' :
        result.sale_ids.length + ' vente(s) importée(s).';
      try {
        await refresh();
      } catch {
        if (dialog.open) status.textContent += ' Actualisation indisponible : recharge les listes.';
      }
    } catch (error) {
      if (same(origin)) {
        if (error.status && error.status < 500) pendingConfirmation = null;
        saveRecovery();
        showError(error, true);
      }
    } finally {
      setBusy(false);
    }
  });
})();
