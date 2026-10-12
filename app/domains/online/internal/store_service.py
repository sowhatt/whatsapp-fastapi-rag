from __future__ import annotations

import json
import re
import unicodedata

from sqlalchemy.orm import Session

from app.domains.online.foundation.business import default_capabilities, normalize_capabilities, parse_business_type
from app.domains.online.internal.models import OnlineStore
from app.models.merchant import Merchant


def normalize_store_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        char for char in normalized if not unicodedata.combining(char)
    )
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) < 3:
        raise ValueError("Le slug de boutique doit contenir au moins 3 caractères.")
    return slug[:80]


def get_public_store(*, slug: str, db: Session) -> OnlineStore | None:
    normalized_slug = normalize_store_slug(slug)
    return (
        db.query(OnlineStore)
        .filter(
            OnlineStore.slug == normalized_slug,
            OnlineStore.is_active.is_(True),
        )
        .first()
    )


def get_or_create_store(
    *,
    merchant_id: int,
    db: Session,
    slug: str | None = None,
    display_name: str | None = None,
    business_type: str = "commerce",
    capabilities: list[str] | tuple[str, ...] | set[str] | None = None,
) -> OnlineStore:
    merchant = db.query(Merchant).filter(Merchant.id == merchant_id).first()
    if merchant is None:
        raise ValueError("Commerçant introuvable.")

    existing = (
        db.query(OnlineStore)
        .filter(OnlineStore.merchant_id == merchant_id)
        .first()
    )
    if existing is not None:
        return existing

    base_name = display_name or merchant.shop_name or f"boutique-{merchant_id}"
    candidate = normalize_store_slug(slug or base_name)

    collision = db.query(OnlineStore).filter(OnlineStore.slug == candidate).first()
    if collision is not None:
        candidate = normalize_store_slug(f"{candidate}-{merchant_id}")

    kind = parse_business_type(business_type)
    resolved_capabilities = normalize_capabilities(capabilities, business_type=kind)

    store = OnlineStore(
        merchant_id=merchant_id,
        slug=candidate,
        display_name=(display_name or merchant.shop_name or "Ma boutique")[:150],
        business_type=kind.value,
        capabilities_json=json.dumps(list(resolved_capabilities)),
        currency="XOF",
        country_code="BJ",
        template="essential",
        is_active=True,
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def update_store(
    *,
    merchant_id: int,
    db: Session,
    display_name: str | None = None,
    description: str | None = None,
    business_type: str | None = None,
    capabilities: list[str] | tuple[str, ...] | set[str] | None = None,
    logo_url: str | None = None,
    banner_url: str | None = None,
    primary_color: str | None = None,
    accent_color: str | None = None,
    template: str | None = None,
    country_code: str | None = None,
    currency: str | None = None,
    seo_title: str | None = None,
    seo_description: str | None = None,
    canonical_domain: str | None = None,
    address: str | None = None,
    city: str | None = None,
    postal_code: str | None = None,
    latitude: str | None = None,
    longitude: str | None = None,
    is_active: bool | None = None,
) -> OnlineStore:
    store = (
        db.query(OnlineStore)
        .filter(OnlineStore.merchant_id == merchant_id)
        .first()
    )
    if store is None:
        store = get_or_create_store(merchant_id=merchant_id, db=db)

    if display_name is not None:
        store.display_name = display_name[:150]
    if business_type is not None:
        kind = parse_business_type(business_type)
        store.business_type = kind.value
        if capabilities is None:
            store.capabilities_json = json.dumps(list(default_capabilities(kind)))
    if capabilities is not None:
        resolved = normalize_capabilities(capabilities, business_type=store.business_type)
        store.capabilities_json = json.dumps(list(resolved))
    if description is not None:
        store.description = description[:500]
    if logo_url is not None:
        store.logo_url = logo_url[:1000]
    if banner_url is not None:
        store.banner_url = banner_url[:1000]
    if primary_color is not None:
        store.primary_color = primary_color[:20]
    if accent_color is not None:
        store.accent_color = accent_color[:20]
    if template is not None:
        if template not in {"essential", "boutique", "premium"}:
            raise ValueError("Template Online invalide.")
        store.template = template
    if country_code is not None:
        store.country_code = country_code.upper()[:2]
    if currency is not None:
        store.currency = currency.upper()[:3]
    if seo_title is not None:
        store.seo_title = seo_title[:180]
    if seo_description is not None:
        store.seo_description = seo_description[:320]
    if canonical_domain is not None:
        store.canonical_domain = canonical_domain[:255]
    if address is not None:
        store.address = address[:300]
    if city is not None:
        store.city = city[:120]
    if postal_code is not None:
        store.postal_code = postal_code[:30]
    if latitude is not None:
        store.latitude = latitude[:40]
    if longitude is not None:
        store.longitude = longitude[:40]
    if is_active is not None:
        store.is_active = is_active

    db.commit()
    db.refresh(store)
    return store


def get_store_capabilities(store: OnlineStore) -> tuple[str, ...]:
    if not store.capabilities_json:
        return default_capabilities(store.business_type)
    try:
        raw = json.loads(store.capabilities_json)
    except (TypeError, ValueError):
        return default_capabilities(store.business_type)
    return normalize_capabilities(raw, business_type=store.business_type)
