from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import schema as _schema  # noqa: F401
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.merchant import Merchant
from app.models.payment import Payment
from app.models.product import Product
from app.models.sale import Sale
from app.models.shop import Shop
from app.models.shop_inventory import ShopInventory
from app.models.stock_movement import StockMovement
from app.routers.sales import create_sale
from app.schemas.sale import SaleCreate, SaleItemCreate
from app.services.shop_context_service import (
    set_initial_shop_stock,
)


OFFLINE_ID = "11111111-2222-3333-4444-555555555555"


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed_merchant(db, suffix: str):
    merchant = Merchant(
        whatsapp_number=f"2290000{suffix}",
        subscription_status="pilot",
    )
    db.add(merchant)
    db.flush()

    shop = Shop(
        merchant_id=merchant.id,
        name=f"Boutique {suffix}",
        code=f"shop-{suffix}",
    )
    db.add(shop)
    db.flush()

    customer = Customer(
        merchant_id=merchant.id,
        name=f"Client {suffix}",
        phone=f"2291{suffix}",
        debt=0,
    )

    product = Product(
        merchant_id=merchant.id,
        name=f"Riz {suffix}",
        unit="sac",
        stock=50,
        initial_stock=50,
        threshold=2,
        price=10000,
        purchase_price=8000,
    )

    db.add_all([customer, product])
    db.commit()

    set_current_merchant(db, merchant.id)
    db.info["pwa_shop_id"] = shop.id

    set_initial_shop_stock(
        product,
        10,
        db,
    )
    db.commit()

    return merchant, shop, customer, product


def payload(
    customer,
    product,
    *,
    quantity=2,
    offline_sale_id=OFFLINE_ID,
):
    return SaleCreate(
        customer_id=customer.id,
        items=[
            SaleItemCreate(
                product_id=product.id,
                quantity=quantity,
            )
        ],
        paid_amount=10000 * quantity,
        payment_channel="cash",
        offline_sale_id=offline_sale_id,
    )


def test_offline_replay_returns_same_sale():
    db = make_db()
    _, _, customer, product = seed_merchant(db, "901")

    request = payload(customer, product)

    first = create_sale(request, db)
    second = create_sale(request, db)

    assert second.id == first.id
    assert second.sale_number == first.sale_number

    assert (
        db.query(Sale)
        .filter(Sale.offline_sale_id == OFFLINE_ID)
        .count()
        == 1
    )


def test_offline_replay_decrements_stock_once():
    db = make_db()
    _, shop, customer, product = seed_merchant(db, "902")

    request = payload(customer, product)

    create_sale(request, db)
    create_sale(request, db)

    db.expire_all()

    inventory = (
        db.query(ShopInventory)
        .filter(
            ShopInventory.shop_id == shop.id,
            ShopInventory.product_id == product.id,
        )
        .one()
    )

    assert inventory.stock == 8


def test_offline_replay_creates_payment_once():
    db = make_db()
    _, _, customer, product = seed_merchant(db, "903")

    request = payload(customer, product)

    first = create_sale(request, db)
    create_sale(request, db)

    assert (
        db.query(Payment)
        .filter(Payment.sale_id == first.id)
        .count()
        == 1
    )


def test_offline_replay_creates_stock_movement_once():
    db = make_db()
    _, _, customer, product = seed_merchant(db, "904")

    request = payload(customer, product)

    create_sale(request, db)

    count_after_first = (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id == product.id,
            StockMovement.movement_type == "sale_out",
        )
        .count()
    )

    create_sale(request, db)

    count_after_replay = (
        db.query(StockMovement)
        .filter(
            StockMovement.product_id == product.id,
            StockMovement.movement_type == "sale_out",
        )
        .count()
    )

    assert count_after_first == 1
    assert count_after_replay == 1


def test_same_offline_id_is_isolated_by_merchant():
    db = make_db()

    merchant_a, _, customer_a, product_a = seed_merchant(
        db,
        "905",
    )

    sale_a = create_sale(
        payload(customer_a, product_a),
        db,
    )

    merchant_b, _, customer_b, product_b = seed_merchant(
        db,
        "906",
    )

    sale_b = create_sale(
        payload(customer_b, product_b),
        db,
    )

    assert merchant_a.id != merchant_b.id
    assert sale_a.id != sale_b.id

    # Le filtre tenant est actif sur les requêtes Sale :
    # chaque commerçant ne doit voir que sa propre vente,
    # même lorsque la même clé offline est réutilisée.
    set_current_merchant(db, merchant_a.id)

    visible_a = (
        db.query(Sale)
        .filter(Sale.offline_sale_id == OFFLINE_ID)
        .all()
    )

    assert [sale.id for sale in visible_a] == [sale_a.id]

    set_current_merchant(db, merchant_b.id)

    visible_b = (
        db.query(Sale)
        .filter(Sale.offline_sale_id == OFFLINE_ID)
        .all()
    )

    assert [sale.id for sale in visible_b] == [sale_b.id]


def test_same_offline_id_with_different_payload_is_conflict():
    db = make_db()
    _, _, customer, product = seed_merchant(db, "907")

    create_sale(
        payload(
            customer,
            product,
            quantity=1,
        ),
        db,
    )

    try:
        create_sale(
            payload(
                customer,
                product,
                quantity=2,
            ),
            db,
        )
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "Conflit d'idempotence" in exc.detail
    else:
        raise AssertionError(
            "La même clé offline avec un contenu différent "
            "doit être refusée"
        )
