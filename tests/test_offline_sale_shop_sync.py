from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import schema as _schema  # noqa: F401
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.merchant_user import MerchantUser
from app.models.product import Product
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory
from app.models.user_shop_membership import UserShopMembership
from app.routers.sales import sync_offline_sale
from app.schemas.sale import (
    OfflineSaleSyncCreate,
    SaleCreate,
    SaleItemCreate,
)
from app.services.shop_context_service import set_initial_shop_stock


OFFLINE_ID = "22222222-3333-4444-5555-666666666666"


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    merchant = Merchant(
        whatsapp_number="22900000999",
        subscription_status="pilot",
    )
    db.add(merchant)
    db.flush()

    shop_centre = Shop(
        merchant_id=merchant.id,
        name="Centre",
        code="centre",
    )
    shop_nord = Shop(
        merchant_id=merchant.id,
        name="Nord",
        code="nord",
    )
    db.add_all([shop_centre, shop_nord])
    db.flush()

    user = MerchantUser(
        merchant_id=merchant.id,
        full_name="Vendeur Test",
        role="SELLER",
        is_active=True,
    )
    db.add(user)
    db.flush()

    db.add_all(
        [
            UserShopMembership(
                user_id=user.id,
                shop_id=shop_centre.id,
                role="SELLER",
                is_active=True,
            ),
            UserShopMembership(
                user_id=user.id,
                shop_id=shop_nord.id,
                role="SELLER",
                is_active=True,
            ),
        ]
    )

    customer = Customer(
        merchant_id=merchant.id,
        name="Awa",
        phone="2291000",
        debt=0,
    )

    product = Product(
        merchant_id=merchant.id,
        name="Coca",
        unit="bouteille",
        stock=100,
        initial_stock=100,
        threshold=2,
        price=1000,
        purchase_price=700,
    )

    db.add_all([customer, product])
    db.commit()

    set_current_merchant(db, merchant.id)
    db.info["pwa_user_id"] = user.id

    db.info["pwa_shop_id"] = shop_centre.id
    db.info["pwa_role"] = "SELLER"
    set_initial_shop_stock(product, 10, db)
    db.flush()

    db.info["pwa_shop_id"] = shop_nord.id
    db.info["pwa_role"] = "SELLER"
    set_initial_shop_stock(product, 20, db)

    db.commit()

    return (
        merchant,
        user,
        shop_centre,
        shop_nord,
        customer,
        product,
    )


def offline_payload(shop_id, customer, product):
    return OfflineSaleSyncCreate(
        shop_id=shop_id,
        sale=SaleCreate(
            customer_id=customer.id,
            items=[
                SaleItemCreate(
                    product_id=product.id,
                    quantity=2,
                )
            ],
            paid_amount=2000,
            payment_channel="cash",
            offline_sale_id=OFFLINE_ID,
        ),
    )


def inventory_stock(db, shop_id, product_id):
    db.expire_all()

    row = (
        db.query(ShopInventory)
        .filter(
            ShopInventory.shop_id == shop_id,
            ShopInventory.product_id == product_id,
        )
        .one()
    )

    return row.stock


def test_offline_sync_writes_to_original_shop():
    db = make_db()

    (
        merchant,
        _user,
        shop_centre,
        shop_nord,
        customer,
        product,
    ) = seed(db)

    # Au moment de la reconnexion, l'utilisateur est sur Nord.
    db.info["pwa_shop_id"] = shop_nord.id
    db.info["pwa_role"] = "SELLER"

    sale = sync_offline_sale(
        offline_payload(
            shop_centre.id,
            customer,
            product,
        ),
        merchant,
        db,
    )

    assert sale.offline_sale_id == OFFLINE_ID

    # La vente appartient historiquement à Centre.
    assert inventory_stock(
        db,
        shop_centre.id,
        product.id,
    ) == 8

    # Nord ne doit pas être modifiée.
    assert inventory_stock(
        db,
        shop_nord.id,
        product.id,
    ) == 20


def test_offline_sync_restores_current_shop_context():
    db = make_db()

    (
        merchant,
        _user,
        shop_centre,
        shop_nord,
        customer,
        product,
    ) = seed(db)

    db.info["pwa_shop_id"] = shop_nord.id
    db.info["pwa_role"] = "SELLER"

    sync_offline_sale(
        offline_payload(
            shop_centre.id,
            customer,
            product,
        ),
        merchant,
        db,
    )

    assert db.info["pwa_shop_id"] == shop_nord.id
    assert db.info["pwa_role"] == "SELLER"


def test_offline_sync_rejects_unauthorized_original_shop():
    db = make_db()

    (
        merchant,
        user,
        shop_centre,
        shop_nord,
        customer,
        product,
    ) = seed(db)

    membership = (
        db.query(UserShopMembership)
        .filter(
            UserShopMembership.user_id == user.id,
            UserShopMembership.shop_id == shop_centre.id,
        )
        .one()
    )

    membership.is_active = False
    db.commit()

    db.info["pwa_shop_id"] = shop_nord.id
    db.info["pwa_role"] = "SELLER"

    try:
        sync_offline_sale(
            offline_payload(
                shop_centre.id,
                customer,
                product,
            ),
            merchant,
            db,
        )
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "Boutique non autorisée"
    else:
        raise AssertionError(
            "Une boutique non autorisée doit être refusée"
        )


def test_offline_sync_rejects_role_without_sale_create():
    db = make_db()

    (
        merchant,
        user,
        shop_centre,
        shop_nord,
        customer,
        product,
    ) = seed(db)

    membership = (
        db.query(UserShopMembership)
        .filter(
            UserShopMembership.user_id == user.id,
            UserShopMembership.shop_id == shop_centre.id,
        )
        .one()
    )

    membership.role = "STOCK_MANAGER"
    db.commit()

    db.info["pwa_shop_id"] = shop_nord.id
    db.info["pwa_role"] = "SELLER"

    try:
        sync_offline_sale(
            offline_payload(
                shop_centre.id,
                customer,
                product,
            ),
            merchant,
            db,
        )
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "Permission requise : sale.create"
    else:
        raise AssertionError(
            "Un rôle sans sale.create doit être refusé"
        )


def test_offline_sync_replay_is_idempotent():
    db = make_db()

    (
        merchant,
        _user,
        shop_centre,
        shop_nord,
        customer,
        product,
    ) = seed(db)

    db.info["pwa_shop_id"] = shop_nord.id
    db.info["pwa_role"] = "SELLER"

    request = offline_payload(
        shop_centre.id,
        customer,
        product,
    )

    first = sync_offline_sale(
        request,
        merchant,
        db,
    )

    second = sync_offline_sale(
        request,
        merchant,
        db,
    )

    assert first.id == second.id

    assert inventory_stock(
        db,
        shop_centre.id,
        product.id,
    ) == 8

    assert inventory_stock(
        db,
        shop_nord.id,
        product.id,
    ) == 20
