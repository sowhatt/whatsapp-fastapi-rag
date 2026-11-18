// A network-first worker can serve current scripts to an older cached document.
// Preserve every local draft/outbox, stop this incompatible document before boot.
if (!document.getElementById('expressPaidAmount') || !document.getElementById('financeCurrentLabel') || !document.getElementById('financeSupplierPaid')) {
  const notice=document.createElement('section');notice.id='commercialUpgradeRequired';notice.setAttribute('role','alert');notice.style.cssText='padding:24px;background:white;color:#142d29;position:relative;z-index:99999';
  const message=document.createElement('p');message.textContent='Mise à jour nécessaire. Tes brouillons et opérations en attente sont conservés. Actualise cette page pour reprendre dans le même compte et la même boutique.';
  for(const control of document.querySelectorAll('button,input,select,textarea'))control.disabled=true;
  const reload=document.createElement('button');reload.type='button';reload.textContent='Actualiser et conserver les brouillons';reload.onclick=()=>location.reload();notice.append(message,reload);document.body.prepend(notice);reload.focus();
  throw new Error('Document commercial ancien : actualisation explicite nécessaire, stockage conservé.');
}

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
// Historical password sessions stay persistent. Quick credentials stay in memory.
let tokenPersistent = true;
let passkeysEnabled = false;
let passkeyBusy = false;
let quickAuthUI = null;
window.whatzabiAccessToken = () => token;
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

// A transport failure is not an authentication decision. This small, token-bound
// record only labels a suspended session; it never authorizes offline writes.
const RESUME_CONTEXT_KEY = 'whatzabi:resume-context:v1';
let sessionNeedsCheck = true;
let resumeTimer = null;
let resumeRunning = false;

function sessionClaims(value = token) {
  try {
    const part = value.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const claims = JSON.parse(atob(part));
    return claims.type === 'access' && Number.isFinite(claims.exp) ? claims : null;
  } catch { return null; }
}
function sessionIsUnexpired(value = token) {
  const claims = sessionClaims(value);
  return Boolean(claims && claims.exp * 1000 > Date.now());
}
function sessionFailure(message, status) {
  const error = new Error(message);
  error.status = status;
  // Never turn expiry, denial or a changed account into a queued sale.
  error.isHttpError = true;
  return error;
}
async function tokenFingerprint(value) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, '0')).join('');
}
function sameSessionIdentity(merchant, claims) {
  return merchant && claims &&
    Number(merchant.id) === Number(claims.merchant_id) &&
    Number(merchant.user_id || 0) === Number(claims.user_id || 0) &&
    Number(merchant.shop_id || 0) === Number(claims.shop_id || 0);
}
async function rememberResumeContext(expectedToken) {
  if (!tokenPersistent) return;
  const merchant = state.merchant;
  const claims = sessionClaims(expectedToken);
  if (!sameSessionIdentity(merchant, claims) || !sessionIsUnexpired(expectedToken)) return;
  const fingerprint = await tokenFingerprint(expectedToken);
  if (token !== expectedToken) return;
  try {
    localStorage.setItem(RESUME_CONTEXT_KEY, JSON.stringify({
      fingerprint, expiresAt: claims.exp * 1000,
      merchant: {id: merchant.id, user_id: merchant.user_id, shop_id: merchant.shop_id,
        active_shop_name: merchant.active_shop_name || ''}
    }));
  } catch { /* Resume still preserves the token/outboxes when context storage is unavailable. */ }
}
function resumeView() {
  let view = $('offlineResumeView');
  if (!view) {
    view = document.createElement('section');
    view.id = 'offlineResumeView'; view.className = 'card'; view.hidden = true;
    view.setAttribute('aria-live', 'polite');
    view.innerHTML = '<h2 id="offlineResumeTitle"></h2><p id="offlineResumeMessage"></p>' +
      '<p id="offlineResumeShop"></p><button id="offlineResumeRetry" type="button">Réessayer</button> ' +
      '<button id="offlineResumeLogout" type="button">Se déconnecter</button>';
    $('loginView').before(view);
    $('offlineResumeRetry').addEventListener('click', () => void boot());
    $('offlineResumeLogout').addEventListener('click', signOut);
  }
  return view;
}
function hideResumeView() {
  clearTimeout(resumeTimer); resumeTimer = null;
  if ($('offlineResumeView')) $('offlineResumeView').hidden = true;
}
async function suspendSession(error) {
  const expectedToken = token;
  if (!expectedToken) return;
  if (!sessionIsUnexpired(expectedToken)) {
    logout('Session expirée. Reconnecte-toi : tes opérations en attente sont conservées.');
    return;
  }
  sessionNeedsCheck = true;
  let context = null;
  try {
    const saved = JSON.parse(localStorage.getItem(RESUME_CONTEXT_KEY) || 'null');
    if (saved?.fingerprint === await tokenFingerprint(expectedToken) &&
        saved.expiresAt === sessionClaims(expectedToken).exp * 1000 &&
        sameSessionIdentity(saved.merchant, sessionClaims(expectedToken))) context = saved;
  } catch {}
  if (token !== expectedToken) return;
  const view = resumeView();
  $('appView').hidden = true; $('loginView').hidden = true; view.hidden = false;
  view.dataset.reason = error?.isNetworkError ? 'network' : 'server';
  view.dataset.context = context ? 'available' : 'missing';
  $('offlineResumeTitle').textContent = error?.isNetworkError ? 'Connexion indisponible' : 'Service indisponible';
  $('offlineResumeMessage').textContent =
    'Ta session est conservée jusqu’à son expiration. Tes brouillons et opérations en attente restent sur cet appareil. ' +
    'Le serveur vérifiera tes accès avant la reprise. Aucune opération n’est envoyée pour le moment.';
  $('offlineResumeShop').textContent = context?.merchant.shop_id
    ? 'Boutique d’origine : ' + (context.merchant.active_shop_name || '#' + context.merchant.shop_id)
    : 'Contexte de boutique indisponible sur cet appareil. Il sera rechargé au retour du réseau.';
  clearTimeout(resumeTimer);
  resumeTimer = setTimeout(() => {
    if (token === expectedToken && !sessionIsUnexpired()) {
      logout('Session expirée. Reconnecte-toi : tes opérations en attente sont conservées.');
    }
  }, Math.min(2147483647, Math.max(1, sessionClaims(expectedToken).exp * 1000 - Date.now())));
}
async function verifyServerSession() {
  const expectedToken = token;
  if (!sessionIsUnexpired(expectedToken)) {
    logout('Session expirée. Tes opérations en attente sont conservées.');
    throw sessionFailure('Session expirée', 401);
  }
  const merchant = await api('/auth/me', {cache: 'no-store'});
  if (token !== expectedToken || !sameSessionIdentity(merchant, sessionClaims(expectedToken))) {
    throw sessionFailure('Le compte ou la boutique a changé. Opération conservée.', 409);
  }
  state.merchant = merchant;
  await rememberResumeContext(expectedToken);
  if (token !== expectedToken) throw sessionFailure('Session modifiée. Opération conservée.', 409);
  sessionNeedsCheck = false;
  return merchant;
}

async function api(path, options = {}) {
  const {requireJsonResponse = false, ...requestOptions} = options;
  const mutation = !['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase());
  if (mutation && path.startsWith('/pwa/') && !sessionIsUnexpired()) {
    logout('Session expirée. Tes opérations en attente sont conservées.');
    throw sessionFailure('Session expirée', 401);
  }
  if (mutation && path.startsWith('/pwa/') && sessionNeedsCheck && navigator.onLine) {
    await verifyServerSession();
  }
  const requestToken = token;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  if (requestToken) {
    headers.Authorization = 'Bearer ' + requestToken;
  }

  /*
   * Une erreur levée directement par fetch() correspond
   * à une vraie erreur réseau : elle n'est volontairement
   * pas transformée ici.
   */
  let response;
  try {
    response = await fetch(path, {...requestOptions, headers});
  } catch (error) {
    error.isNetworkError = true;
    sessionNeedsCheck = true;
    throw error;
  }
  if (requestToken !== token && path !== '/auth/login') {
    throw sessionFailure('La session a changé. Reprends dans le compte d’origine.', 409);
  }

  let body = null;

  try {
    body = await response.json();
  } catch (cause) {
    if (requireJsonResponse && response.ok) {
      const error = new Error('Confirmation incertaine : réponse illisible ou incomplète.');
      error.confirmationUncertain = true;
      error.responseStatus = response.status;
      throw error;
    }
  }

  if (requireJsonResponse && requestToken !== token) {
    throw sessionFailure('La session a changé. Reprends dans le compte d’origine.', 409);
  }

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
      path !== '/auth/login' && !path.startsWith('/auth/quick/') && !path.startsWith('/auth/passkeys/')
        ? 'Session expirée'
        : detail
    );

    error.status = response.status;
    error.isHttpError = true;
    error.body = body;

    if (
      response.status === 401 &&
      path !== '/auth/login' && !path.startsWith('/auth/quick/') && !path.startsWith('/auth/passkeys/')
    ) {
      logout('Session expirée ou refusée par le serveur. Tes opérations en attente sont conservées.');
    } else if (response.status === 403 && ['/auth/me', '/auth/shops'].includes(path)) {
      logout('Accès refusé par le serveur. Tes opérations en attente sont conservées.');
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
  if (name === 'more') refreshPasskeyList();
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
  if (!data || data.shop_id!==state.merchant?.shop_id) return;

  const financeFmt=value=>data.data_quality?.unknown_currency_count ? String(value)+' (devise non qualifiée)' : fmt(value);
  const activity = data.activity || {};
  const cashflow = data.cashflow || {};
  const receivables = data.receivables || {};
  const payables = data.payables || {};
  const stock = data.stock || {};
  const position = data.position || {};
  $('financeRefundsDue').textContent = financeFmt(data.refunds?.due || 0);
  $('financeRefundsPaid').textContent = financeFmt(cashflow.refunds_paid || 0);
  $('financeTimezone').textContent = 'Fuseau métier : ' + data.business_timezone + ' · Devise : '+data.currency+' · Dernière lecture : '+data.read_at+' · Hors gestion TVA';
  $('financeCurrentLabel').textContent='Encours actuel, arrêté le '+data.read_at+' — indépendant de la période ; solde historique indisponible';
  $('financeSupplierPaid').textContent=financeFmt(cashflow.purchases_paid);
  $('statRevenue').textContent=financeFmt(activity.sales_total);
  $('statDebt').textContent=financeFmt(receivables.total);
  $('statSupplierDebt').textContent=financeFmt(payables.total);
  $('statExpenses').textContent=financeFmt(cashflow.expenses_total);
  $('commercialPeriodRead').textContent=(data.since?'Activité du '+data.since+' au '+data.until:'Depuis le début — historique connu, origine non garantie')+' · '+data.business_timezone+' · '+data.currency+' · Lecture '+data.read_at;
  const quality = data.data_quality || {};
  $('financeQuality').hidden = quality.complete !== false;
  $('financeQuality').textContent = `${quality.unknown_receipts_count || 0} encaissement(s) sans date effective vérifiée (${financeFmt(quality.unknown_receipts_amount || 0)}), exclus des totaux de période. ${quality.unassessed_cancellations || 0} annulation(s) historique(s) à rapprocher. ${quality.unknown_currency_count || 0} opération(s) sans devise historique qualifiée. Le flux affiché est incomplet. ${quality.unknown_supplier_count || 0} règlement(s) fournisseur sans date qualifiée (${financeFmt(quality.unknown_supplier_amount || 0)}). ${quality.unknown_cost_lines || 0} ligne(s) de vente à coût non qualifié (${financeFmt(quality.unknown_cost_revenue || 0)} de CA).`;

  if ($('financeShopName')) {
    $('financeShopName').textContent =
      state.merchant?.active_shop_name ||
      state.merchant?.shop_name ||
      'Boutique active';
  }

  $('financeRevenue').textContent =
    financeFmt(activity.sales_total);

  $('financeGrossMargin').textContent =
    activity.gross_margin == null ? 'Indisponible — coûts non qualifiés' : financeFmt(activity.gross_margin);

  $('financeMarginRate').textContent =
    activity.gross_margin_rate == null ? '—' : financePercent(activity.gross_margin_rate);

  $('financeSalesPaid').textContent =
    financeFmt(activity.sales_paid);

  $('financeReceivables').textContent =
    financeFmt(receivables.total);

  $('financeOverdue').textContent =
    financeFmt(receivables.overdue) + ' en retard';

  $('financePayables').textContent =
    financeFmt(payables.total);

  $('financeExpenses').textContent =
    financeFmt(cashflow.expenses_total);

  $('financeCashflow').textContent =
    financeFmt(cashflow.net_cash_flow);

  $('financeStockValue').textContent =
    financeFmt(stock.value);

  $('financePotentialSales').textContent =
    financeFmt(stock.potential_sales_value);

  $('financeAssets').textContent =
    financeFmt(position.estimated_current_assets);

  $('financeLiabilities').textContent =
    financeFmt(position.estimated_current_liabilities);

  $('financeNetPosition').textContent =
    financeFmt(position.estimated_net_position);

  $('financePeriodLabel').textContent = data.since ? 'Activité du '+data.since+' au '+data.until : 'Depuis le début — historique connu';

  renderFinancePeriodButtons();
}

let financeRequest=0;
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
  const request=++financeRequest, before=token;
  invalidateFinance();
  renderFinancePeriodButtons();
  if($('commercialPeriod')) $('commercialPeriod').value=period;

  setFinanceStatus(
    "Chargement de l'analyse financière…"
  );

  try {
    const data = await api(
      '/pwa/finance/overview?period=' +
        encodeURIComponent(period) + ($('financeAsOf').value ? '&as_of=' + encodeURIComponent($('financeAsOf').value) : '') + (period==='custom'?'&since='+encodeURIComponent($('commercialSince').value)+'&until='+encodeURIComponent($('commercialUntil').value):'')
    );

    if(request!==financeRequest || before!==token) return;
    state.finance = data;
    renderFinanceOverview(data);
    await loadRefundsDue();
    setFinanceStatus();
  } catch (error) {
    if(request!==financeRequest || before!==token) return;
    invalidateFinance();
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
  $('productBarcodeBtn').hidden = true;
  $('internalBarcodeLabel').hidden = true;
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

// A suggestion only changes the unit after an explicit selection. Historical
// and scanned values remain verbatim in the editable field.
$('productUnitPreset')?.addEventListener('change', (event) => {
  if (!event.target.value) return;
  $('productUnit').value = event.target.value;
  event.target.value = '';
  $('productUnit').focus();
});

function fillProductForm(values = {}) {
  $('productName').value = values.name || '';
  $('productUnit').value = values.unit ?? 'unité';
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
  $('productBarcodeBtn').hidden = false;
  $('internalBarcodeLabel').hidden = true;
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

function logout(message = '') {
  hideResumeView();
  sessionNeedsCheck = true;
  localStorage.removeItem(RESUME_CONTEXT_KEY);
  quickAuthUI?.clear();
  token = '';
  localStorage.removeItem('whatzabi_token');
  state = { products: [], customers: [], sales: [], merchant: null, shops: [], currencyContext: null, finance: null, financePeriod: 'month' };
  $('appView').hidden = true;
  $('loginView').hidden = false;
  $('password').value = '';
  $('loginError').textContent = typeof message === 'string' ? message : '';

  if ($('offlineSyncBadge')) {
    $('offlineSyncBadge').hidden = true;
  }
  $('passkeyPassword').value = '';
  $('passkeyList').replaceChildren();
  updatePasskeysUI();
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
  const customers = state.customers.map(c=>({...c,debt:state.sales.filter(s=>s.customer_id===c.id && s.status!=='cancelled').reduce((n,s)=>n+Number(s.remaining_amount||0),0)}));
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

    return threshold > 0 && stock <= threshold;
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
                Total ${operationMoney(sale.total_amount,sale.currency_code)} ·
                Payé ${operationMoney(sale.paid_amount,sale.currency_code)} ·
                Reste ${operationMoney(sale.remaining_amount,sale.currency_code)}
              </small>
            </div>
            <strong>${operationMoney(sale.total_amount,sale.currency_code)}</strong>
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
            <strong>${operationMoney(sale.total_amount,sale.currency_code)}</strong>
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
                <small>Total ${operationMoney(sale.total_amount,sale.currency_code)} · payé ${operationMoney(sale.paid_amount,sale.currency_code)}</small>
              </div>
              <div class="receivable-end">
                <strong>${operationMoney(sale.remaining_amount,sale.currency_code)}</strong>
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
              <div class="item-meta"><span class="badge">${esc(sale.status)}</span> · ${esc(fmtSaleDate(sale.created_at))} · payé ${operationMoney(sale.paid_amount,sale.currency_code)}</div>
            </div>
            <div class="sale-item-end">
              <div class="money">${operationMoney(sale.total_amount,sale.currency_code)}</div>
              <span aria-hidden="true">›</span>
            </div>
          </button>`,
        )
        .join('')
    : '<article class="card muted">Aucune vente.</article>';

  const classicScope=[state.merchant?.id,state.merchant?.user_id,state.merchant?.shop_id].join(':');
  const classicSelection=state.classicRenderScope===classicScope?{customer:$('saleCustomer').value,product:$('saleProduct').value}:{customer:'',product:''};
  state.classicRenderScope=classicScope;
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
  if([...$('saleCustomer').options].some(o=>o.value===classicSelection.customer))$('saleCustomer').value=classicSelection.customer;
  if([...$('saleProduct').options].some(o=>o.value===classicSelection.product))$('saleProduct').value=classicSelection.product;

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
    operationMoney(sale.total_amount,sale.currency_code);

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
          <td style="text-align:right">${receiptEscape(operationMoney(item.unit_price,sale.currency_code))}</td>
          <td style="text-align:right">${receiptEscape(operationMoney(item.line_total,sale.currency_code))}</td>
        </tr>
      `;
    }).join('');

    const paymentText = (payments || []).length
      ? (payments || []).map((payment) =>
          receiptEscape(payment.channel || 'paiement') +
          ' : ' + receiptEscape(operationMoney(payment.amount,sale.currency_code))
        ).join('<br>')
      : 'Aucun paiement enregistré';

    const receiptNumber = sale.sale_number ?? sale.id;
    const cancelled = String(sale.status) === 'cancelled';
    const shareLines = (items || []).map((item) => {
      const product = state.products.find(
        (entry) => Number(entry.id) === Number(item.product_id)
      );
      const name = product?.name || ('Produit #' + item.product_id);
      return item.quantity + ' × ' + name + ' — ' + operationMoney(item.line_total,sale.currency_code);
    });
    const receiptShareText = [
      shopName,
      'Reçu de vente #' + receiptNumber,
      'Date : ' + fmtSaleDate(sale.created_at),
      'Client : ' + (customer?.name || 'Vente comptoir'),
      '',
      ...shareLines,
      '',
      'Total : ' + operationMoney(sale.total_amount,sale.currency_code),
      'Payé : ' + operationMoney(sale.paid_amount,sale.currency_code),
      'Reste : ' + operationMoney(sale.remaining_amount,sale.currency_code),
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
          <div class="total"><span>Total</span><span>${receiptEscape(operationMoney(sale.total_amount,sale.currency_code))}</span></div>
          <div><span>Payé</span><span>${receiptEscape(operationMoney(sale.paid_amount,sale.currency_code))}</span></div>
          <div><span>Reste</span><span>${receiptEscape(operationMoney(sale.remaining_amount,sale.currency_code))}</span></div>
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
    ' · reste ' + operationMoney(sale.remaining_amount,sale.currency_code) +
    ' · échéance ' + fmtDueDate(sale.due_date) +
    ' · paiement partiel possible';
  $('receivablePaymentAmount').value = String(sale.remaining_amount);
  $('receivablePaymentAmount').max = String(sale.remaining_amount);
  $('receivablePaymentReference').value = '';
  $('receivablePaymentSheet').hidden = false;
  PaymentJournal.open('client', sale.id);
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


  const button = $('receivablePaymentSubmitBtn');
  button.disabled = true;
  try {
    const confirmed = await PaymentJournal.send('client', {sale_id:sale.id,customer_id:sale.customer_id,amount,
      channel:$('receivablePaymentChannel').value,reference:$('receivablePaymentReference').value.trim() || null});
    if (!confirmed) return;

    closeReceivablePayment();
    await refresh();
    toast(
      amount === Number(sale.remaining_amount || 0)
        ? 'Créance soldée.'
        : 'Paiement enregistré. Créance mise à jour.'
    );
  } catch (error) {
    PaymentJournal.open('client', sale.id);
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
  closeVoiceSheet();
  const data = await api('/auth/select-shop', {
    method: 'POST',
    body: JSON.stringify({ shop_id: Number(shopId) }),
  });
  token = data.access_token;
  if (tokenPersistent) localStorage.setItem('whatzabi_token', token);
  state.merchant = data.merchant;
  financeRequest++;invalidateFinance();
  if($('commercialReceipt'))$('commercialReceipt').replaceChildren();
  for(const id of ['receivablePaymentSheet','supplierPaymentSheet','declaredPaymentReceipt'])if($(id))$(id).hidden=true;
  state.sales=[];state.customers=[];state.products=[];

  // Invalider immédiatement les indicateurs de l'ancienne boutique.
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
  let expectedToken = token;
  let merchant = await api('/auth/me');
  let shops = await api('/auth/shops');

  if (merchant.user_id && !merchant.shop_id && shops.length) {
    await selectShop(shops[0].id, { silent: true });
    expectedToken = token;
    merchant = await api('/auth/me');
    shops = await api('/auth/shops');
  }

  if (token !== expectedToken || !sameSessionIdentity(merchant, sessionClaims(expectedToken))) {
    throw sessionFailure('Session modifiée pendant le chargement.', 409);
  }
  const previousShop = state.merchant?.shop_id;
  state.merchant = merchant;
  state.shops = shops;
  await rememberResumeContext(expectedToken);
  sessionNeedsCheck = false;

  if (String(previousShop) !== String(merchant.shop_id)) {
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
    sessionNeedsCheck = true;
    void updateOfflineSyncBadge();
  }
);


window.addEventListener(
  'online',
  () => {
    window.setTimeout(
      () => {
        if ($('offlineResumeView') && !$('offlineResumeView').hidden) void boot();
        else void syncOfflineSales().catch(error => {
          if (error.isNetworkError) void suspendSession(error);
        });
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
  const refreshToken=token;
  const [currencyContext, products, customers, sales] = await Promise.all([
    api('/pwa/currencies/context'),
    api('/pwa/products'),
    api('/pwa/customers'),
    api('/pwa/sales'),
  ]);
  if(refreshToken!==token)return;
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

  updatePasskeysUI();

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
  if (!token || resumeRunning) return;
  if (!sessionIsUnexpired()) {
    logout('Session expirée. Reconnecte-toi : tes opérations en attente sont conservées.');
    return;
  }
  resumeRunning = true;
  try {
    await refresh();
    hideResumeView();
    $('loginView').hidden = true;
    $('appView').hidden = false;
    await updateOfflineSyncBadge();
    await syncOfflineSales();
  } catch (error) {
    // Only an explicit authentication decision removes the session.
    // Missing data, HTTP 5xx and network failures suspend it without touching outboxes.
    if (token) await suspendSession(error);
  } finally {
    resumeRunning = false;
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
    tokenPersistent = true;
    localStorage.setItem('whatzabi_token', token);
    hideResumeView();
    sessionNeedsCheck = true;
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

$('logoutBtn').addEventListener('click', signOut);
window.addEventListener('storage', event => {
  if (!tokenPersistent || event.key !== 'whatzabi_token' || event.newValue === token) return;
  // Do not transmit from an old tab after another tab logged out or changed account.
  token = event.newValue || '';
  sessionNeedsCheck = true;
  hideResumeView();
  state = {products: [], customers: [], sales: [], merchant: null, shops: [], currencyContext: null, finance: null, financePeriod: 'month'};
  $('appView').hidden = true;
  $('loginView').hidden = Boolean(token);
  if (token) void boot();
});

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
    const createdContext = [state.merchant?.id,state.merchant?.user_id,state.merchant?.shop_id].join(':');
    const created = await api('/pwa/customers', {
      method: 'POST',
      body: JSON.stringify({
        name: $('customerName').value,
        phone: $('customerPhone').value || null,
        debt: 0,
      }),
    });
    if (createdContext !== [state.merchant?.id,state.merchant?.user_id,state.merchant?.shop_id].join(':')) return;
    event.target.reset();
    state.customers.push(created);
    window.whatzabiCustomerCreated?.(created);
    try { await refresh(); toast('Client ajouté'); }
    catch (_) { toast('Client créé. Liste indisponible : actualiser sans recréer.'); }
  } catch (error) {
    toast(error.message);
  }
});

$('saleForm').addEventListener('submit', (event) => {
  event.preventDefault();
  const product=state.products.find(p=>p.id===Number($('saleProduct').value));
  const quantity=Number($('saleQty').value),customer=Number($('saleCustomer').value)||null;
  if(!product || !Number.isSafeInteger(quantity) || quantity<=0)return toast('Produit et quantité entière requis.');
  const amount=product.price*quantity,paid=customer?Number($('salePaid').value):amount;
  if(!Number.isSafeInteger(paid) || paid<0 || paid>amount)return toast('Montant payé invalide.');
  window.whatzabiPrepareSale?.({product,quantity,customer,paid,channel:$('saleChannel').value});
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
    $('settingsTimezone').value = data.business_timezone || '';
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
            business_timezone: $('settingsTimezone').value.trim(),
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
let voiceEpoch = 0;
let voiceOrigin = '';
const voiceScope = () => String(state.merchant?.id || '') + ':' + String(state.merchant?.shop_id || '');

function openVoiceSheet() {
  voiceEpoch++;
  voiceOrigin = voiceScope();
  $('voiceRecordBtn').disabled = false;
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
  voiceEpoch++;
  voiceOrigin = '';
  $('voiceTranscript').textContent = '';
  $('voiceReviewActions').hidden = true;
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
  const epoch = voiceEpoch, origin = voiceOrigin;
  const current = () => epoch === voiceEpoch && origin && origin === voiceScope() && !$('voiceSheet').hidden;
  cleanupVoiceStream();
  if (!current()) return;

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

    if (!current()) return;
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
    if (!current()) return;
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
  if (voiceOrigin !== voiceScope() || $('voiceSheet').hidden) return;
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
  marchandises: 'Marchandises', // Historical display only; new stock uses Achats.
  transport: 'Transport',
  loyer: 'Loyer',
  electricite: 'Électricité',
  eau: 'Eau',
  restauration: 'Restauration',
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
  const f=state.finance;if(!f)return false;
  const raw=entry.created_at;const d=new Date(/Z$|[+-]\d\d:\d\d$/.test(raw)?raw:raw+'Z');
  if(!Number.isFinite(d.getTime()))return false;
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:f.business_timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(d);
  const part=t=>parts.find(p=>p.type===t)?.value;const day=part('year')+'-'+part('month')+'-'+part('day');
  return (!f.since || day>=f.since) && (!f.until || day<=f.until);
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
            <strong class="expense-amount">− ${operationMoney(entry.amount,entry.currency_code)}</strong>
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

  await loadFinanceOverview(state.financePeriod || 'month');
}


let expenseScanFile = null;
let expenseScanPreviewUrl = null;

const EXPENSE_SCAN_ALLOWED_CATEGORIES = new Set(
  Object.keys(EXPENSE_CATEGORY_LABELS).filter(code => code !== 'marchandises'),
);

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

    const token = window.whatzabiAccessToken();

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
    void loadFinanceOverview(state.expensePeriod).then(renderExpenses);
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

    if(!state.finance) return toast('Actualise Finance avant l’export.');
    sinceInput.value = state.finance.since || '';
    untilInput.value = state.finance.until || '';
    sinceInput.required=false;untilInput.required=false;
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

    if(!sinceInput.value)params.delete('since');if(!untilInput.value)params.delete('until');
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
      <input data-camera-input type="file" accept="image/*" capture="environment" hidden>
      <input data-gallery-input type="file" accept="image/*" hidden>
    </div>
    <img data-preview alt="Photo du registre" hidden>
    <p data-status role="status" aria-live="polite"></p>
    <form data-review hidden>
      <div class="sale-photo-fields">
        <label>Date du registre<input data-date type="date" required></label>
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
      <div data-lines></div>
      <p data-total></p>
      <details><summary>Voir le JSON corrigé</summary><pre data-json></pre></details>
      <label class="sale-photo-check"><input data-confirm type="checkbox" required>
        J'ai vérifié la date, les produits, les paiements, le regroupement et le stock.
        Ces ventes ne sont pas déjà enregistrées.</label>
      <button type="submit" class="primary">Valider et importer les ventes</button>
    </form>`;
  document.body.appendChild(dialog);
  const get = name => dialog.querySelector('[data-' + name + ']');
  const form = get('review');
  const status = get('status');
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'
  }[c]));
  const context = () => ({
    merchant:state.merchant?.id, shop:state.merchant?.shop_id, token
  });
  const same = before => before &&
    before.merchant === state.merchant?.id &&
    before.shop === state.merchant?.shop_id &&
    before.token === token && can('sale.create');
  let origin = null, extraction = null, controller = null;
  let previewUrl = null, busy = false;

  function reset() {
    extraction = null;
    form.hidden = true;
    form.reset();
    get('lines').replaceChildren();
    get('json').textContent = '';
    get('total').textContent = '';
    get('warnings').textContent = '';
    get('preview').hidden = true;
    get('preview').removeAttribute('src');
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
  }
  function syncAccess() {
    menu.hidden = !can('sale.create');
    if (dialog.open && !same(origin)) {
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
  menu.addEventListener('click', () => {
    if (!token || !can('sale.create') || !state.merchant?.shop_id) {
      toast('Sélectionne une boutique et reconnecte-toi.');
      return;
    }
    if (busy) return;
    reset();
    origin = context();
    status.textContent = '';
    get('shop').textContent = 'Boutique : ' +
      (state.merchant.active_shop_name || state.merchant.shop_name || origin.shop);
    dialog.showModal();
  });
  get('close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    controller?.abort();
    reset();
  });
  get('camera').addEventListener('click', () => get('camera-input').click());
  get('gallery').addEventListener('click', () => get('gallery-input').click());

  async function request(path, body, json = false) {
    if (!same(origin)) throw new Error('La boutique ou la session a changé. Recommence.');
    controller = new AbortController();
    const active = controller;
    const timer = setTimeout(() => active.abort(), 90000);
    try {
      const response = await fetch(path, {
        method:'POST', cache:'no-store', signal:active.signal,
        headers:{
          Authorization:'Bearer ' + origin.token,
          ...(json ? {'Content-Type':'application/json'} : {})
        },
        body:json ? JSON.stringify(body) : body
      });
      const result = await response.json();
      if (!same(origin)) throw new Error('La boutique ou la session a changé. Recommence.');
      if (!response.ok) {
        if (response.status === 401) logout();
        throw new Error(typeof result.detail === 'string' ? result.detail :
          'Vérifie les champs obligatoires (' + response.status + ').');
      }
      return result;
    } finally {
      clearTimeout(timer);
      if (controller === active) controller = null;
    }
  }
  async function convert(file) {
    if (!file?.type.startsWith('image/')) throw new Error('Choisis une photo.');
    if (file.size > 20 * 1024 * 1024) {
      throw new Error('Photo trop volumineuse : maximum 20 Mo avant compression.');
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
        throw new Error('Impossible de préparer cette photo. Utilise un JPEG ou PNG plus léger.');
      }
      return blob;
    } catch (error) {
      throw new Error(error.message || 'Format illisible. Convertis la photo HEIC en JPEG.');
    } finally {
      URL.revokeObjectURL(url);
    }
  }
  function setBusy(value) {
    busy = value;
    dialog.querySelectorAll('input, select, button').forEach(control => {
      if (!control.hasAttribute('data-close')) control.disabled = value;
    });
  }
  async function selected(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || busy) return;
    reset();
    setBusy(true);
    status.textContent = 'Lecture de la photo…';
    const before = origin;
    try {
      const blob = await convert(file);
      if (!dialog.open || !same(before)) return;
      previewUrl = URL.createObjectURL(blob);
      get('preview').src = previewUrl;
      get('preview').hidden = false;
      const data = new FormData();
      data.append('image', blob, 'registre.jpg');
      const result = await request('/pwa/sales/photo/extract', data);
      if (!dialog.open || !same(before) ||
          String(result.shop_id) !== String(before.shop)) return;
      extraction = result;
      if (!result.result.lines.length) {
        throw new Error('Aucune ligne lisible. Reprends la photo.');
      }
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
          description:'Produit à vérifier', quantity:'Quantité à vérifier',
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
    } catch (error) {
      if (dialog.open && same(before)) {
        status.textContent = error.name === 'AbortError' ?
          'Lecture interrompue. Réessaie.' : error.message;
      }
    } finally {
      setBusy(false);
    }
  }
  get('camera-input').addEventListener('change', selected);
  get('gallery-input').addEventListener('change', selected);
  function payload() {
    const number = input => input.value === '' ? null : Number(input.value);
    return {
      confirmed:get('confirm').checked,
      shop_id:Number(origin.shop),
      source_sha256:extraction.source_sha256,
      document_date:get('date').value,
      currency:get('currency').value.toUpperCase(),
      affect_stock:get('stock').value === 'deduct',
      rows:[...get('lines').querySelectorAll('[data-row]')].map(field => {
        const read = name => field.querySelector('[data-' + name + ']');
        const row = extraction.result.lines[Number(field.dataset.row)];
        return {
          row_number:row.row_number,
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
      ' ' + data.currency;
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
    if (busy || !form.reportValidity() || !same(origin)) return;
    const data = payload();
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
      if (dialog.open) {
        status.textContent = error.name === 'AbortError' ?
          'Réponse interrompue : réessaie la même validation, les doublons sont protégés.' :
          error.message;
      }
    } finally {
      setBusy(false);
    }
  });
})();

// Passkeys: the new access token lives in memory and is never persisted.
function updatePasskeysUI() {
  const supported = Boolean(window.WhatzabiPasskeys?.supported());
  $('passkeyLoginBtn').hidden = !passkeysEnabled || !supported;
  $('passkeyLoginHint').hidden = !passkeysEnabled || !supported;
  $('passkeyCard').hidden = true; // Shown only after the account-specific rollout check.
  quickAuthUI?.update(passkeysEnabled);
  $('passkeyLoginBtn').disabled = passkeyBusy;
  $('passkeyEnrollBtn').disabled = passkeyBusy || !supported;
  $('passkeyRecoverBtn').disabled = passkeyBusy;
  $('passkeyRefreshBtn').disabled = passkeyBusy;
  $('passkeyList').querySelectorAll('button').forEach((button) => { button.disabled = passkeyBusy; });
}

async function refreshPasskeyList() {
  if (!passkeysEnabled || !state.merchant?.user_id) return;
  try {
    const keys = await api('/auth/passkeys');
    $('passkeyList').replaceChildren();
    for (const key of keys) {
      const item = document.createElement('li');
      const label = document.createElement('span');
      label.textContent = key.name + ' ';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'ghost';
      button.textContent = 'Supprimer';
      button.setAttribute('aria-label', 'Supprimer ' + key.name);
      button.addEventListener('click', () => revokePasskey(key.id));
      item.append(label, button);
      $('passkeyList').append(item);
    }
    if (!keys.length) $('passkeyStatus').textContent = 'Aucune Passkey enregistrée.';
    updatePasskeysUI();
  } catch (error) {
    $('passkeyStatus').textContent = window.WhatzabiPasskeys.message(error);
  }
}

async function passkeyAction(action, statusId = 'passkeyStatus') {
  if (passkeyBusy) return;
  passkeyBusy = true;
  $(statusId).textContent = '';
  updatePasskeysUI();
  try {
    await action();
  } catch (error) {
    $(statusId).textContent = window.WhatzabiPasskeys.message(error);
  } finally {
    passkeyBusy = false;
    $('passkeyPassword').value = '';
    updatePasskeysUI();
  }
}

$('passkeyLoginBtn').addEventListener('click', () => passkeyAction(async () => {
  const result = await window.WhatzabiPasskeys.authenticate(api);
  token = result.access_token;
  tokenPersistent = false;
  localStorage.removeItem('whatzabi_token');
  try {
    await refresh();
    $('loginView').hidden = true;
    $('appView').hidden = false;
    await updateOfflineSyncBadge();
    await syncOfflineSales();
  } catch (error) {
    logout();
    throw error;
  }
}, 'loginError'));

$('passkeyEnrollForm').addEventListener('submit', (event) => {
  event.preventDefault();
  passkeyAction(async () => {
    const password = $('passkeyPassword').value;
    $('passkeyPassword').value = '';
    await window.WhatzabiPasskeys.register(api, password, $('passkeyName').value.trim() || 'Mon appareil');
    $('passkeyStatus').textContent = 'Passkey enregistrée. Vous pouvez l’utiliser à votre prochaine connexion.';
    await refreshPasskeyList();
  });
});

function revokePasskey(passkeyId) {
  if (!$('passkeyPassword').reportValidity()) return;
  if (!window.confirm('Supprimer cette Passkey ? Votre mot de passe restera utilisable.')) return;
  passkeyAction(async () => {
    await api('/auth/passkeys/revoke', { method: 'POST', body: JSON.stringify({
      passkey_id: passkeyId, password: $('passkeyPassword').value,
    }) });
    $('passkeyStatus').textContent = 'Passkey supprimée.';
    await api('/auth/me'); // Revoking the current Passkey also invalidates this session.
    await refreshPasskeyList();
  });
}

$('passkeyRecoverBtn').addEventListener('click', () => {
  if (!$('passkeyPassword').reportValidity()) return;
  if (!window.confirm('Révoquer toutes vos Passkeys et appareils enregistrés ? Vous pourrez en ajouter après connexion par mot de passe.')) return;
  passkeyAction(async () => {
    await api('/auth/passkeys/recover', { method: 'POST', body: JSON.stringify({
      password: $('passkeyPassword').value,
    }) });
    logout();
    $('loginError').textContent = 'Passkeys révoquées. Reconnectez-vous avec votre mot de passe.';
  });
});
$('passkeyRefreshBtn').addEventListener('click', refreshPasskeyList);

quickAuthUI = window.WhatzabiQuickAuth?.init({ api, identity: () => state.merchant, logout,
  accept: async (result) => {
    token = result.access_token;
    tokenPersistent = false;
    localStorage.removeItem('whatzabi_token');
    try {
      await refresh();
      $('loginView').hidden = true;
      $('appView').hidden = false;
      await updateOfflineSyncBadge();
      await syncOfflineSales();
    } catch (error) { logout(); throw error; }
  },
});

fetch('/auth/passkeys/capabilities', { cache: 'no-store', credentials: 'same-origin' })
  .then((response) => response.ok ? response.json() : { enabled: false })
  .then((result) => { passkeysEnabled = result.enabled === true; updatePasskeysUI(); })
  .catch(() => { passkeysEnabled = false; updatePasskeysUI(); });

$('changeAccountBtn').addEventListener('click', async () => {
  await signOut();
  $('phone').value = '';
  $('password').value = '';
  $('phone').focus();
});

async function signOut() {
  let unconfirmed = false;
  try {
    // Historical logout keeps its exact local-only behavior.
    if (!tokenPersistent && token && state.merchant?.user_id) await api('/auth/quick/logout', { method: 'POST' });
  } catch { unconfirmed = true; }
  finally {
    logout();
    if (unconfirmed) $('loginError').textContent = 'Déconnexion locale. Révocation serveur non confirmée ; une session PIN expire au plus tard quinze minutes après sa création.';
  }
}

$('productBarcodeBtn').addEventListener('click', async () => {
  const id = editingProductId, scope = voiceScope();
  if (!id || !can('product.update')) return;
  const button = $('productBarcodeBtn');
  button.disabled = true;
  try {
    const label = await api(`/pwa/products/${id}/internal-barcode`, {method:'POST'});
    if (id !== editingProductId || scope !== voiceScope()) return;
    $('internalBarcodeName').textContent = label.name;
    $('internalBarcodeImage').src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(label.svg);
    $('internalBarcodeLabel').dataset.barcode = label.barcode;
    $('internalBarcodeLabel').hidden = false;
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
});
$('internalBarcodePrint').addEventListener('click', () => {
  document.body.classList.add('printing-internal-label');
  try { window.print(); } finally { document.body.classList.remove('printing-internal-label'); }
});

let refundDraft = null;
const refundScope = () => `${state.merchant?.id}:${state.merchant?.shop_id}`;
const refundDraftKey = () => 'whatzabi:refund:v1:' + refundScope();
function fillRefundDraft(draft) {
  refundDraft = draft;
  $('refundForm').hidden = !can('refund.create');
  $('refundAmount').value = draft.amount;
  $('refundChannel').value = draft.channel;
  $('refundEffectiveAt').value = draft.effective_at;
  $('refundReference').value = draft.reference || '';
  $('refundConfirmed').checked = false;
}
async function loadRefundsDue() {
  const scope = refundScope();
  const rows = await api('/pwa/finance/refunds-due');
  if (scope !== refundScope()) return;
  $('refundForm').hidden = true; refundDraft = null;
  const list = $('refundDueList'); list.replaceChildren();
  for (const row of rows.filter(r => r.remaining > 0)) {
    const line = document.createElement('p');
    line.textContent = `Vente #${row.sale_id} : ${fmt(row.remaining)} à restituer ; créance annulée ${fmt(row.receivable_waived)}. `;
    if (can('refund.create')) {
      const button = document.createElement('button'); button.type = 'button';
      button.dataset.refundSale = row.sale_id; button.textContent = 'Saisir un remboursement effectué';
      button.onclick = () => {
        const saved = localStorage.getItem(refundDraftKey());
        if (saved) return fillRefundDraft(JSON.parse(saved));
        fillRefundDraft({sale_id:row.sale_id,amount:row.remaining,channel:'cash',effective_at:new Date().toISOString(),reference:null,idempotency_key:crypto.randomUUID(),scope});
      }; line.appendChild(button);
    } list.appendChild(line);
  }
  const saved = localStorage.getItem(refundDraftKey());
  if (saved && can('refund.create')) fillRefundDraft(JSON.parse(saved));
}
$('refundForm').addEventListener('submit', async event => {
  event.preventDefault();
  if (!refundDraft || refundDraft.scope !== refundScope() || !can('refund.create') || !$('refundConfirmed').checked) return;
  const scope = refundScope(), key = refundDraftKey();
  const existing = localStorage.getItem(key);
  const draft = existing ? JSON.parse(existing) : {...refundDraft,
    amount:Number($('refundAmount').value),channel:$('refundChannel').value,
    effective_at:$('refundEffectiveAt').value,reference:$('refundReference').value || null};
  localStorage.setItem(key,JSON.stringify(draft));
  const {scope:origin,...payload} = draft;
  $('refundSubmit').disabled = true;
  try {
    const result = await api('/pwa/finance/refunds',{method:'POST',body:JSON.stringify({...payload,confirmed:true})});
    localStorage.removeItem(key);
    if (scope !== refundScope()) return;
    $('refundReceipt').textContent = `Remboursement #${result.id} enregistré : ${fmt(result.amount)} · ${result.channel} · ${result.effective_at}`;
    await loadFinanceOverview(state.financePeriod);
  } catch (error) {
    // A definitive validation refusal created no refund. Permit correction,
    // while retaining the same identity after an uncertain network outcome.
    if ([400,422].includes(error.status)) localStorage.removeItem(key);
    if(scope===refundScope()) $('refundReceipt').textContent = error.message +
      ([400,422].includes(error.status) ? ' — corrige la saisie puis confirme.' : ' — le reçu sera recherché avec la même clé à la reprise.');
  }
  finally { $('refundSubmit').disabled = false; }
});
$('financeAsOf').addEventListener('change',()=>loadFinanceOverview(state.financePeriod));
$('financeCashExport').addEventListener('click',async()=>{
  const f=state.finance;if(!f)return;
  const query=new URLSearchParams();if(f.since)query.set('since',f.since);if(f.until)query.set('until',f.until);
  const before=token;
  const response=await fetch('/pwa/exports/cash.csv?'+query,{headers:{Authorization:'Bearer '+token}});
  if(before!==token || state.finance!==f)return;
  if(!response.ok)return toast('Export indisponible');
  const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download='encaissements.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});

// D01/D02: durable immutable requests, scoped to the authenticated origin.
const PaymentJournal = (() => {
  const prefix = 'whatzabi:declared-payment:v1:';
  const origin = () => [state.merchant?.id, state.merchant?.user_id, state.merchant?.shop_id].join(':');
  const key = (kind, id) => prefix + origin() + ':' + kind + ':' + id;
  const read = k => { const raw = localStorage.getItem(k); return raw ? JSON.parse(raw) : null; };
  const write = (k, value) => localStorage.setItem(k, JSON.stringify(value));
  const forms = {};
  function view(kind) { return kind === 'client' ? 'receivablePayment' : 'supplierPayment'; }
  function open(kind, id) {
    const k = key(kind, id), record = read(k), base = view(kind);
    const pending = record && record.status !== 'confirmed' ? record : null;
    forms[kind] = {key:k, id, origin:origin(), generation:record?.payload.idempotency_key || null,
      effective_at:pending?.payload.effective_at || new Date().toISOString()};
    for (const [field, name] of [['Amount','amount'],['Channel','channel'],['Reference','reference']]) {
      const input = $(base + field);
      if (pending) input.value = pending.payload[name] ?? '';
      input.disabled = !!pending;
    }
    let date = $(base + 'Effective');
    if (!date) {
      date = document.createElement('p'); date.id = base + 'Effective'; date.setAttribute('role','status');
      $(base + 'Meta').after(date);
    }
    date.textContent = 'Date effective déclarée : ' + forms[kind].effective_at + ' · règlement enregistré, aucun paiement bancaire';
    $(base + 'SubmitBtn').textContent = pending ? 'Reprendre le même règlement' : 'Confirmer le règlement';
    let correct = $(base + 'Correct');
    if (!correct) {
      correct = document.createElement('button'); correct.id = base + 'Correct'; correct.type = 'button';
      correct.textContent = 'Corriger le règlement refusé'; $(base + 'SubmitBtn').after(correct);
      correct.onclick = () => {
        const f = forms[kind], r = f && read(f.key);
        if (!r || r.status !== 'refused') return;
        // Only a certain 400/422 refusal can begin a new editable cycle.
        write(f.key, {...r,status:'confirmed',refused:true}); open(kind,f.id);
      };
    }
    correct.hidden = pending?.status !== 'refused';
    $(base + 'Amount').focus();
    return !!pending;
  }
  function valid(receipt, record) {
    const p = record.payload, target = record.kind === 'client' ? 'sale_id' : 'purchase_id';
    return receipt && Number.isInteger(receipt.id) && receipt.id > 0 &&
      receipt.idempotency_key === p.idempotency_key && receipt[target] === p[target] &&
      receipt.merchant_id === record.merchant && receipt.shop_id === record.shop &&
      receipt.amount === p.amount && receipt.channel === p.channel &&
      (receipt.reference || null) === (p.reference || null) &&
      new Date(receipt.effective_at).getTime() === new Date(p.effective_at).getTime() &&
      Array.isArray(receipt.allocations) && receipt.allocations.length > 0 &&
      receipt.allocations.every(a => Number.isInteger(a.amount) && a.amount > 0) &&
      receipt.allocations.reduce((sum,a) => sum+a.amount,0) === p.amount;
  }
  async function transmit(k, record) {
    if (record.origin !== origin()) throw Error('Revenir au compte et à la boutique d’origine.');
    const before = origin();
    try {
      const receipt = await api(record.kind === 'client' ? '/pwa/payments' : '/pwa/supplier-payments',
        {method:'POST',body:JSON.stringify(record.payload)});
      if (!valid(receipt,record)) throw Error('Reçu non conforme : règlement conservé, reprendre la même opération.');
      // Store the valid receipt with its operation, even if navigation changed.
      write(k + ':receipt:' + receipt.id,{...record,status:'confirmed',receipt});
      write(k,{...record,status:'confirmed',receipt});
      if (before !== origin()) return false;
      render(); showReceipt(receipt,record.kind); return true;
    } catch (error) {
      if ([400,422].includes(error.status)) write(k,{...record,status:'refused',error:error.message});
      if (before === origin()) render();
      throw error;
    }
  }
  async function send(kind, payload) {
    if (!navigator.locks) throw Error('Ce navigateur ne permet pas la reprise sûre entre onglets. Utiliser un navigateur compatible.');
    const f = forms[kind];
    if (!f || f.origin !== origin()) throw Error('Le contexte a changé. Rouvrir le règlement.');
    return navigator.locks.request(f.key,async () => {
      if (f.origin !== origin()) throw Error('Le contexte a changé.');
      let record = read(f.key);
      if (record?.status === 'confirmed' && record.payload.idempotency_key !== f.generation) {
        showReceipt(record.receipt,kind);
        throw Error('Un autre onglet a confirmé ce règlement. Rouvrir pour un nouveau règlement distinct.');
      }
      if (!record || record.status === 'confirmed') {
        record = {kind,origin:origin(),merchant:state.merchant.id,shop:state.merchant.shop_id,
          status:'pending',payload:{...payload,effective_at:f.effective_at,idempotency_key:crypto.randomUUID()}};
        write(f.key,record); // Must succeed before any HTTP request.
      }
      if (record.status === 'refused') throw Error('Règlement refusé sans écriture. Utiliser « Corriger le règlement refusé ».');
      return transmit(f.key,record);
    });
  }
  function showReceipt(receipt,kind) {
    if (!receipt) return;
    let panel = $('declaredPaymentReceipt');
    if (!panel) { panel = document.createElement('div');panel.id='declaredPaymentReceipt';panel.className='voice-sheet';
      const card=document.createElement('div');card.className='voice-sheet-card';card.setAttribute('role','dialog');card.setAttribute('aria-label','Reçu du règlement');
      const close=document.createElement('button');close.type='button';close.textContent='Fermer le reçu';close.onclick=()=>{panel.hidden=true;};
      card.append(close,document.createElement('pre'));panel.append(card);document.body.append(panel); }
    panel.querySelector('pre').textContent = 'Reçu '+(kind==='client'?'client':'fournisseur')+' #'+receipt.id+'\nBoutique #'+receipt.shop_id+
      '\nDate effective : '+receipt.effective_at+'\nMontant : '+operationMoney(receipt.amount,receipt.currency_code)+'\nCanal : '+receipt.channel+
      '\nAllocations : '+JSON.stringify(receipt.allocations);
    panel.hidden=false;panel.querySelector('button').focus();
  }
  function render() {
    let panel=$('declaredPayments');
    if (!panel) { panel=document.createElement('details');panel.id='declaredPayments';$('appView')?.prepend(panel); }
    panel.replaceChildren();const summary=document.createElement('summary');summary.textContent='Règlements conservés et reçus';panel.append(summary);
    const start=prefix+origin()+':';
    for (let n=0;n<localStorage.length;n++) {
      const k=localStorage.key(n);if (!k.startsWith(start)) continue;
      let r;try {r=read(k);}catch(_){summary.textContent='Règlement illisible — rapprochement requis';continue;}
      const button=document.createElement('button');button.type='button';
      if(!k.includes(':receipt:'))button.dataset.paymentLiveKind=r.kind;
      button.textContent=(r.status==='confirmed'?'Consulter le reçu':'Reprendre le règlement en attente')+' · '+r.kind+' · '+operationMoney(r.payload.amount,r.receipt?.currency_code);
      button.onclick=async()=>{try{if(r.status==='confirmed')showReceipt(r.receipt,r.kind);else await navigator.locks.request(k,()=>transmit(k,read(k)));}catch(e){toast(e.message);}};
      if(r.status!=='confirmed')panel.open=true;
      panel.append(button);
    }
  }
  addEventListener('storage',()=>{if(state.merchant)render();});
  return {open,send,render};
})();

async function commercialConfirm(title, summary) {
  const before=[token,state.merchant?.id,state.merchant?.shop_id].join(':');
  const focus=document.activeElement;
  return new Promise(resolve=>{
    const dialog=document.createElement('dialog');dialog.className='commercial-confirm';
    const heading=document.createElement('h2');heading.textContent=title;
    const details=document.createElement('p');details.textContent=(state.merchant?.active_shop_name || state.merchant?.shop_name || 'Boutique')+' · '+(summary.date || new Date().toISOString())+'\n'+(summary.lines||[]).join('\n')+'\nTotal '+fmt(summary.total)+' · Payé '+fmt(summary.paid)+' · Reste '+fmt(summary.remaining)+'\nCanal : '+summary.channel+(summary.tendered!=null?' · Remis '+fmt(summary.tendered)+' · Rendu '+fmt(summary.tendered-summary.paid):'');
    const cancel=document.createElement('button');cancel.type='button';cancel.textContent='Revenir à la saisie';
    const accept=document.createElement('button');accept.type='button';accept.textContent='Confirmer maintenant';accept.className='primary';
    const done=value=>{dialog.close();dialog.remove();focus?.focus();resolve(value && before===[token,state.merchant?.id,state.merchant?.shop_id].join(':'));};
    cancel.onclick=()=>done(false);accept.onclick=()=>done(true);dialog.addEventListener('cancel',e=>{e.preventDefault();done(false);});
    dialog.append(heading,details,cancel,accept);document.body.append(dialog);dialog.showModal();cancel.focus();
  });
}
function commercialReceipt(label, receipt) {
  let box=$('commercialReceipt');
  if(!box){box=document.createElement('details');box.id='commercialReceipt';$('appView').prepend(box);}
  box.replaceChildren();const heading=document.createElement('summary');heading.textContent=label+' #'+(receipt.sale_number || receipt.id)+' — reçu';
  const text=document.createElement('p');text.textContent='Boutique '+(state.merchant?.active_shop_name || state.merchant?.shop_id)+' · '+receipt.created_at+'\nTotal '+operationMoney(receipt.total_amount,receipt.currency_code)+' · Payé '+operationMoney(receipt.paid_amount,receipt.currency_code)+' · Reste '+operationMoney(receipt.remaining_amount,receipt.currency_code);
  if(receipt.channel)text.textContent+='\nCanal déclaré : '+receipt.channel;
  for(const payment of receipt.payment_details || [])text.textContent+='\nRèglement #'+payment.id+' · '+operationMoney(payment.amount,receipt.currency_code)+' · '+payment.channel+' · '+(payment.effective_at || 'date effective inconnue')+' · allocations '+JSON.stringify(payment.allocations);
  box.append(heading,text);box.open=true;
}

function invalidateFinance() {
  state.finance=null;
  for(const id of ['financeRevenue','financeGrossMargin','financeMarginRate','financeSalesPaid','financeSupplierPaid','financeReceivables','financeOverdue','financePayables','financeExpenses','financeCashflow','financeStockValue','financePotentialSales','financeAssets','financeLiabilities','financeNetPosition','financeRefundsDue','financeRefundsPaid','statRevenue','statExpenses','statDebt','statSupplierDebt']) if($(id))$(id).textContent='—';
  if($('commercialPeriodRead'))$('commercialPeriodRead').textContent='Lecture en attente — aucun résultat de période exportable';
  if($('commercialDetailRows'))$('commercialDetailRows').replaceChildren();
}
(() => {
  const bar=document.createElement('section');bar.className='card commercial-period';bar.setAttribute('aria-label','Période commune Accueil et Finance');
  bar.innerHTML='<label>Période <select id="commercialPeriod"><option value="today">Aujourd’hui</option><option value="yesterday">Hier</option><option value="week">Cette semaine</option><option value="month" selected>Ce mois</option><option value="previous_month">Mois précédent</option><option value="custom">Personnalisée</option><option value="all">Depuis le début</option></select></label><label>Début inclus<input id="commercialSince" type="date"></label><label>Fin incluse<input id="commercialUntil" type="date"></label><button id="commercialApply" type="button">Appliquer la période</button><p id="commercialPeriodRead" role="status"></p>';
  $('dashboard').before(bar);
  $('commercialPeriod').onchange=()=>{if($('commercialPeriod').value!=='custom')void loadFinanceOverview($('commercialPeriod').value);};
  $('commercialApply').onclick=()=>loadFinanceOverview($('commercialPeriod').value);
  // Separate current positions physically from period activity.
  const position=document.createElement('section');position.className='card commercial-current';position.append($('financeCurrentLabel'));
  for(const id of ['financeReceivables','financePayables','financeStockValue','financeAssets']) {const card=$(id).closest('article');if(card)position.append(card);}
  $('finance').append(position);
  const panel=document.createElement('section');panel.className='card';
  panel.innerHTML='<h2>Opérations justificatives</h2><label>Indicateur<select id="commercialDetailKind"><option value="sales">CA actif révisé</option><option value="receipts">Encaissements clients</option><option value="supplier_payments">Décaissements fournisseurs</option><option value="purchases">Achats reçus</option><option value="expenses">Dépenses</option><option value="refunds">Remboursements clients</option><option value="receivables">Créances actuelles</option><option value="payables">Dettes actuelles</option></select></label><button id="commercialDetails" type="button">Voir les opérations</button><button id="commercialExport" type="button">Exporter ce détail</button><p id="commercialDetailStatus" role="status"></p><div id="commercialDetailRows"></div><button id="commercialPrevious" type="button">Page précédente</button><button id="commercialNext" type="button">Page suivante</button>';
  $('finance').append(panel);let page=1,total=0,detailRequest=0;
  const params=()=>{const f=state.finance;if(!f)throw Error('Actualise la période avant de consulter ou exporter.');const q=new URLSearchParams();if(f.since)q.set('since',f.since);if(f.until)q.set('until',f.until);return q;};
  async function detail(){const current=++detailRequest,before=token,f=state.finance;try{
    const q=params();q.set('kind',$('commercialDetailKind').value);q.set('page',page);q.set('size','25');
    $('commercialDetailRows').replaceChildren();const data=await api('/pwa/finance/details?'+q);
    if(current!==detailRequest || before!==token || f!==state.finance)return;
    total=data.count;$('commercialDetailStatus').textContent=total+' opérations · page '+page+' · Total daté '+fmt(data.known_amount)+' · Sans date : '+data.unknown_count+' / '+fmt(data.unknown_amount)+' · '+(data.basis==='current'?'Encours actuel, hors période':$('commercialPeriodRead').textContent);
    for(const row of data.rows){const line=document.createElement('p');line.textContent='#'+row.id+' · opération #'+row.operation_id+' · '+operationMoney(row.amount,row.currency_code)+' · '+(row.effective_at || 'Date inconnue — exclue des totaux de période')+' · '+(row.channel || '');$('commercialDetailRows').append(line);}
    $('commercialPrevious').disabled=page===1;$('commercialNext').disabled=page*25>=total;
  }catch(e){if(current===detailRequest && before===token && f===state.finance){$('commercialDetailRows').replaceChildren();$('commercialDetailStatus').textContent=e.message;}}}
  $('commercialDetailKind').onchange=()=>{detailRequest++;page=1;total=0;$('commercialDetailRows').replaceChildren();$('commercialDetailStatus').textContent='Choix modifié : consulter le détail.';};
  $('commercialDetails').onclick=()=>{page=1;void detail();};$('commercialPrevious').onclick=()=>{if(page>1){page--;void detail();}};$('commercialNext').onclick=()=>{if(page*25<total){page++;void detail();}};
  $('commercialExport').onclick=async()=>{try{let kind=$('commercialDetailKind').value;const q=params(),before=token,f=state.finance;
    
    if(['receipts','refunds'].includes(kind)){q.set('movement',kind==='receipts'?'receipt':'refund');kind='cash';}
    const response=await fetch('/pwa/exports/'+kind+'.csv?'+q,{headers:{Authorization:'Bearer '+token}});if(!response.ok)throw Error('Export indisponible');
    const blob=await response.blob();if(before!==token || f!==state.finance)return;
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=kind+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){toast(e.message);}};
})();

function operationMoney(amount,currency){return currency ? new Intl.NumberFormat('fr-FR',{style:'currency',currency,maximumFractionDigits:2}).format(amount) : String(amount)+' (devise historique non qualifiée)';}
