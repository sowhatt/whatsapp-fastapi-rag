import os

import jwt
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
from app.models.user_phone import UserPhone
from app.models.user_shop_membership import UserShopMembership
from app.routers.auth import SelectShopPayload, list_accessible_shops, select_shop


JWT_SECRET = "test-secret-for-pwa-shop-selection-1234567890"


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    merchant = Merchant(
        whatsapp_number="22900000021",
        shop_name="Groupe Test",
        subscription_status="pilot",
    )
    other_merchant = Merchant(
        whatsapp_number="22900000022",
        shop_name="Autre Groupe",
        subscription_status="pilot",
    )
    db.add_all([merchant, other_merchant])
    db.flush()

    centre = Shop(merchant_id=merchant.id, name="Centre", code="centre")
    nord = Shop(merchant_id=merchant.id, name="Nord", code="nord")
    forbidden = Shop(merchant_id=other_merchant.id, name="Autre", code="autre")
    db.add_all([centre, nord, forbidden])
    db.flush()

    user = MerchantUser(
        merchant_id=merchant.id,
        full_name="Awa Test",
        role="SELLER",
        password_hash=hash_password("motdepasse123"),
        is_active=True,
    )
    db.add(user)
    db.flush()

    db.add(
        UserPhone(
            merchant_id=merchant.id,
            user_id=user.id,
            shop_id=centre.id,
            phone_number="33600000021",
            is_primary=True,
            is_active=True,
        )
    )
    db.add(
        UserShopMembership(
            user_id=user.id,
            shop_id=nord.id,
            role="MANAGER",
            is_active=True,
        )
    )
    db.commit()
    return merchant, user, centre, nord, forbidden


def _activate_user_context(db, user):
    db.info["pwa_user_id"] = user.id
    db.info["pwa_role"] = user.role


def test_accessible_shops_include_direct_phone_and_membership_roles():
    db = make_db()
    merchant, user, centre, nord, _forbidden = seed(db)
    _activate_user_context(db, user)

    shops = list_accessible_shops(merchant=merchant, db=db)

    assert [(shop.id, shop.role) for shop in shops] == [
        (centre.id, "SELLER"),
        (nord.id, "MANAGER"),
    ]


def test_select_shop_mints_token_with_selected_shop_and_effective_role(monkeypatch):
    monkeypatch.setenv("PWA_JWT_SECRET", JWT_SECRET)
    db = make_db()
    merchant, user, _centre, nord, _forbidden = seed(db)
    _activate_user_context(db, user)

    response = select_shop(
        SelectShopPayload(shop_id=nord.id),
        merchant=merchant,
        db=db,
    )

    payload = jwt.decode(response.access_token, JWT_SECRET, algorithms=["HS256"])
    assert payload["merchant_id"] == merchant.id
    assert payload["user_id"] == user.id
    assert payload["shop_id"] == nord.id
    assert payload["role"] == "MANAGER"
    assert response.merchant.active_shop_name == "Nord"
    assert response.merchant.role == "MANAGER"


def test_select_shop_rejects_shop_from_another_merchant(monkeypatch):
    monkeypatch.setenv("PWA_JWT_SECRET", JWT_SECRET)
    db = make_db()
    merchant, user, _centre, _nord, forbidden = seed(db)
    _activate_user_context(db, user)

    with pytest.raises(HTTPException) as exc:
        select_shop(
            SelectShopPayload(shop_id=forbidden.id),
            merchant=merchant,
            db=db,
        )

    assert exc.value.status_code == 403


def test_inactive_membership_cannot_be_selected(monkeypatch):
    monkeypatch.setenv("PWA_JWT_SECRET", JWT_SECRET)
    db = make_db()
    merchant, user, _centre, nord, _forbidden = seed(db)
    _activate_user_context(db, user)

    membership = (
        db.query(UserShopMembership)
        .filter(
            UserShopMembership.user_id == user.id,
            UserShopMembership.shop_id == nord.id,
        )
        .one()
    )
    membership.is_active = False
    db.commit()

    with pytest.raises(HTTPException) as exc:
        select_shop(
            SelectShopPayload(shop_id=nord.id),
            merchant=merchant,
            db=db,
        )

    assert exc.value.status_code == 403
