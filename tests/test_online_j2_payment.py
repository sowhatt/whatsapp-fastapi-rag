import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.internal.transaction_model import BusinessTransaction
from app.domains.online.internal.order_models import OnlineOrder
from app.domains.online.internal.payment_policy import initial_payment_status
from app.domains.online.internal.payment_service import update_payment_status
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public.cart import create_cart, set_cart_item
from app.domains.online.public.checkout import checkout_cart
from app.domains.online.internal.catalog_service import publish_product
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


def _ready_order(db, payment_method="cash_on_delivery"):
    merchant = Merchant(
        whatsapp_number=f"payment-{payment_method}",
        shop_name="Payment Shop",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    store = get_or_create_store(merchant_id=merchant.id, db=db)
    product = Product(
        merchant_id=merchant.id,
        name="Produit paiement",
        unit="Pièce",
        price=3000,
        purchase_price=2000,
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
        customer_name="Client",
        customer_phone="+229500",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        payment_method=payment_method,
        db=db,
    )
    return merchant, result


def test_payment_policy_initial_statuses():
    assert initial_payment_status("cash_on_delivery").value == "cash_on_delivery"
    assert initial_payment_status("mobile_money").value == "mobile_money_pending"


def test_mobile_money_checkout_sets_order_and_transaction_status(db):
    merchant, result = _ready_order(db, payment_method="mobile_money")

    order = db.query(OnlineOrder).one()
    transaction = db.query(BusinessTransaction).one()

    assert result["payment_method"] == "mobile_money"
    assert result["payment_status"] == "mobile_money_pending"
    assert order.payment_method == "mobile_money"
    assert order.payment_status == "mobile_money_pending"
    assert transaction.payment_status == "mobile_money_pending"


def test_mark_paid_syncs_business_transaction_and_emits_event(db):
    merchant, result = _ready_order(db, payment_method="mobile_money")

    order = update_payment_status(
        merchant_id=merchant.id,
        order_id=result["id"],
        status="paid",
        db=db,
    )
    transaction = db.query(BusinessTransaction).one()

    assert order.payment_status == "paid"
    assert transaction.payment_status == "paid"

    payment_events = (
        db.query(OutboxEvent)
        .filter(OutboxEvent.event_type == "payment.received")
        .all()
    )
    assert len(payment_events) == 1


def test_paid_payment_is_terminal(db):
    merchant, result = _ready_order(db)
    update_payment_status(
        merchant_id=merchant.id,
        order_id=result["id"],
        status="paid",
        db=db,
    )

    with pytest.raises(ValueError, match="Transition de paiement invalide"):
        update_payment_status(
            merchant_id=merchant.id,
            order_id=result["id"],
            status="failed",
            db=db,
        )


def test_failed_mobile_money_can_retry(db):
    merchant, result = _ready_order(db, payment_method="mobile_money")
    update_payment_status(
        merchant_id=merchant.id,
        order_id=result["id"],
        status="failed",
        db=db,
    )
    retried = update_payment_status(
        merchant_id=merchant.id,
        order_id=result["id"],
        status="mobile_money_pending",
        db=db,
    )
    assert retried.payment_status == "mobile_money_pending"
