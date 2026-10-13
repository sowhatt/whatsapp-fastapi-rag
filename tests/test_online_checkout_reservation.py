from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.core.public.stock import available_stock
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public.cart import create_cart, set_cart_item
from app.domains.online.public.checkout import checkout_cart
from app.models.merchant import Merchant
from app.models.product import Product
from app.domains.online.internal.catalog_service import publish_product


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_checkout_reserves_stock_without_decrementing_physical_stock(db):
    merchant = Merchant(
        whatsapp_number="checkout-reservation-test",
        shop_name="Chez Awa",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    store = get_or_create_store(merchant_id=merchant.id, db=db)

    product = Product(
        merchant_id=merchant.id,
        name="Huile",
        unit="Bidon",
        price=5000,
        purchase_price=4000,
        stock=10,
        initial_stock=10,
        threshold=0,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
    )
    cart = create_cart(slug=store.slug, db=db)
    set_cart_item(
        slug=store.slug,
        token=cart["token"],
        product_id=product.id,
        quantity=4,
        db=db,
    )

    result = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Jean Client",
        customer_phone="+2290100000002",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        db=db,
    )

    db.refresh(product)
    reservation = db.query(StockReservation).one()

    assert result["stock_reserved"] is True
    assert product.stock == 10
    assert reservation.quantity == 4
    assert reservation.status == "active"
    assert available_stock(product=product, db=db) == 6



def test_unpaid_order_reservation_uses_pilot_ttl(db, monkeypatch):
    monkeypatch.setenv("ONLINE_ORDER_RESERVATION_MINUTES", "240")

    merchant = Merchant(
        whatsapp_number="checkout-reservation-ttl",
        shop_name="Chez TTL",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    store = get_or_create_store(merchant_id=merchant.id, db=db)

    product = Product(
        merchant_id=merchant.id,
        name="Farine",
        unit="Sac",
        price=6000,
        purchase_price=5000,
        stock=10,
        initial_stock=10,
        threshold=0,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    publish_product(merchant_id=merchant.id, product_id=product.id, db=db)

    cart = create_cart(slug=store.slug, db=db)
    set_cart_item(
        slug=store.slug,
        token=cart["token"],
        product_id=product.id,
        quantity=1,
        db=db,
    )

    before = datetime.utcnow()
    result = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Client TTL",
        customer_phone="+2290100000003",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        db=db,
    )
    reservation = db.query(StockReservation).one()

    assert result["reservation_minutes"] == 240
    assert reservation.expires_at >= before + timedelta(minutes=239)
