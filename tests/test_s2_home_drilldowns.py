from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "app/pwa/index.html").read_text()
APP_JS = (ROOT / "app/pwa/app.js").read_text()


def test_home_sales_card_opens_sales_list():
    assert 'id="statSalesCard"' in INDEX
    assert 'data-open-tab="sales"' in INDEX
    assert 'data-scroll-target="saleList"' in INDEX


def test_home_receivables_card_opens_receivables():
    assert 'id="statCustomerDebtCard"' in INDEX
    assert 'data-open-tab="customers"' in INDEX
    assert 'data-scroll-target="receivableList"' in INDEX


def test_home_supplier_debt_card_opens_payables():
    assert 'id="statSupplierDebtCard"' in INDEX
    assert 'data-open-tab="purchases"' in INDEX
    assert 'data-scroll-target="supplierPayablesList"' in INDEX


def test_home_low_stock_card_opens_critical_stock():
    assert 'id="statLowStockCard"' in INDEX
    assert 'data-open-tab="catalog"' in INDEX
    assert 'data-scroll-target="criticalStockList"' in INDEX
    assert 'id="criticalStockList"' in INDEX
    assert 'id="criticalStockItems"' in INDEX


def test_critical_stock_uses_stock_and_threshold():
    assert "const lowStockProducts = products.filter(" in APP_JS
    assert (
        "Number(product.stock || 0) <= Number(product.threshold || 0)"
        in APP_JS
    )
    assert "$('criticalStockItems').innerHTML" in APP_JS
    assert "Stock ${stock}" in APP_JS
    assert "seuil ${threshold}" in APP_JS
    assert "Rupture" in APP_JS
    assert "Faible" in APP_JS


def test_generic_home_drilldown_handler_is_present():
    assert "document.querySelectorAll('[data-open-tab]')" in APP_JS
    assert "showTab(button.dataset.openTab)" in APP_JS
    assert "button.dataset.scrollTarget" in APP_JS
    assert "scrollIntoView" in APP_JS
