from datetime import datetime, timedelta

import pytest

from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.core.internal.transaction_model import BusinessTransaction
from app.domains.online.internal.catalog_service import publish_product
from app.domains.online.internal.order_models import OnlineOrder, OnlineOrderItem
from app.domains.online.internal.order_service import revalidate_order_reservations
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public.cart import create_cart, set_cart_item
from app.domains.online.public.checkout import checkout_cart
from app.models.merchant import Merchant
from app.models.product import Product
from app.shared.outbox.model import OutboxEvent
from tests.test_online_j42_core_consistency import advance, db  # noqa: F401


def multi_order(db, suffix="a", stocks=(10, 10)):
    """Real two-product publication/cart/checkout, also used by PostgreSQL tests."""
    merchant = Merchant(whatsapp_number=f"j42-{suffix}", shop_name=f"J42 {suffix}")
    db.add(merchant)
    db.commit()
    store = get_or_create_store(merchant_id=merchant.id, db=db)
    products = [
        Product(merchant_id=merchant.id, name=f"Article {i}", unit="Pièce",
                price=1000, purchase_price=500, stock=stocks[i], initial_stock=stocks[i], threshold=0)
        for i in range(2)
    ]
    db.add_all(products)
    db.commit()
    for product in products:
        publish_product(merchant_id=merchant.id, product_id=product.id, db=db)
    cart = create_cart(slug=store.slug, db=db)
    for product, quantity in zip(products, (2, 3)):
        set_cart_item(slug=store.slug, token=cart["token"], product_id=product.id,
                      quantity=quantity, db=db)
    result = checkout_cart(
        slug=store.slug, token=cart["token"], customer_name="Client test",
        customer_phone="+22997000000", delivery_mode="pickup",
        delivery_address=None, notes=None, db=db,
    )
    return merchant.id, result["id"]


@pytest.mark.parametrize("target", ["confirmed", "completed"])
@pytest.mark.parametrize("defect", [
    "missing", "expired", "short", "extra", "wrong_product", "consumed",
    "released", "zero", "duplicate",
])
def test_incomplete_multi_article_set_cannot_confirm_or_complete(db, target, defect):
    merchant_id, order_id = multi_order(db)
    if target == "completed":
        for stage in ("confirmed", "preparing", "ready"):
            advance(db, merchant_id, order_id, stage)
    rows = db.query(StockReservation).order_by(StockReservation.id).all()
    row = rows[1]
    if defect == "missing":
        db.delete(row)
    elif defect == "expired":
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    elif defect == "short":
        row.quantity -= 1
    elif defect == "extra":
        row.quantity += 1
    elif defect == "wrong_product":
        row.product_id = rows[0].product_id
    elif defect in {"consumed", "released"}:
        row.status = defect
    elif defect == "zero":
        row.quantity = 0
    else:
        db.add(StockReservation(
            merchant_id=merchant_id, product_id=row.product_id, quantity=row.quantity,
            source_type="online_order", source_id=order_id, status="active",
            expires_at=row.expires_at,
        ))
    db.commit()
    before = db.query(OutboxEvent).count()
    with pytest.raises(ValueError, match="réservation"):
        advance(db, merchant_id, order_id, target)
    db.commit()  # a caller cannot accidentally persist a partially applied command
    assert db.query(OnlineOrder).one().status == ("pending" if target == "confirmed" else "ready")
    assert db.query(BusinessTransaction).one().status == ("pending" if target == "confirmed" else "confirmed")
    assert db.query(OutboxEvent).count() == before


def test_complete_consumes_all_quantities_replay_accepts_consumed_not_expiration(db):
    merchant_id, order_id = multi_order(db)
    for stage in ("confirmed", "preparing", "ready", "completed"):
        advance(db, merchant_id, order_id, stage)
    for row in db.query(StockReservation).all():
        assert row.status == "consumed"
        row.expires_at = datetime.utcnow() - timedelta(days=1)
    db.commit()
    advance(db, merchant_id, order_id, "completed")
    assert sum(r.quantity for r in db.query(StockReservation).all()) == 5
    assert db.query(OutboxEvent).filter_by(event_type="commerce.order.completed").count() == 1


def test_completed_replay_rejects_missing_consumed_line(db):
    merchant_id, order_id = multi_order(db)
    for stage in ("confirmed", "preparing", "ready", "completed"):
        advance(db, merchant_id, order_id, stage)
    db.delete(db.query(StockReservation).first())
    db.commit()
    with pytest.raises(ValueError, match="réservation"):
        advance(db, merchant_id, order_id, "completed")


def test_revalidation_checks_quantities_even_with_correct_row_count(db):
    merchant_id, order_id = multi_order(db)
    db.query(StockReservation).first().quantity = 1
    db.commit()
    revalidate_order_reservations(db=db, merchant_id=merchant_id, order_id=order_id)
    active = {r.product_id: r.quantity for r in db.query(StockReservation).filter_by(status="active")}
    expected = {r.product_id: r.quantity for r in db.query(OnlineOrderItem)}
    assert active == expected
    advance(db, merchant_id, order_id, "confirmed")


def test_revalidation_never_rebuilds_over_consumed_stock(db):
    merchant_id, order_id = multi_order(db)
    db.query(StockReservation).first().status = "consumed"
    db.commit()
    with pytest.raises(ValueError, match="déjà consommé"):
        revalidate_order_reservations(db=db, merchant_id=merchant_id, order_id=order_id)
    assert db.query(StockReservation).count() == 2
