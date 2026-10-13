import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal.catalog_service import publish_product
from app.domains.online.internal.order_models import OnlineOrder
from app.domains.online.internal.order_service import update_order_status
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


def _create_order(db):
    merchant = Merchant(
        whatsapp_number="+22990000000",
        shop_name="Notification Shop",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    store = get_or_create_store(merchant_id=merchant.id, db=db)
    product = Product(
        merchant_id=merchant.id,
        name="Produit Notification",
        unit="Pièce",
        price=2500,
        purchase_price=1800,
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
        customer_name="Client Notification",
        customer_phone="+22997000000",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        db=db,
    )
    order = db.query(OnlineOrder).filter(OnlineOrder.id == result["id"]).one()
    return merchant, store, cart, order


def _notification_events(db):
    return (
        db.query(OutboxEvent)
        .filter(OutboxEvent.event_type == "notification.requested")
        .order_by(OutboxEvent.id)
        .all()
    )


def test_order_created_enqueues_customer_and_merchant_notifications(db):
    merchant, _, _, order = _create_order(db)

    events = _notification_events(db)
    assert len(events) == 2

    payloads = [event.payload["data"] for event in events]
    by_role = {payload["recipient_role"]: payload for payload in payloads}

    assert by_role["customer"]["recipient"] == "+22997000000"
    assert by_role["customer"]["template"] == "online_order_created_customer"
    assert by_role["merchant"]["recipient"] == merchant.whatsapp_number
    assert by_role["merchant"]["template"] == "online_order_created_merchant"

    for payload in payloads:
        assert payload["channel"] == "whatsapp"
        assert payload["context"]["reference"] == order.reference
        assert payload["context"]["stage"] == "created"


def test_notification_intents_follow_order_lifecycle(db):
    merchant, _, _, order = _create_order(db)

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
    update_order_status(
        merchant_id=merchant.id,
        order_id=order.id,
        status="completed",
        db=db,
    )

    events = _notification_events(db)
    assert len(events) == 8

    templates = [event.payload["data"]["template"] for event in events]
    assert templates.count("online_order_created_customer") == 1
    assert templates.count("online_order_created_merchant") == 1
    assert templates.count("online_order_confirmed_customer") == 1
    assert templates.count("online_order_confirmed_merchant") == 1
    assert templates.count("online_order_ready_customer") == 1
    assert templates.count("online_order_ready_merchant") == 1
    assert templates.count("online_order_completed_customer") == 1
    assert templates.count("online_order_completed_merchant") == 1

    stages = [
        event.payload["data"]["context"]["stage"]
        for event in events
    ]
    assert stages.count("created") == 2
    assert stages.count("confirmed") == 2
    assert stages.count("ready") == 2
    assert stages.count("completed") == 2


def test_checkout_replay_does_not_duplicate_created_notifications(db):
    _, store, cart, order = _create_order(db)

    first_count = len(_notification_events(db))
    replay = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Client Notification",
        customer_phone="+22997000000",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        db=db,
    )

    assert replay["id"] == order.id
    assert replay["idempotent_replay"] is True
    assert len(_notification_events(db)) == first_count



def test_customer_notification_contains_ready_to_send_message_and_tracking_path(db):
    merchant, store, _, order = _create_order(db)

    event = (
        db.query(OutboxEvent)
        .filter(
            OutboxEvent.event_type == "notification.requested",
        )
        .order_by(OutboxEvent.id)
        .first()
    )
    data = event.payload["data"]

    assert data["recipient_role"] == "customer"
    assert order.reference in data["message"]
    assert store.display_name in data["message"]
    assert data["tracking_path"].startswith(
        f"/shop/{store.slug}/order/{order.reference}?phone="
    )
    assert data["tracking_path"] in data["message"]


def test_ready_and_completed_customer_messages_are_specific(db):
    merchant, _, _, order = _create_order(db)

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
    update_order_status(
        merchant_id=merchant.id,
        order_id=order.id,
        status="completed",
        db=db,
    )

    customer_events = [
        event.payload["data"]
        for event in _notification_events(db)
        if event.payload["data"]["recipient_role"] == "customer"
    ]
    by_stage = {
        row["context"]["stage"]: row
        for row in customer_events
    }

    assert "prête" in by_stage["ready"]["message"].lower()
    assert "terminée" in by_stage["completed"]["message"].lower()
    assert order.reference in by_stage["completed"]["message"]
