import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.category import Category
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_publication import ProductPublication
from app.services.customer_catalog_service import (
    add_product_image,
    list_customer_catalog,
    publish_product,
    render_customer_catalog,
    search_customer_catalog,
    unpublish_product,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")

    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    session.close()


def create_merchant(db, name):
    merchant = Merchant(
        whatsapp_number=f"test-{name.lower().replace(' ', '-')}",
        shop_name=name,
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return merchant


def create_product(db, merchant, name, price, stock):
    product = Product(
        merchant_id=merchant.id,
        name=name,
        unit="Sac",
        price=price,
        purchase_price=0,
        stock=stock,
        initial_stock=stock,
        threshold=0,
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    return product


def test_unpublished_product_is_not_visible(db):
    merchant = create_merchant(db, "Chez Awa")
    create_product(db, merchant, "Riz parfumé", 19500, 30)

    catalog = list_customer_catalog(
        merchant_id=merchant.id,
        db=db,
    )

    assert catalog == []


def test_published_product_is_visible(db):
    merchant = create_merchant(db, "Chez Awa")
    product = create_product(
        db,
        merchant,
        "Riz parfumé",
        19500,
        30,
    )

    publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
    )

    catalog = list_customer_catalog(
        merchant_id=merchant.id,
        db=db,
    )

    assert len(catalog) == 1
    assert catalog[0]["name"] == "Riz parfumé"
    assert catalog[0]["price"] == 19500
    assert catalog[0]["available"] is True

    # Par défaut le client ne voit pas le stock exact.
    assert catalog[0]["stock"] is None


def test_customer_never_receives_purchase_price(db):
    merchant = create_merchant(db, "Chez Awa")

    product = Product(
        merchant_id=merchant.id,
        name="Maïs",
        unit="Sac",
        price=20000,
        purchase_price=15000,
        stock=10,
        initial_stock=10,
        threshold=0,
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
    )

    catalog = list_customer_catalog(
        merchant_id=merchant.id,
        db=db,
    )

    assert "purchase_price" not in catalog[0]
    assert catalog[0]["price"] == 20000


def test_stock_can_be_exposed_if_merchant_wants_it(db):
    merchant = create_merchant(db, "Chez Awa")
    product = create_product(db, merchant, "Maïs", 17000, 30)

    publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
        show_stock=True,
    )

    catalog = list_customer_catalog(
        merchant_id=merchant.id,
        db=db,
    )

    assert catalog[0]["stock"] == 30


def test_product_image_is_returned(db):
    merchant = create_merchant(db, "Chez Awa")
    product = create_product(db, merchant, "Huile rouge", 7500, 12)

    publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
    )

    add_product_image(
        merchant_id=merchant.id,
        product_id=product.id,
        image_url="https://example.com/huile.jpg",
        db=db,
        is_primary=True,
    )

    catalog = list_customer_catalog(
        merchant_id=merchant.id,
        db=db,
    )

    assert catalog[0]["image_url"] == "https://example.com/huile.jpg"


def test_search_only_returns_published_products(db):
    merchant = create_merchant(db, "Chez Awa")

    riz = create_product(db, merchant, "Riz parfumé", 19500, 30)
    create_product(db, merchant, "Riz premium privé", 25000, 8)

    publish_product(
        merchant_id=merchant.id,
        product_id=riz.id,
        db=db,
    )

    results = search_customer_catalog(
        merchant_id=merchant.id,
        query="riz",
        db=db,
    )

    assert len(results) == 1
    assert results[0]["name"] == "Riz parfumé"


def test_catalog_is_isolated_by_merchant(db):
    merchant_a = create_merchant(db, "Chez Awa")
    merchant_b = create_merchant(db, "Chez Fati")

    riz_a = create_product(db, merchant_a, "Riz Awa", 19000, 10)
    riz_b = create_product(db, merchant_b, "Riz Fati", 18000, 20)

    publish_product(
        merchant_id=merchant_a.id,
        product_id=riz_a.id,
        db=db,
    )

    publish_product(
        merchant_id=merchant_b.id,
        product_id=riz_b.id,
        db=db,
    )

    catalog_a = list_customer_catalog(
        merchant_id=merchant_a.id,
        db=db,
    )

    assert len(catalog_a) == 1
    assert catalog_a[0]["name"] == "Riz Awa"


def test_unpublish_removes_product_from_customer_catalog(db):
    merchant = create_merchant(db, "Chez Awa")
    product = create_product(db, merchant, "Maïs", 17000, 30)

    publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
    )

    unpublish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
    )

    catalog = list_customer_catalog(
        merchant_id=merchant.id,
        db=db,
    )

    assert catalog == []


def test_render_catalog_does_not_show_purchase_price(db):
    merchant = create_merchant(db, "Chez Awa")

    product = Product(
        merchant_id=merchant.id,
        name="Riz parfumé",
        unit="Sac",
        price=19500,
        purchase_price=17000,
        stock=30,
        initial_stock=30,
        threshold=0,
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
    )

    rendered = render_customer_catalog(
        merchant_id=merchant.id,
        db=db,
    )

    assert "19 500 FCFA" in rendered
    assert "17 000" not in rendered
