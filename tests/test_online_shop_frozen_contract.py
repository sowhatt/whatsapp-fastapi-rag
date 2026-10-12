from pathlib import Path


SHOP_FROZEN_FILES = (
    "app/main.py",
    "app/db/tenant.py",
    "app/services/sales_service.py",
    "app/services/customer_catalog_service.py",
    "app/models/product_publication.py",
)


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_shop_main_does_not_mount_online_routes_or_startup():
    source = _read("app/main.py")
    assert "online_public" not in source
    assert "online_admin" not in source
    assert "online_storefront" not in source
    assert "install_online_" not in source


def test_shop_sales_and_tenant_do_not_depend_on_online_domain():
    assert "app.domains.online" not in _read("app/services/sales_service.py")
    assert "app.domains.online" not in _read("app/db/tenant.py")


def test_whatsapp_catalog_contract_stays_independent_from_online():
    source = _read("app/services/customer_catalog_service.py")
    assert "app.domains.online" not in source
    assert "available_stock" not in source


def test_legacy_product_publication_schema_is_not_extended_for_online_seo():
    source = _read("app/models/product_publication.py")
    assert "seo_slug" not in source
    assert "seo_title" not in source
    assert "seo_description" not in source


def test_online_has_separate_entrypoint():
    source = _read("app/online_main.py")
    assert 'FastAPI(title="Whatzabi Online")' in source
    assert "online_public_router" in source
    assert "online_storefront_web_router" in source
