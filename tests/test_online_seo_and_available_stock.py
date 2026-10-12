import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.core.public.stock import reserve_stock
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public import read_public_catalog, read_public_product_by_slug
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


def test_public_catalog_uses_available_stock_and_seo_slug(db):
    merchant = Merchant(
        whatsapp_number="seo-stock-test",
        shop_name="Chez Awa",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    store = get_or_create_store(merchant_id=merchant.id, db=db)
    product = Product(
        merchant_id=merchant.id,
        name="Riz parfumé 25 kg",
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

    publication = publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
        show_stock=True,
    )
    reserve_stock(
        merchant_id=merchant.id,
        product_id=product.id,
        quantity=4,
        source_type="online_order",
        source_id=999,
        db=db,
    )
    db.commit()

    catalog = read_public_catalog(slug=store.slug, db=db)

    assert publication.seo_slug == "riz-parfume-25-kg"
    assert catalog["products"][0]["stock"] == 6
    assert catalog["products"][0]["available"] is True

    detail = read_public_product_by_slug(
        slug=store.slug,
        product_slug="riz-parfume-25-kg",
        db=db,
    )
    assert detail["name"] == "Riz parfumé 25 kg"
    assert detail["stock"] == 6


def test_short_product_name_gets_safe_slug(db):
    merchant = Merchant(
        whatsapp_number="seo-short-test",
        shop_name="Tech Shop",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    product = Product(
        merchant_id=merchant.id,
        name="TV",
        unit="Pièce",
        price=100000,
        purchase_price=80000,
        stock=2,
        initial_stock=2,
        threshold=0,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    publication = publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
    )

    assert publication.seo_slug == f"produit-{product.id}"
