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

  state.financePeriod = period;
  renderFinancePeriodButtons();

  setFinanceStatus(
    "Chargement de l'analyse financière…"
  );

  try {
    const data = await api(
      '/pwa/finance/overview?period=' +
        encodeURIComponent(period)
    );

    state.finance = data;
    renderFinanceOverview(data);
    setFinanceStatus();
  } catch (error) {
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
  state = { products: [], customers: [], sales: [], merchant: null, shops: [], currencyContext: null, finance: null, financePeriod: 'month' };
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
                <span>Stock ${stock} ${esc(product.unit)} · seuil ${threshold}</span>
              </div>
              ${status}
            </article>`;
          })
          .join('')
      : '<p class="muted empty-state">Aucun produit en stock critique.</p>';
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
   * En cas d'échec de compression, on conserve le fichier original.
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

    if (!context) return file;

    context.drawImage(image, 0, 0, width, height);

    const blob = await new Promise((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', 0.8);
    });

    if (!blob) return file;

    return new File(
      [blob],
      'depense.jpg',
      { type: 'image/jpeg' }
    );
  } catch (error) {
    console.warn('Compression justificatif impossible', error);
    return file;
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
    formData.append('image', preparedFile);

    const token = localStorage.getItem('whatzabi_token');

    const response = await fetch('/pwa/expenses/scan', {
      method: 'POST',
      headers: token
        ? { Authorization: `Bearer ${token}` }
        : {},
      body: formData,
    });

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
    setExpenseScanStatus(
      error.message || 'Analyse du justificatif impossible.',
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
