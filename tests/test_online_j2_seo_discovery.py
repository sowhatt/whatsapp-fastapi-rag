from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal.catalog_service import publish_product
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public.seo_discovery import list_indexable_paths
from app.models.merchant import Merchant
from app.models.product import Product


def test_sitemap_paths_include_store_and_published_product_only():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    merchant = Merchant(whatsapp_number="j2-seo", shop_name="Chez Awa")
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
    publication = publish_product(
        merchant_id=merchant.id,
        product_id=product.id,
        db=db,
        seo_slug="riz-parfume",
    )

    paths = list_indexable_paths(db=db)

    assert f"/shop/{store.slug}" in paths
    assert f"/shop/{store.slug}/p/{publication.seo_slug}" in paths
    db.close()
