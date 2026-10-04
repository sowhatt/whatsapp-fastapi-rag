import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal.models import OnlineStore
from app.domains.online.internal.store_service import (
    get_or_create_store,
    get_public_store,
    normalize_store_slug,
)
from app.models.merchant import Merchant


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_slug_is_url_safe():
    assert normalize_store_slug("Chez Awa Délices") == "chez-awa-delices"


def test_store_is_created_from_existing_merchant(db):
    merchant = Merchant(
        whatsapp_number="test-online-awa",
        shop_name="Chez Awa",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    store = get_or_create_store(merchant_id=merchant.id, db=db)

    assert store.slug == "chez-awa"
    assert store.display_name == "Chez Awa"
    assert store.currency == "XOF"
    assert store.country_code == "BJ"
    assert db.query(OnlineStore).count() == 1


def test_get_or_create_is_idempotent(db):
    merchant = Merchant(
        whatsapp_number="test-online-idempotent",
        shop_name="Chez Fati",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    first = get_or_create_store(merchant_id=merchant.id, db=db)
    second = get_or_create_store(merchant_id=merchant.id, db=db)

    assert first.id == second.id
    assert db.query(OnlineStore).count() == 1


def test_inactive_store_is_not_public(db):
    merchant = Merchant(
        whatsapp_number="test-online-inactive",
        shop_name="Boutique Fermée",
    )
    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    store = get_or_create_store(merchant_id=merchant.id, db=db)
    store.is_active = False
    db.commit()

    assert get_public_store(slug=store.slug, db=db) is None
