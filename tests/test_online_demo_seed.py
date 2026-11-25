"""Jeu de démonstration Online : idempotent, protège les commerçants réels."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.domains.online.internal.stock_policy import online_available_stock, resolve_stock_policy
from app.domains.online.public.storefront import read_public_catalog
from app.models.merchant import Merchant
from app.models.product import Product
from scripts.online_demo_seed import DEMO_NUMBER, DEMO_SLUG, seed_demo


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()


def test_seed_publie_une_vitrine_avec_les_trois_modes(db):
    result = seed_demo(db)
    assert result["slug"] == DEMO_SLUG and len(result["products"]) == 5
    catalog = read_public_catalog(slug=DEMO_SLUG, db=db)
    states = {p["name"]: p["availability"] for p in catalog["products"]}
    assert states["Riz parfumé 25 kg"] == "in_stock"
    assert states["Huile végétale 5 L"] == "low_stock"        # 2 unités, seuil 2
    assert states["Jus de bissap 1 L"] == "in_stock"          # quantité du jour
    assert states["Couture sur mesure"] == "in_stock"         # sur commande
    assert {p["category"] for p in catalog["products"]} == {"Épicerie", "Boissons", "Services"}


def test_seed_est_idempotent(db):
    first = seed_demo(db)
    second = seed_demo(db)
    assert first == second
    assert db.query(Product).count() == 5 and db.query(Merchant).count() == 1


def test_seed_refuse_un_commercant_reel(db):
    db.add(Merchant(whatsapp_number=DEMO_NUMBER, shop_name="Chez Awa"))
    db.commit()
    with pytest.raises(ValueError, match="commerçant réel"):
        seed_demo(db)
    assert db.query(Product).count() == 0


def test_apercu_sans_apply_n_ecrit_rien(capsys):
    from scripts.online_demo_seed import main
    assert main([]) == 0
    assert "Aperçu seulement" in capsys.readouterr().out
