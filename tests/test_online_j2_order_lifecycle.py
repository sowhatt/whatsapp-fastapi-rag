import pytest
from sqlalchemy import create_engine
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.core.public.stock import available_stock
from app.domains.online.internal.order_models import OnlineOrder
from app.domains.online.internal.order_service import cleanup_expired_order_reservations, get_order, revalidate_order_reservations, update_order_status
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public.cart import create_cart, set_cart_item
from app.domains.online.public.checkout import checkout_cart
from app.models.merchant import Merchant
from app.models.product import Product
from app.shared.outbox.model import OutboxEvent
from app.domains.online.internal.catalog_service import publish_product


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _order(db):
    merchant = Merchant(whatsapp_number="j2-order", shop_name="Chez Awa")
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
    publish_product(merchant_id=merchant.id, product_id=product.id, db=db)
    cart = create_cart(slug=store.slug, db=db)
    set_cart_item(slug=store.slug, token=cart["token"], product_id=product.id, quantity=2, db=db)
    result = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Client",
        customer_phone="+2290002",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        db=db,
    )
    return merchant, db.query(OnlineOrder).filter(OnlineOrder.id == result["id"]).one()


def test_confirm_then_prepare_then_ready_then_complete(db):
    merchant, order = _order(db)

    assert update_order_status(merchant_id=merchant.id, order_id=order.id, status="confirmed", db=db)["status"] == "confirmed"
    assert update_order_status(merchant_id=merchant.id, order_id=order.id, status="preparing", db=db)["status"] == "preparing"
    assert update_order_status(merchant_id=merchant.id, order_id=order.id, status="ready", db=db)["status"] == "ready"
    assert update_order_status(merchant_id=merchant.id, order_id=order.id, status="completed", db=db)["status"] == "completed"


def test_cancel_releases_online_reservation(db):
    merchant, order = _order(db)
    reservation = db.query(StockReservation).one()
    assert reservation.status == "active"

    result = update_order_status(
        merchant_id=merchant.id,
        order_id=order.id,
        status="cancelled",
        db=db,
    )

    db.refresh(reservation)
    assert result["status"] == "cancelled"
    assert reservation.status == "released"


def test_invalid_order_transition_is_rejected(db):
    merchant, order = _order(db)
    with pytest.raises(ValueError, match="Transition de commande invalide"):
        update_order_status(
            merchant_id=merchant.id,
            order_id=order.id,
            status="completed",
            db=db,
        )



def test_expired_reservation_blocks_confirmation_and_is_visible(db):
    merchant, order = _order(db)
    reservation = db.query(StockReservation).one()
    reservation.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    payload = get_order(
        merchant_id=merchant.id,
        order_id=order.id,
        db=db,
    )
    assert payload["reservation_status"] == "expired"

    with pytest.raises(ValueError, match="réservation de stock a expiré"):
        update_order_status(
            merchant_id=merchant.id,
            order_id=order.id,
            status="confirmed",
            db=db,
        )


def test_cleanup_marks_expired_reservations(db):
    merchant, _ = _order(db)
    reservation = db.query(StockReservation).one()
    reservation.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    cleaned = cleanup_expired_order_reservations(
        merchant_id=merchant.id,
        db=db,
    )

    db.refresh(reservation)
    assert cleaned == 1
    assert reservation.status == "expired"



def test_expired_reservation_can_be_revalidated_then_confirmed(db):
    merchant, order = _order(db)
    reservation = db.query(StockReservation).one()
    reservation.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    refreshed = revalidate_order_reservations(
        merchant_id=merchant.id,
        order_id=order.id,
        db=db,
    )

    assert refreshed["reservation_status"] == "active"

    confirmed = update_order_status(
        merchant_id=merchant.id,
        order_id=order.id,
        status="confirmed",
        db=db,
    )
    assert confirmed["status"] == "confirmed"


def test_revalidation_rolls_back_when_stock_is_insufficient(db):
    merchant, order = _order(db)
    reservation = db.query(StockReservation).one()
    reservation.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    item = db.query(OnlineOrder).filter(OnlineOrder.id == order.id).one()
    product_id = (
        db.query(StockReservation.product_id)
        .filter(StockReservation.source_id == item.id)
        .scalar()
    )
    product = db.query(Product).filter(Product.id == product_id).one()
    product.stock = 0
    db.commit()

    with pytest.raises(ValueError, match="Stock disponible insuffisant"):
        revalidate_order_reservations(
            merchant_id=merchant.id,
            order_id=order.id,
            db=db,
        )

    active = (
        db.query(StockReservation)
        .filter(
            StockReservation.source_id == order.id,
            StockReservation.status == "active",
        )
        .count()
    )
    assert active == 0



def test_confirm_extends_reservation_and_emits_delivery_request(db):
    merchant = Merchant(whatsapp_number="j2-delivery", shop_name="Chez Livraison")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    store = get_or_create_store(merchant_id=merchant.id, db=db)

    product = Product(
        merchant_id=merchant.id,
        name="Colis",
        unit="Pièce",
        price=5000,
        purchase_price=4000,
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
    result = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Client Livraison",
        customer_phone="+229600",
        delivery_mode="delivery",
        delivery_address="Cotonou centre",
        notes=None,
        db=db,
    )

    reservation = db.query(StockReservation).one()
    old_expiry = reservation.expires_at

    update_order_status(
        merchant_id=merchant.id,
        order_id=result["id"],
        status="confirmed",
        db=db,
    )

    db.refresh(reservation)
    assert reservation.expires_at > old_expiry

    events = {
        event.event_type
        for event in db.query(OutboxEvent).all()
    }
    assert "commerce.order.confirmed" in events
    assert "delivery.requested" in events


def test_completed_consumes_reservation_and_emits_completed_event(db):
    merchant, order = _order(db)

    for status in ("confirmed", "preparing", "ready", "completed"):
        payload = update_order_status(
            merchant_id=merchant.id,
            order_id=order.id,
            status=status,
            db=db,
        )

    reservation = db.query(StockReservation).one()
    assert payload["status"] == "completed"
    assert payload["reservation_status"] == "consumed"
    assert reservation.status == "consumed"

    events = {
        event.event_type
        for event in db.query(OutboxEvent).all()
    }
    assert "commerce.order.completed" in events


def test_expired_reservation_blocks_completion(db):
    merchant, order = _order(db)
    update_order_status(
        merchant_id=merchant.id,
        order_id=order.id,
        status="confirmed",
        db=db,
    )
    update_order_status(
        merchant_id=merchant.id,
        order_id=order.id,
        status="preparing",
        db=db,
    )
    update_order_status(
        merchant_id=merchant.id,
        order_id=order.id,
        status="ready",
        db=db,
    )

    reservation = db.query(StockReservation).one()
    reservation.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    with pytest.raises(ValueError, match="Revalidez avant de terminer"):
        update_order_status(
            merchant_id=merchant.id,
            order_id=order.id,
            status="completed",
            db=db,
        )

    db.refresh(order)
    assert order.status == "ready"



def test_ready_order_can_revalidate_then_complete(db):
    merchant, order = _order(db)

    for status in ("confirmed", "preparing", "ready"):
        update_order_status(
            merchant_id=merchant.id,
            order_id=order.id,
            status=status,
            db=db,
        )

    reservation = db.query(StockReservation).one()
    reservation.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    refreshed = revalidate_order_reservations(
        merchant_id=merchant.id,
        order_id=order.id,
        db=db,
    )
    assert refreshed["status"] == "ready"
    assert refreshed["reservation_status"] == "active"

    completed = update_order_status(
        merchant_id=merchant.id,
        order_id=order.id,
        status="completed",
        db=db,
    )
    assert completed["status"] == "completed"
    assert completed["reservation_status"] == "consumed"



def test_completed_order_stays_unavailable_to_online_without_mutating_shop_stock(db):
    merchant, order = _order(db)
    reservation = db.query(StockReservation).one()
    product = db.query(Product).filter(Product.id == reservation.product_id).one()

    assert product.stock == 10
    assert available_stock(product=product, db=db) == 8

    for status in ("confirmed", "preparing", "ready", "completed"):
        update_order_status(
            merchant_id=merchant.id,
            order_id=order.id,
            status=status,
            db=db,
        )

    db.refresh(product)
    db.refresh(reservation)

    assert product.stock == 10
    assert reservation.status == "consumed"
    assert available_stock(product=product, db=db) == 8


def test_cancelled_order_releases_quantity_back_to_online(db):
    merchant, order = _order(db)
    reservation = db.query(StockReservation).one()
    product = db.query(Product).filter(Product.id == reservation.product_id).one()

    assert available_stock(product=product, db=db) == 8

    update_order_status(
        merchant_id=merchant.id,
        order_id=order.id,
        status="cancelled",
        db=db,
    )

    db.refresh(product)
    db.refresh(reservation)

    assert product.stock == 10
    assert reservation.status == "released"
    assert available_stock(product=product, db=db) == 10
