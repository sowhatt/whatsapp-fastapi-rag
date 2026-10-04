from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.core.public.stock import (
    available_stock,
    consume_reservations,
    release_reservations,
    reserve_stock,
)
from app.models.merchant import Merchant
from app.models.product import Product


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _product(db, stock=10):
    merchant = Merchant(
        whatsapp_number="reservation-test",
        shop_name="Chez Awa",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    product = Product(
        merchant_id=merchant.id,
        name="Riz",
        unit="Sac",
        price=1000,
        purchase_price=800,
        stock=stock,
        initial_stock=stock,
        threshold=0,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return merchant, product


def test_available_stock_subtracts_active_reservations(db):
    merchant, product = _product(db, stock=10)

    reserve_stock(
        merchant_id=merchant.id,
        product_id=product.id,
        quantity=4,
        source_type="online_order",
        source_id=1,
        db=db,
    )
    db.commit()

    assert available_stock(product=product, db=db) == 6


def test_expired_reservation_does_not_reduce_available_stock(db):
    merchant, product = _product(db, stock=10)
    db.add(
        StockReservation(
            merchant_id=merchant.id,
            product_id=product.id,
            quantity=8,
            source_type="online_order",
            source_id=1,
            status="active",
            expires_at=datetime.utcnow() - timedelta(seconds=1),
        )
    )
    db.commit()

    assert available_stock(product=product, db=db) == 10


def test_cannot_reserve_more_than_available(db):
    merchant, product = _product(db, stock=5)

    reserve_stock(
        merchant_id=merchant.id,
        product_id=product.id,
        quantity=4,
        source_type="online_order",
        source_id=1,
        db=db,
    )
    db.flush()

    with pytest.raises(ValueError, match="Stock disponible insuffisant"):
        reserve_stock(
            merchant_id=merchant.id,
            product_id=product.id,
            quantity=2,
            source_type="online_order",
            source_id=2,
            db=db,
        )


def test_release_and_consume_change_reservation_state(db):
    merchant, product = _product(db, stock=10)

    first = reserve_stock(
        merchant_id=merchant.id,
        product_id=product.id,
        quantity=2,
        source_type="online_order",
        source_id=1,
        db=db,
    )
    second = reserve_stock(
        merchant_id=merchant.id,
        product_id=product.id,
        quantity=2,
        source_type="online_order",
        source_id=2,
        db=db,
    )
    db.flush()

    assert release_reservations(
        merchant_id=merchant.id,
        source_type="online_order",
        source_id=1,
        db=db,
    ) == 1
    assert consume_reservations(
        merchant_id=merchant.id,
        source_type="online_order",
        source_id=2,
        db=db,
    ) == 1

    assert first.status == "released"
    assert second.status == "consumed"
