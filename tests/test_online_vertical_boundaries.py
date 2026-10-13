import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal.store_service import get_or_create_store
from app.domains.online.public.cart import create_cart
from app.domains.online.public.storefront import read_public_catalog
from app.models.merchant import Merchant


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_restaurant_store_cannot_use_commerce_catalog_or_cart(db):
    merchant = Merchant(
        whatsapp_number="vertical-boundary-restaurant",
        shop_name="Le Palmier",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    store = get_or_create_store(
        merchant_id=merchant.id,
        db=db,
        business_type="restaurant",
    )

    with pytest.raises(ValueError, match="Vertical Online non disponible ici"):
        read_public_catalog(slug=store.slug, db=db)

    with pytest.raises(ValueError, match="Vertical Online non disponible ici"):
        create_cart(slug=store.slug, db=db)
