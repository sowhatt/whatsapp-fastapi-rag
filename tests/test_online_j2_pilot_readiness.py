from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.online.internal.catalog_service import publish_product
from app.domains.online.internal.pilot_readiness import pilot_readiness
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public.cart import create_cart, set_cart_item
from app.domains.online.public.checkout import checkout_cart
from app.models.merchant import Merchant
from app.models.product import Product
from app.shared.outbox.model import OutboxEvent


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _setup_order(db, payment_method="cash_on_delivery"):
    merchant = Merchant(
        whatsapp_number=f"pilot-ready-{payment_method}",
        shop_name="Pilot Shop",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    store = get_or_create_store(merchant_id=merchant.id, db=db)
    product = Product(
        merchant_id=merchant.id,
        name="Produit pilote",
        unit="Pièce",
        price=2000,
        purchase_price=1500,
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
    order = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Client pilote",
        customer_phone="+229700",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        payment_method=payment_method,
        db=db,
    )
    return merchant, order


def test_readiness_warnings_do_not_block_go(db):
    merchant, _ = _setup_order(db, payment_method="mobile_money")

    result = pilot_readiness(merchant_id=merchant.id, db=db)

    assert result["ready"] is True
    assert result["warnings"]["pending_mobile_money"] == 1
    assert result["warnings"]["pending_outbox"] >= 1


def test_expired_reservation_blocks_readiness(db):
    merchant, order = _setup_order(db)
    reservation = (
        db.query(StockReservation)
        .filter(StockReservation.source_id == order["id"])
        .one()
    )
    reservation.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    result = pilot_readiness(merchant_id=merchant.id, db=db)

    assert result["ready"] is False
    assert result["blockers"]["expired_reservations"] == 1


def test_failed_outbox_blocks_readiness(db):
    merchant, _ = _setup_order(db)
    event = (
        db.query(OutboxEvent)
        .filter(OutboxEvent.merchant_id == merchant.id)
        .first()
    )
    event.status = "failed"
    db.commit()

    result = pilot_readiness(merchant_id=merchant.id, db=db)

    assert result["ready"] is False
    assert result["blockers"]["failed_outbox"] == 1
