import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public import (
    read_public_catalog,
    read_public_product,
    read_public_store,
)
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


def _merchant(db):
    merchant = Merchant(
        whatsapp_number="online-public-test",
        shop_name="Chez Awa",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)
    return merchant


def _product(db, merchant, *, name="Riz parfumé", stock=12):
    product = Product(
        merchant_id=merchant.id,
        name=name,
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
    return product


def test_public_store_exposes_only_storefront_configuration(db):
    merchant = _merchant(db)
    store = get_or_create_store(merchant_id=merchant.id, db=db)

    payload = read_public_store(slug=store.slug, db=db)

    assert payload["slug"] == "chez-awa"
    assert payload["display_name"] == "Chez Awa"
    assert "merchant_id" not in payload
    assert "whatsapp_number" not in payload


def test_public_catalog_exposes_only_published_products(db):
    merchant = _merchant(db)
    store = get_or_create_store(merchant_id=merchant.id, db=db)
    published = _product(db, merchant, name="Riz parfumé")
    _product(db, merchant, name="Produit privé")

    publish_product(
        merchant_id=merchant.id,
        product_id=published.id,
        db=db,
    )

    payload = read_public_catalog(slug=store.slug, db=db)

    assert [item["name"] for item in payload["products"]] == ["Riz parfumé"]
    assert "purchase_price" not in payload["products"][0]


def test_public_product_respects_publication(db):
    merchant = _merchant(db)
    store = get_or_create_store(merchant_id=merchant.id, db=db)
    product = _product(db, merchant)

    assert read_public_product(
        slug=store.slug,
        product_id=product.id,
        db=db,
    ) is None

    publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
    )

    payload = read_public_product(
        slug=store.slug,
        product_id=product.id,
        db=db,
    )

    assert payload["name"] == "Riz parfumé"
    assert payload["price"] == 19500
    assert "purchase_price" not in payload
