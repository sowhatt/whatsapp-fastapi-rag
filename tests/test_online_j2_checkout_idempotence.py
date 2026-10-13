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
from app.domains.online.internal.catalog_service import publish_product


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_checkout_replay_returns_same_order(db):
    merchant = Merchant(whatsapp_number="j2-idempotence", shop_name="Chez Awa")
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    store = get_or_create_store(merchant_id=merchant.id, db=db)

    product = Product(
        merchant_id=merchant.id,
        name="Riz",
        unit="Sac",
        price=10000,
        purchase_price=8000,
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

    first = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Jean",
        customer_phone="+2290001",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        db=db,
    )
    replay = checkout_cart(
        slug=store.slug,
        token=cart["token"],
        customer_name="Jean",
        customer_phone="+2290001",
        delivery_mode="pickup",
        delivery_address=None,
        notes=None,
        db=db,
    )

    assert first["id"] == replay["id"]
    assert first["reference"] == replay["reference"]
    assert replay["idempotent_replay"] is True
    assert db.query(OnlineOrder).count() == 1
