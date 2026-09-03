from app.rbac import has_permission
from app.services.merchant_service import normalize_whatsapp_number, phone_lookup_candidates


def test_normalize_whatsapp_number_accepts_pwa_and_meta_formats():
    assert normalize_whatsapp_number("+33 6 03 88 70 70") == "33603887070"
    assert normalize_whatsapp_number("33603887070") == "33603887070"


def test_phone_lookup_candidates_keep_legacy_plus_format():
    assert phone_lookup_candidates("33603887070") == (
        "33603887070",
        "+33603887070",
    )


def test_owner_has_all_permissions():
    assert has_permission("OWNER", "staff.manage") is True


def test_seller_cannot_adjust_stock():
    assert has_permission("SELLER", "stock.adjust") is False
    assert has_permission("SELLER", "sale.create") is True
