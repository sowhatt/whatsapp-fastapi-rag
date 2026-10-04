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