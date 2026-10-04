import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal.order_models import OnlineOrder
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public.cart import create_cart, set_cart_item
from app.domains.online.public.checkout import checkout_cart
from app.models.merchant import Merchant
from app.models.product import Product
from app.services.customer_catalog_service import publish_product
from app.shared.outbox.model import OutboxEvent


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _ready_cart(db):
    merchant = Merchant(whatsapp_number="checkout-test", shop_name="Chez Awa")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    store = get_or_create_store(merchant_id=merchant.id, db=db)

    product = Product(
        merchant_id=merchant.id,
        name="Riz parfumé",
        unit="Sac",
        price=19500,
        purchase_price=17000,
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
        quantity=2,
        db=db,
    )
    return merchant, store, product, cart


def test_checkout_creates_order_transaction_and_outbox(db):
    merchant, store, product, cart = _ready_cart(db)

    result = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Jean Client",
        customer_phone="+2290100000000",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        db=db,
    )

    assert result["status"] == "pending"
    assert result["total"] == 39000
    assert result["reference"].startswith("WO-")

    order = db.query(OnlineOrder).one()
    assert order.merchant_id == merchant.id
    assert order.transaction_id is not None

    event = db.query(OutboxEvent).one()
    assert event.event_type == "commerce.order.created"
    assert event.aggregate_id == str(order.id)


def test_delivery_checkout_requires_address(db):
    _, store, _, cart = _ready_cart(db)

    with pytest.raises(ValueError, match="adresse de livraison"):
        checkout_cart(
            slug=store.slug,
            token=cart["token"],
            customer_name="Jean Client",
            customer_phone="+2290100000000",
            delivery_mode="delivery",
            delivery_address=None,
            notes=None,
            db=db,
        )
