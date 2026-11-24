import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.db import schema as _schema  # noqa: F401
from app.db.base import Base
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.routers.pwa_settings import (
    CommerceSettingsUpdate,
    get_commerce_settings,
    update_commerce_settings,
)


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    merchant = Merchant(
        whatsapp_number="22900000999",
        shop_name="Groupe Settings Test",
        subscription_status="pilot",
        business_type="general_retail",
        country_code=None,
    )
    db.add(merchant)
    db.flush()

    centre = Shop(
        merchant_id=merchant.id,
        name="Centre",
        code="centre-settings",
        address="Ancienne adresse Centre",
        currency_code="XOF",
    )

    nord = Shop(
        merchant_id=merchant.id,
        name="Nord",
        code="nord-settings",
        address="Adresse Nord",
        currency_code="XOF",
    )

    db.add_all([centre, nord])
    db.flush()

    manager = MerchantUser(
        merchant_id=merchant.id,
        full_name="Manager Settings",
        role="MANAGER",
        password_hash=hash_password("motdepasse123"),
        is_active=True,
    )

    seller = MerchantUser(
        merchant_id=merchant.id,
        full_name="Seller Settings",
        role="SELLER",
        password_hash=hash_password("motdepasse123"),
        is_active=True,
    )

    db.add_all([manager, seller])
    db.commit()

    return merchant, centre, nord, manager, seller


def activate_context(db, user, shop, role):
    db.info["pwa_user_id"] = user.id
    db.info["pwa_role"] = role
    db.info["pwa_shop_id"] = shop.id
    db.info["resolved_shop_id"] = shop.id


def payload(
    *,
    shop_name="Groupe Settings Modifié",
    business_type="pharmacy",
    country_code="BJ",
    address="Nouvelle adresse Centre",
):
    return CommerceSettingsUpdate(
        shop_name=shop_name,
        business_type=business_type,
        country_code=country_code,
        active_shop_address=address,
    )


def test_get_settings_uses_active_shop_and_allows_country_none():
    db = make_db()
    merchant, centre, _nord, manager, _seller = seed(db)

    activate_context(db, manager, centre, "MANAGER")

    result = get_commerce_settings(
        merchant=merchant,
        db=db,
    )

    assert result.shop_name == "Groupe Settings Test"
    assert result.business_type == "general_retail"
    assert result.country_code is None

    assert result.active_shop_id == centre.id
    assert result.active_shop_name == "Centre"
    assert result.active_shop_address == "Ancienne adresse Centre"
    assert result.currency_code == "XOF"

    assert result.role == "MANAGER"


def test_manager_can_update_commerce_and_active_shop_address():
    db = make_db()
    merchant, centre, nord, manager, _seller = seed(db)

    activate_context(db, manager, centre, "MANAGER")

    result = update_commerce_settings(
        payload=payload(),
        merchant=merchant,
        db=db,
    )

    assert result.shop_name == "Groupe Settings Modifié"
    assert result.business_type == "pharmacy"
    assert result.country_code == "BJ"
    assert result.active_shop_address == "Nouvelle adresse Centre"

    db.refresh(merchant)
    db.refresh(centre)
    db.refresh(nord)

    assert merchant.shop_name == "Groupe Settings Modifié"
    assert merchant.business_type == "pharmacy"
    assert merchant.country_code == "BJ"

    assert centre.address == "Nouvelle adresse Centre"

    # L'autre boutique ne doit jamais être modifiée.
    assert nord.address == "Adresse Nord"


def test_manager_can_clear_country_and_address():
    db = make_db()
    merchant, centre, _nord, manager, _seller = seed(db)

    merchant.country_code = "BJ"
    db.commit()

    activate_context(db, manager, centre, "MANAGER")

    result = update_commerce_settings(
        payload=payload(
            country_code=None,
            address=None,
        ),
        merchant=merchant,
        db=db,
    )

    assert result.country_code is None
    assert result.active_shop_address is None

    db.refresh(merchant)
    db.refresh(centre)

    assert merchant.country_code is None
    assert centre.address is None


def test_seller_can_read_settings():
    db = make_db()
    merchant, centre, _nord, _manager, seller = seed(db)

    activate_context(db, seller, centre, "SELLER")

    result = get_commerce_settings(
        merchant=merchant,
        db=db,
    )

    assert result.active_shop_name == "Centre"
    assert result.role == "SELLER"


def test_seller_cannot_update_settings():
    db = make_db()
    merchant, centre, _nord, _manager, seller = seed(db)

    activate_context(db, seller, centre, "SELLER")

    with pytest.raises(HTTPException) as exc:
        update_commerce_settings(
            payload=payload(),
            merchant=merchant,
            db=db,
        )

    assert exc.value.status_code == 403

    db.refresh(merchant)
    db.refresh(centre)

    assert merchant.shop_name == "Groupe Settings Test"
    assert merchant.business_type == "general_retail"
    assert merchant.country_code is None
    assert centre.address == "Ancienne adresse Centre"


def test_switching_active_shop_changes_settings_shop_context():
    db = make_db()
    merchant, centre, nord, manager, _seller = seed(db)

    activate_context(db, manager, centre, "MANAGER")

    centre_result = get_commerce_settings(
        merchant=merchant,
        db=db,
    )

    assert centre_result.active_shop_name == "Centre"
    assert centre_result.active_shop_address == "Ancienne adresse Centre"

    activate_context(db, manager, nord, "MANAGER")

    nord_result = get_commerce_settings(
        merchant=merchant,
        db=db,
    )

    assert nord_result.active_shop_name == "Nord"
    assert nord_result.active_shop_address == "Adresse Nord"
    assert nord_result.active_shop_id != centre_result.active_shop_id
