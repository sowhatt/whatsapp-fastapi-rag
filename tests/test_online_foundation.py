import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.foundation import (
    BusinessType,
    StoreCapability,
    build_store_schema_type,
    default_capabilities,
    require_capability,
)
from app.domains.online.internal.store_service import (
    get_or_create_store,
    get_store_capabilities,
    update_store,
)
from app.models.merchant import Merchant


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _merchant(db, suffix: str):
    merchant = Merchant(
        whatsapp_number=f"foundation-{suffix}",
        shop_name=f"Business {suffix}",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return merchant


def test_commerce_is_backward_compatible_default(db):
    merchant = _merchant(db, "commerce")
    store = get_or_create_store(merchant_id=merchant.id, db=db)

    assert store.business_type == BusinessType.COMMERCE.value
    capabilities = get_store_capabilities(store)
    assert StoreCapability.CATALOG.value in capabilities
    assert StoreCapability.CART.value in capabilities
    assert StoreCapability.CHECKOUT.value in capabilities
    assert StoreCapability.SEO.value in capabilities
    assert StoreCapability.MEDIA.value in capabilities


def test_restaurant_gets_delivery_capability_without_restaurant_domain_code(db):
    merchant = _merchant(db, "restaurant")
    store = get_or_create_store(
        merchant_id=merchant.id,
        db=db,
        business_type="restaurant",
    )

    capabilities = get_store_capabilities(store)
    assert store.business_type == "restaurant"
    assert "delivery" in capabilities
    assert "cart" in capabilities
    assert build_store_schema_type(store.business_type) == "Restaurant"


def test_switching_vertical_resets_default_capabilities(db):
    merchant = _merchant(db, "switch")
    store = get_or_create_store(merchant_id=merchant.id, db=db)
    assert "pickup" in get_store_capabilities(store)

    store = update_store(
        merchant_id=merchant.id,
        db=db,
        business_type="rental",
    )

    assert store.business_type == "rental"
    assert get_store_capabilities(store) == default_capabilities("rental")
    assert "cart" not in get_store_capabilities(store)


def test_custom_capabilities_keep_platform_seo_and_media(db):
    merchant = _merchant(db, "custom")
    store = get_or_create_store(
        merchant_id=merchant.id,
        db=db,
        capabilities=["catalog"],
    )

    capabilities = get_store_capabilities(store)
    assert capabilities == ("catalog", "media", "seo")


def test_unknown_business_type_is_rejected(db):
    merchant = _merchant(db, "unknown")
    with pytest.raises(ValueError, match="Type d'activité"):
        get_or_create_store(
            merchant_id=merchant.id,
            db=db,
            business_type="pharmacy-space-station",
        )


def test_capability_guard_fails_closed():
    with pytest.raises(ValueError, match="checkout"):
        require_capability(("catalog", "seo"), "checkout")


@pytest.mark.parametrize(
    ("business_type", "schema_type"),
    [
        ("commerce", "Store"),
        ("restaurant", "Restaurant"),
        ("rental", "LocalBusiness"),
        ("service", "ProfessionalService"),
    ],
)
def test_seo_schema_type_per_vertical(business_type, schema_type):
    assert build_store_schema_type(business_type) == schema_type
