from app.domains.online.public.html_storefront import render_product_page, render_store_page


def test_store_page_renders_catalog_and_seo():
    store = {
        "slug": "chez-awa",
        "display_name": "Chez Awa",
        "description": "Épicerie à Cotonou",
        "currency": "XOF",
        "country_code": "BJ",
        "seo_title": "Chez Awa - Boutique en ligne",
        "seo_description": "Achetez chez Awa en ligne.",
        "canonical_domain": None,
        "logo_url": None,
        "banner_url": None,
    }
    products = [{
        "id": 1,
        "name": "Riz parfumé 25 kg",
        "price": 19500,
        "available": True,
        "image_url": "https://cdn.example/riz.jpg",
        "seo_slug": "riz-parfume-25-kg",
    }]

    html = render_store_page(store=store, products=products, base_url="https://whatzabi.test")

    assert "Chez Awa - Boutique en ligne" in html
    assert "Riz parfumé 25 kg" in html
    assert "/shop/chez-awa/p/riz-parfume-25-kg" in html
    assert "application/ld+json" in html
    assert "Ajouter au panier" in html


def test_product_page_renders_product_offer_jsonld():
    store = {"slug":"chez-awa","display_name":"Chez Awa","currency":"XOF"}
    product = {
        "id": 1,
        "name": "Riz parfumé 25 kg",
        "price": 19500,
        "available": True,
        "description": "Riz parfumé premium",
        "image_url": "https://cdn.example/riz.jpg",
        "currency": "XOF",
        "seo_slug": "riz-parfume-25-kg",
        "seo_title": "Riz parfumé 25 kg",
        "seo_description": "Achetez votre riz parfumé.",
    }

    html = render_product_page(store=store, product=product, base_url="https://whatzabi.test")

    assert '"@type": "Product"' in html
    assert '"price": "19500"' in html
    assert "https://schema.org/InStock" in html
    assert "Ajouter au panier" in html

def _store(**extra):
    base = {"slug": "chez-awa", "display_name": "Chez Awa", "currency": "XOF", "country_code": "BJ"}
    base.update(extra)
    return base


def test_store_page_shows_availability_badges():
    products = [
        {"id": 1, "name": "Riz", "price": 100, "available": True, "availability": "in_stock"},
        {"id": 2, "name": "Huile", "price": 200, "available": True, "availability": "low_stock"},
        {"id": 3, "name": "Sucre", "price": 300, "available": False, "availability": "out_of_stock"},
    ]
    html = render_store_page(store=_store(), products=products, base_url="https://w.test")
    assert "En stock" in html and "Dernières unités" in html and "Épuisé" in html


def test_store_page_badge_falls_back_on_available_flag():
    html = render_store_page(
        store=_store(), base_url="https://w.test",
        products=[{"id": 1, "name": "Riz", "price": 100, "available": False}],
    )
    assert "Épuisé" in html


def test_store_page_info_band_reflects_capabilities():
    html = render_store_page(
        store=_store(capabilities=["catalog", "pickup"], address="Rue 12", city="Cotonou"),
        products=[], base_url="https://w.test",
    )
    assert "Retrait en boutique" in html
    assert "Livraison" not in html
    assert "Paiement à la livraison ou au retrait" in html
    assert "Rue 12, Cotonou" in html


def test_store_page_has_quantity_stepper_on_each_card():
    html = render_store_page(
        store=_store(), base_url="https://w.test",
        products=[{"id": 7, "name": "Riz", "price": 100, "available": True}],
    )
    assert 'class="card-actions" data-product-id="7"' in html
    assert "qty-minus" in html and "qty-plus" in html


def test_rayons_only_when_two_categories_or_more():
    one = [{"id": 1, "name": "A", "price": 1, "available": True, "category": "Epicerie"}]
    two = one + [{"id": 2, "name": "B", "price": 1, "available": True, "category": "Boissons"}]
    assert 'class="rayons"' not in render_store_page(store=_store(), products=one, base_url="https://w.test")
    html = render_store_page(store=_store(), products=two, base_url="https://w.test")
    assert 'class="rayons"' in html and 'data-category="Boissons"' in html


def test_product_page_low_stock_explains_confirmation():
    product = {"id": 1, "name": "Huile", "price": 200, "available": True, "availability": "low_stock", "currency": "XOF"}
    html = render_product_page(store=_store(), product=product, base_url="https://w.test")
    assert "Dernières unités" in html and "confirme votre commande" in html


def test_storefront_assets_wire_stepper_and_rayons():
    from app.domains.online.public.storefront_assets import STOREFRONT_CSS, STOREFRONT_JS
    assert "function syncCards" in STOREFRONT_JS and ".qty-plus" in STOREFRONT_JS and ".rayon" in STOREFRONT_JS
    assert "[hidden]{display:none!important}" in STOREFRONT_CSS and ".badge-low" in STOREFRONT_CSS
