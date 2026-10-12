from __future__ import annotations

from enum import StrEnum


class BusinessType(StrEnum):
    COMMERCE = "commerce"
    RESTAURANT = "restaurant"
    RENTAL = "rental"
    SERVICE = "service"


class StoreCapability(StrEnum):
    CATALOG = "catalog"
    CART = "cart"
    CHECKOUT = "checkout"
    DELIVERY = "delivery"
    PICKUP = "pickup"
    SEO = "seo"
    MEDIA = "media"
    NOTIFICATIONS = "notifications"
    PAYMENTS = "payments"


_COMMON = {
    StoreCapability.SEO,
    StoreCapability.MEDIA,
    StoreCapability.NOTIFICATIONS,
}

_DEFAULTS = {
    BusinessType.COMMERCE: _COMMON | {
        StoreCapability.CATALOG,
        StoreCapability.CART,
        StoreCapability.CHECKOUT,
        StoreCapability.PICKUP,
        StoreCapability.DELIVERY,
    },
    BusinessType.RESTAURANT: _COMMON | {
        StoreCapability.CATALOG,
        StoreCapability.CART,
        StoreCapability.CHECKOUT,
        StoreCapability.PICKUP,
        StoreCapability.DELIVERY,
    },
    BusinessType.RENTAL: _COMMON | {
        StoreCapability.CATALOG,
        StoreCapability.CHECKOUT,
    },
    BusinessType.SERVICE: _COMMON | {
        StoreCapability.CATALOG,
        StoreCapability.CHECKOUT,
    },
}


def parse_business_type(value: str | BusinessType) -> BusinessType:
    if isinstance(value, BusinessType):
        return value
    try:
        return BusinessType(str(value).strip().lower())
    except ValueError as exc:
        raise ValueError("Type d'activité Online invalide.") from exc


def default_capabilities(business_type: str | BusinessType) -> tuple[str, ...]:
    kind = parse_business_type(business_type)
    return tuple(sorted(cap.value for cap in _DEFAULTS[kind]))


def normalize_capabilities(
    values: list[str] | tuple[str, ...] | set[str] | None,
    *,
    business_type: str | BusinessType,
) -> tuple[str, ...]:
    if values is None:
        return default_capabilities(business_type)

    normalized: set[str] = set()
    allowed = {cap.value for cap in StoreCapability}
    for value in values:
        candidate = str(value).strip().lower()
        if candidate not in allowed:
            raise ValueError(f"Capacité Online inconnue : {candidate}")
        normalized.add(candidate)

    # SEO/media are platform-level primitives, not optional vertical logic.
    normalized.add(StoreCapability.SEO.value)
    normalized.add(StoreCapability.MEDIA.value)
    return tuple(sorted(normalized))


def has_capability(
    capabilities: tuple[str, ...] | list[str] | set[str],
    capability: str | StoreCapability,
) -> bool:
    target = capability.value if isinstance(capability, StoreCapability) else str(capability).strip().lower()
    return target in set(capabilities)


def require_capability(
    capabilities: tuple[str, ...] | list[str] | set[str],
    capability: str | StoreCapability,
) -> None:
    if not has_capability(capabilities, capability):
        target = capability.value if isinstance(capability, StoreCapability) else str(capability).strip().lower()
        raise ValueError(f"Capacité Online non activée : {target}")
