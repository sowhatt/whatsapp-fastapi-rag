import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.online.internal.order_models import OnlineOrder
from app.domains.online.internal.order_service import update_order_status
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
