import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal.order_service import get_order, list_orders
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
