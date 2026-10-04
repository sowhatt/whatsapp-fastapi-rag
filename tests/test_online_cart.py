import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public.cart import create_cart, read_cart, set_cart_item
from app.models.merchant import Merchant
from app.models.product import Product
from app.services.customer_catalog_service import publish_product


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _merchant_and_product(db, *, stock=10):
    merchant = Merchant(
        whatsapp_number="cart-test",
        shop_name="Chez Awa",
    )
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
        stock=stock,
        initial_stock=stock,
        threshold=0,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    publish_product(merchant_id=merchant.id, product_id=product.id, db=db)
    return merchant, store, product


def test_create_empty_cart(db):
    _, store, _ = _merchant_and_product(db)
    cart = create_cart(slug=store.slug, db=db)

    assert cart["status"] == "active"
    assert cart["items"] == []
    assert cart["subtotal"] == 0
    assert cart["token"]


def test_add_product_to_cart(db):
    _, store, product = _merchant_and_product(db)
    cart = create_cart(slug=store.slug, db=db)

    updated = set_cart_item(
        slug=store.slug,
        token=cart["token"],
        product_id=product.id,
        quantity=2,
        db=db,
    )

    assert updated["quantity_total"] == 2
    assert updated["subtotal"] == 39000
    assert updated["items"][0]["unit_price"] == 19500


def test_cart_rejects_quantity_above_stock(db):
    _, store, product = _merchant_and_product(db, stock=2)
    cart = create_cart(slug=store.slug, db=db)

    with pytest.raises(ValueError, match="Stock insuffisant"):
        set_cart_item(
            slug=store.slug,
            token=cart["token"],
            product_id=product.id,
            quantity=3,
            db=db,
        )


def test_zero_quantity_removes_product(db):
    _, store, product = _merchant_and_product(db)
    cart = create_cart(slug=store.slug, db=db)
    set_cart_item(
        slug=store.slug,
        token=cart["token"],
        product_id=product.id,
        quantity=1,
        db=db,
    )

    updated = set_cart_item(
        slug=store.slug,
        token=cart["token"],
        product_id=product.id,
        quantity=0,
        db=db,
    )

    assert updated["items"] == []
    assert read_cart(slug=store.slug, token=cart["token"], db=db)["subtotal"] == 0
