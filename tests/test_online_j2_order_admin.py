from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal.stock_reservation_model import StockReservation
from app.domains.online.internal.order_service import get_order, list_orders, order_summary, update_order_status
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public.cart import create_cart, set_cart_item
from app.domains.online.public.checkout import checkout_cart
from app.domains.online.internal.catalog_service import publish_product
from app.models.merchant import Merchant
from app.models.product import Product


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_order(db, *, suffix: str, customer_name: str, customer_phone: str):
    merchant = Merchant(
        whatsapp_number=f"order-admin-{suffix}",
        shop_name=f"Shop {suffix}",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    store = get_or_create_store(merchant_id=merchant.id, db=db)

    product = Product(
        merchant_id=merchant.id,
        name=f"Produit {suffix}",
        unit="Pièce",
        price=1000,
        purchase_price=800,
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
        customer_name=customer_name,
        customer_phone=customer_phone,
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        db=db,
    )
    return merchant, result


def test_order_listing_is_tenant_scoped(db):
    merchant_a, order_a = _make_order(
        db,
        suffix="a",
        customer_name="Alice",
        customer_phone="+229111",
    )
    merchant_b, order_b = _make_order(
        db,
        suffix="b",
        customer_name="Bob",
        customer_phone="+229222",
    )

    orders_a = list_orders(merchant_id=merchant_a.id, db=db)

    assert [row["id"] for row in orders_a] == [order_a["id"]]
    assert order_b["id"] not in [row["id"] for row in orders_a]
    assert get_order(
        merchant_id=merchant_a.id,
        order_id=order_b["id"],
        db=db,
    ) is None


def test_order_search_matches_reference_name_and_phone(db):
    merchant, order = _make_order(
        db,
        suffix="search",
        customer_name="Jean Dupont",
        customer_phone="+22997000000",
    )

    by_name = list_orders(merchant_id=merchant.id, db=db, query="Jean")
    by_phone = list_orders(merchant_id=merchant.id, db=db, query="9700")
    by_ref = list_orders(
        merchant_id=merchant.id,
        db=db,
        query=order["reference"][-5:],
    )

    assert [row["id"] for row in by_name] == [order["id"]]
    assert [row["id"] for row in by_phone] == [order["id"]]
    assert [row["id"] for row in by_ref] == [order["id"]]



def test_order_summary_counts_statuses_and_amounts(db):
    merchant, first = _make_order(
        db,
        suffix="summary-a",
        customer_name="Alice",
        customer_phone="+229333",
    )

    # Same merchant, second order.
    store = get_or_create_store(merchant_id=merchant.id, db=db)
    product = db.query(Product).filter(Product.merchant_id == merchant.id).first()
    cart = create_cart(slug=store.slug, db=db)
    set_cart_item(
        slug=store.slug,
        token=cart["token"],
        product_id=product.id,
        quantity=2,
        db=db,
    )
    second = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Alice 2",
        customer_phone="+229334",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        db=db,
    )
    update_order_status(
        merchant_id=merchant.id,
        order_id=second["id"],
        status="cancelled",
        db=db,
    )

    summary = order_summary(merchant_id=merchant.id, db=db)

    assert summary["orders_total"] == 2
    assert summary["by_status"]["pending"] == 1
    assert summary["by_status"]["cancelled"] == 1
    assert summary["gross_order_amount"] == first["total"]



def test_order_payload_exposes_correct_actions_for_pending_and_expired(db):
    merchant, order = _make_order(
        db,
        suffix="actions-pending",
        customer_name="Action Client",
        customer_phone="+229444",
    )

    pending = get_order(
        merchant_id=merchant.id,
        order_id=order["id"],
        db=db,
    )
    assert pending["actions"]["can_confirm"] is True
    assert pending["actions"]["can_cancel"] is True
    assert pending["actions"]["recommended_action"] == "confirm"

    reservation = (
        db.query(StockReservation)
        .filter(
            StockReservation.source_type == "online_order",
            StockReservation.source_id == order["id"],
        )
        .one()
    )
    reservation.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    expired = get_order(
        merchant_id=merchant.id,
        order_id=order["id"],
        db=db,
    )
    assert expired["actions"]["can_confirm"] is False
    assert expired["actions"]["can_revalidate_stock"] is True
    assert expired["actions"]["needs_revalidation"] is True
    assert expired["actions"]["recommended_action"] == "revalidate_stock"


def test_order_actions_follow_lifecycle(db):
    merchant, order = _make_order(
        db,
        suffix="actions-flow",
        customer_name="Flow Client",
        customer_phone="+229445",
    )

    confirmed = update_order_status(
        merchant_id=merchant.id,
        order_id=order["id"],
        status="confirmed",
        db=db,
    )
    assert confirmed["actions"]["can_prepare"] is True
    assert confirmed["actions"]["next_status"] == "preparing"

    preparing = update_order_status(
        merchant_id=merchant.id,
        order_id=order["id"],
        status="preparing",
        db=db,
    )
    assert preparing["actions"]["can_mark_ready"] is True
    assert preparing["actions"]["next_status"] == "ready"

    ready = update_order_status(
        merchant_id=merchant.id,
        order_id=order["id"],
        status="ready",
        db=db,
    )
    assert ready["actions"]["can_complete"] is True
    assert ready["actions"]["next_status"] == "completed"

    completed = update_order_status(
        merchant_id=merchant.id,
        order_id=order["id"],
        status="completed",
        db=db,
    )
    assert completed["actions"]["recommended_action"] is None
    assert completed["actions"]["can_cancel"] is False


def test_order_summary_exposes_attention_counts(db):
    merchant, first = _make_order(
        db,
        suffix="attention-a",
        customer_name="Attention A",
        customer_phone="+229446",
    )

    store = get_or_create_store(merchant_id=merchant.id, db=db)
    product = db.query(Product).filter(Product.merchant_id == merchant.id).first()
    cart = create_cart(slug=store.slug, db=db)
    set_cart_item(
        slug=store.slug,
        token=cart["token"],
        product_id=product.id,
        quantity=1,
        db=db,
    )
    second = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Attention B",
        customer_phone="+229447",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        db=db,
    )

    reservation = (
        db.query(StockReservation)
        .filter(
            StockReservation.source_type == "online_order",
            StockReservation.source_id == second["id"],
        )
        .one()
    )
    reservation.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    summary = order_summary(merchant_id=merchant.id, db=db)

    assert summary["attention"]["can_confirm"] == 1
    assert summary["attention"]["needs_revalidation"] == 1
    assert summary["attention"]["total"] == 2



def test_order_priority_places_revalidation_before_confirmation(db):
    merchant, first = _make_order(
        db,
        suffix="priority-a",
        customer_name="Priority A",
        customer_phone="+229448",
    )

    store = get_or_create_store(merchant_id=merchant.id, db=db)
    product = db.query(Product).filter(Product.merchant_id == merchant.id).first()
    cart = create_cart(slug=store.slug, db=db)
    set_cart_item(
        slug=store.slug,
        token=cart["token"],
        product_id=product.id,
        quantity=1,
        db=db,
    )
    second = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Priority B",
        customer_phone="+229449",
        delivery_mode="pickup",
        delivery_address=None,
        notes="Livrer côté portail",
        db=db,
    )

    reservation = (
        db.query(StockReservation)
        .filter(
            StockReservation.source_type == "online_order",
            StockReservation.source_id == second["id"],
        )
        .one()
    )
    reservation.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()

    orders = list_orders(merchant_id=merchant.id, db=db)

    assert orders[0]["id"] == second["id"]
    assert orders[0]["priority"]["key"] == "stock_expired"
    assert orders[0]["priority"]["rank"] == 0
    assert orders[1]["id"] == first["id"]
    assert orders[1]["priority"]["key"] == "confirm"
