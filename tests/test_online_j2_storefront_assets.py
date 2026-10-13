from app.domains.online.public.storefront_assets import STOREFRONT_CSS, STOREFRONT_JS


def test_storefront_has_real_cart_drawer_and_checkout():
    assert "cart-drawer" in STOREFRONT_CSS
    assert "checkout-form" in STOREFRONT_JS
    assert "data-cart-action" in STOREFRONT_JS
    assert "/checkout" in STOREFRONT_JS
    assert "Le tiroir panier arrive" not in STOREFRONT_JS
