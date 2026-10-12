from __future__ import annotations

from dataclasses import dataclass

from .business import BusinessType, parse_business_type


_SCHEMA_TYPES = {
    BusinessType.COMMERCE: "Store",
    BusinessType.RESTAURANT: "Restaurant",
    BusinessType.RENTAL: "LocalBusiness",
    BusinessType.SERVICE: "ProfessionalService",
}


def build_store_schema_type(business_type: str | BusinessType) -> str:
    return _SCHEMA_TYPES[parse_business_type(business_type)]


@dataclass(frozen=True, slots=True)
class SeoProfile:
    title: str
    description: str | None
    canonical_domain: str | None
    schema_type: str

    @classmethod
    def for_store(
        cls,
        *,
        business_type: str | BusinessType,
        display_name: str,
        description: str | None,
        seo_title: str | None,
        seo_description: str | None,
        canonical_domain: str | None,
    ) -> "SeoProfile":
        return cls(
            title=(seo_title or display_name)[:180],
            description=(seo_description or description or None),
            canonical_domain=canonical_domain,
            schema_type=build_store_schema_type(business_type),
        )
