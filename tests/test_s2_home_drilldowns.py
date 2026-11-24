from pathlib import Path
import subprocess


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


def _check_behavior(pattern):
    result = subprocess.run(
        ["node", "--test", "--test-name-pattern", pattern,
         "tests/js/home_drilldowns.test.cjs"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_home_low_stock_card_opens_critical_stock():
    _check_behavior("stock card opens")


def test_critical_stock_uses_stock_and_threshold():
    _check_behavior("critical stock includes")


def test_generic_home_drilldown_handler_is_present():
    assert "document.querySelectorAll('[data-open-tab]')" in APP_JS
    assert "showTab(button.dataset.openTab)" in APP_JS
    assert "button.dataset.scrollTarget" in APP_JS
    assert "scrollIntoView" in APP_JS
