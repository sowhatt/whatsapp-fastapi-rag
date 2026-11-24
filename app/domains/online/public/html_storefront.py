from __future__ import annotations

import json
from html import escape
from typing import Any


def _money(value: int | None, currency: str) -> str:
    if value is None:
        return "Prix sur demande"
    return f"{int(value):,}".replace(",", " ") + f" {currency}"


_AVAILABILITY = {
    "in_stock": ("En stock", "ok"),
    "low_stock": ("Dernières unités", "low"),
    "out_of_stock": ("Épuisé", "out"),
}


def _availability_state(product: dict[str, Any]) -> str:
    state = product.get("availability")
    if state in _AVAILABILITY:
        return state
    return "in_stock" if product.get("available") else "out_of_stock"


def _badge(product: dict[str, Any]) -> str:
    label, tone = _AVAILABILITY[_availability_state(product)]
    return f'<span class="badge badge-{tone}">{label}</span>'


def _info_band(store: dict[str, Any]) -> str:
    """Infos pratiques en tête de vitrine : retrait, livraison, paiement, adresse."""
    capabilities = set(store.get("capabilities") or [])
    items = []
    if "pickup" in capabilities:
        items.append("Retrait en boutique")
    if "delivery" in capabilities:
        items.append("Livraison")
    items.append("Paiement à la livraison ou au retrait")
    items.append("Mobile Money (à confirmer avec le commerçant)")
    where = ", ".join(x for x in (store.get("address"), store.get("city")) if x)
    if where:
        items.append(where)
    pills = "".join(f"<li>{escape(str(item))}</li>" for item in items)
    return f'<ul class="info-band" aria-label="Informations pratiques">{pills}</ul>'


def _rayons(products: list[dict[str, Any]]) -> str:
    names: list[str] = []
    for product in products:
        name = product.get("category")
        if name and name not in names:
            names.append(str(name))
    if len(names) < 2:
        return ""
    chips = '<button type="button" class="rayon active" data-category="">Tous</button>' + "".join(
        f'<button type="button" class="rayon" data-category="{escape(n, quote=True)}">{escape(n)}</button>'
        for n in names
    )
    return f'<nav class="rayons" aria-label="Rayons">{chips}</nav>'


def _head(title: str, description: str, canonical: str, image_url: str | None, json_ld: dict) -> str:
    image_meta = f'<meta property="og:image" content="{escape(image_url, quote=True)}">' if image_url else ""
    structured = '<script type="application/ld+json">' + json.dumps(json_ld, ensure_ascii=False) + '</script>'
    return f'''
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description, quote=True)}">
<link rel="canonical" href="{escape(canonical, quote=True)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{escape(title, quote=True)}">
<meta property="og:description" content="{escape(description, quote=True)}">
<meta property="og:url" content="{escape(canonical, quote=True)}">
{image_meta}
{structured}
<link rel="stylesheet" href="/shop/assets/storefront.css">
'''


def render_store_page(*, store: dict[str, Any], products: list[dict[str, Any]], base_url: str) -> str:
    slug = str(store["slug"])
    canonical = (store.get("canonical_domain") or f"{base_url}/shop/{slug}").rstrip("/")
    title = store.get("seo_title") or store.get("display_name") or "Boutique Whatzabi"
    description = store.get("seo_description") or store.get("description") or f"Découvrez les produits de {title}."
    json_ld = {
        "@context": "https://schema.org",
        "@type": store.get("schema_type") or "Store",
        "name": store.get("display_name"),
        "url": canonical,
        "description": description,
    }
    cards = []
    for product in products:
        product_slug = product.get("seo_slug") or f"produit-{product['id']}"
        product_url = f"/shop/{escape(slug)}/p/{escape(str(product_slug))}"
        image = product.get("image_url")
        if image:
            image_html = f'<img src="{escape(image, quote=True)}" alt="{escape(str(product["name"]), quote=True)}" loading="lazy">'
        else:
            image_html = '<div class="product-placeholder">Photo bientôt disponible</div>'
        disabled = "" if product.get("available") and product.get("price") is not None else "disabled"
        category = escape(str(product.get("category") or ""), quote=True)
        cards.append(f'''
<article class="product-card" data-category="{category}">
  <a class="product-image" href="{product_url}">{image_html}</a>
  <div class="product-body">
    <a class="product-name" href="{product_url}">{escape(str(product["name"]))}</a>
    <div class="product-meta">
      <span class="product-price">{escape(_money(product.get("price"), store.get("currency") or "XOF"))}</span>
      {_badge(product)}
    </div>
    <div class="card-actions" data-product-id="{int(product["id"])}">
      <button class="add-to-cart" data-product-id="{int(product["id"])}" {disabled}>Ajouter au panier</button>
      <div class="qty-stepper" hidden><button type="button" class="qty-minus" aria-label="Retirer une unité">−</button><span class="qty-value">0</span><button type="button" class="qty-plus" aria-label="Ajouter une unité">+</button></div>
    </div>
  </div>
</article>
''')
    logo = store.get("logo_url")
    logo_html = f'<img class="store-logo" src="{escape(logo, quote=True)}" alt="Logo">' if logo else ""
    return f'''<!doctype html>
<html lang="fr">
<head>{_head(title, description, canonical, store.get("banner_url") or logo, json_ld)}</head>
<body data-store-slug="{escape(slug, quote=True)}">
<header class="store-header"><div class="header-inner">{logo_html}<div><h1>{escape(str(store.get("display_name") or "Boutique"))}</h1><p>{escape(str(store.get("description") or ""))}</p></div><button id="cart-button" class="cart-button">Panier <span id="cart-count">0</span></button></div></header>
<main class="store-main">
{_info_band(store)}
<section class="catalog-toolbar"><form method="get" action="/shop/{escape(slug)}"><input type="search" name="q" placeholder="Rechercher un produit"><button type="submit">Rechercher</button></form></section>
{_rayons(products)}
<section class="catalog-grid">{''.join(cards) if cards else '<p>Aucun produit publié pour le moment.</p>'}</section>
</main>
<div id="toast" class="toast" hidden></div>
<script src="/shop/assets/storefront.js" defer></script>
</body></html>'''


def render_product_page(*, store: dict[str, Any], product: dict[str, Any], base_url: str) -> str:
    slug = str(store["slug"])
    product_slug = product.get("seo_slug") or f"produit-{product['id']}"
    canonical = f"{base_url}/shop/{slug}/p/{product_slug}"
    title = product.get("seo_title") or product.get("name") or "Produit"
    description = product.get("seo_description") or product.get("description") or f"Découvrez {title}."
    image = product.get("image_url")
    currency = product.get("currency") or store.get("currency") or "XOF"
    price = product.get("price")
    json_ld = {"@context": "https://schema.org", "@type": "Product", "name": product.get("name"), "image": [image] if image else [], "description": description, "offers": {"@type": "Offer", "url": canonical, "priceCurrency": currency, "price": str(price) if price is not None else None, "availability": "https://schema.org/InStock" if product.get("available") else "https://schema.org/OutOfStock"}}
    image_html = f'<img class="detail-image" src="{escape(image, quote=True)}" alt="{escape(str(product["name"]), quote=True)}">' if image else '<div class="detail-placeholder">Photo bientôt disponible</div>'
    disabled = "" if product.get("available") and price is not None else "disabled"
    return f'''<!doctype html>
<html lang="fr">
<head>{_head(title, description, canonical, image, json_ld)}</head>
<body data-store-slug="{escape(slug, quote=True)}">
<header class="store-header"><div class="header-inner"><a class="back-link" href="/shop/{escape(slug)}">← Boutique</a><div class="store-name">{escape(str(store.get("display_name") or ""))}</div><button id="cart-button" class="cart-button">Panier <span id="cart-count">0</span></button></div></header>
<main class="product-detail"><div class="detail-media">{image_html}</div><div class="detail-content"><h1>{escape(str(product.get("name") or ""))}</h1><div class="detail-price">{escape(_money(price, currency))}</div><div class="detail-stock">{_badge(product)}{'<p class="stock-note">Quantité limitée : le commerçant confirme votre commande avant préparation.</p>' if _availability_state(product) == "low_stock" else ""}</div><p>{escape(str(product.get("description") or ""))}</p><button class="add-to-cart primary-action" data-product-id="{int(product["id"])}" {disabled}>Ajouter au panier</button></div></main>
<div id="toast" class="toast" hidden></div>
<script src="/shop/assets/storefront.js" defer></script>
</body></html>'''