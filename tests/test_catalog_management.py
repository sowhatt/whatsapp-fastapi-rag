"""
Gestion conversationnelle du catalogue : création de produit et
mises à jour (prix de vente, prix d'achat, stock).

Couvre aussi deux régressions découvertes en construisant cette
fonctionnalité :
  - le check générique "amount > 0" de validate_before_confirmation
    ne doit s'appliquer qu'aux types qui utilisent vraiment "amount"
    (pas aux types catalogue, qui utilisent price/purchase_price/stock) ;
  - "modifie le prix de vente du riz" ne doit pas être happé par le
    filtre client des listes de ventes (collision sur "vente du X").
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.validation_agent import validate_before_confirmation
from app.agents import intent_agent
from app.agents.normalization_agent import clear_catalog_values_cache
from app.db.base import Base
from app.models.product import Product
from app.services.catalog_service import (
    create_product_from_action,
    update_product_price,
    update_product_purchase_price,
    update_product_stock,
)
from app.services.sales_list_service import is_sales_list_request
from app.services import message_orchestrator as mo
from app.state.pending_actions import pending_actions
from tests.conftest import with_merchant

SENDER = "22990000003"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def clean_normalization_cache():
    clear_catalog_values_cache()
    yield
    clear_catalog_values_cache()


def teardown_function():
    pending_actions.pop(SENDER, None)


# ── Régression : "amount > 0" ne doit pas concerner le catalogue ──

def test_validation_amount_ignore_les_types_catalogue():
    action = {"type": "catalog_create", "product": "Farine", "price": 20000}
    assert validate_before_confirmation(action, db=None) is None


def test_validation_amount_reste_active_pour_une_vente():
    action = {"type": "sale", "amount": 0, "quantity": 1}
    message = validate_before_confirmation(action, db=None)
    assert message is not None
    assert "montant" in message.lower()


# ── Régression : collision "prix de vente" vs filtre client ───────

def test_modifie_prix_de_vente_nest_pas_pris_pour_une_liste_de_ventes():
    assert not is_sales_list_request("Modifie le prix de vente du riz à 55000")
    assert not is_sales_list_request("Change le prix d'achat du riz à 42000")


def test_ventes_de_client_fonctionne_toujours():
    assert is_sales_list_request("ventes de Awa")


# ── Création de produit ────────────────────────────────────────────

def test_creation_produit(db):
    action = {
        "type": "catalog_create", "product": "Farine de maïs", "unit": "Sac",
        "price": 20000, "purchase_price": 15000, "stock": 10, "product_category": None,
    }
    message = create_product_from_action(action, db)
    assert "Farine de maïs" in message
    created = db.query(Product).filter(Product.name == "Farine de maïs").first()
    assert created is not None
    assert created.price == 20000
    assert created.purchase_price == 15000
    assert created.stock == 10


def test_creation_refuse_un_produit_deja_existant(db):
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100))
    db.commit()
    action = {"type": "catalog_create", "product": "Riz", "unit": "Sac", "price": 60000}
    with pytest.raises(ValueError, match="existe déjà"):
        create_product_from_action(action, db)


def test_nom_produit_explicite_ne_peut_pas_etre_modifie_par_ia(
    db, monkeypatch, clean_normalization_cache
):
    monkeypatch.setattr(
        intent_agent,
        "parse_with_ai",
        lambda text: {
            "type": "catalog_create",
            "product": "Appartement 2",
            "unit": "Pièce",
            "price": 12000,
            "purchase_price": 0,
            "stock": 30,
            "_source": "ai",
            "_confidence": 0.99,
            "_missing_fields": [],
        },
    )

    action = intent_agent.detect_intent(
        "Produit : Appartement 1, Prix de vente : 12 000, "
        "Prix d'achat : 0, Stock : 30, Unité : pièce.",
        db,
    )

    assert action is not None
    assert action["product"] == "Appartement 1"
    assert action["_deterministic_overrides"] == [
        "product_from_explicit_catalog_field"
    ]


def test_confirmation_whatsapp_conserve_appartement_1(
    db, monkeypatch, clean_normalization_cache
):
    # Plusieurs tests historiques remplacent directement mo.detect_intent.
    # Ce scénario doit toujours exercer le vrai détecteur, quelle que soit
    # l'ordre d'exécution de la suite complète.
    monkeypatch.setattr(mo, "detect_intent", intent_agent.detect_intent)
    monkeypatch.setattr(
        intent_agent,
        "parse_with_ai",
        lambda text: {
            "type": "catalog_create",
            "product": "Appartement 2",
            "unit": "Pièce",
            "price": 12000,
            "purchase_price": 0,
            "stock": 30,
            "_source": "ai",
            "_confidence": 0.99,
            "_missing_fields": [],
        },
    )

    result = mo.process_incoming_message(
        channel="whatsapp",
        sender_id=SENDER,
        message_type="audio",
        text=(
            "Produit : Appartement 1, Prix de vente : 12 000, "
            "Prix d'achat : 0, Stock : 30, Unité : pièce."
        ),
        db=db,
    )

    assert "Nouveau produit : Appartement 1 (Pièce)" in result["reply_text"]
    assert "Appartement 2" not in result["reply_text"]


# ── Mises à jour ───────────────────────────────────────────────────

def test_mise_a_jour_prix_de_vente(db):
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100))
    db.commit()
    message = update_product_price({"product": "Riz", "price": 55000}, db)
    assert "50 000" in message and "55 000" in message
    assert db.query(Product).filter(Product.name == "Riz").first().price == 55000


def test_mise_a_jour_prix_d_achat(db):
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100))
    db.commit()
    update_product_purchase_price({"product": "Riz", "purchase_price": 42000}, db)
    assert db.query(Product).filter(Product.name == "Riz").first().purchase_price == 42000


def test_mise_a_jour_stock(db):
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100))
    db.commit()
    message = update_product_stock({"product": "Riz", "stock": 80}, db)
    assert "100" in message and "80" in message
    assert db.query(Product).filter(Product.name == "Riz").first().stock == 80


def test_mise_a_jour_produit_introuvable(db):
    with pytest.raises(ValueError, match="introuvable"):
        update_product_price({"product": "Mil", "price": 10000}, db)


# ── Intégration bout en bout via l'orchestrateur ──────────────────

def test_flux_complet_creation_via_orchestrateur(db, monkeypatch):
    fake_action = {
        "type": "catalog_create", "product": "Farine de maïs", "unit": "Sac",
        "price": 20000, "purchase_price": 15000, "stock": 10,
        "product_category": None, "_missing_fields": [],
    }
    monkeypatch.setattr(mo, "detect_intent", lambda text, db: dict(fake_action))

    result = mo.process_incoming_message(
        channel="whatsapp", sender_id=SENDER, message_type="text",
        text="Crée le produit Farine de maïs, prix de vente 20000, prix d'achat 15000, stock 10",
        db=db,
    )
    assert "Confirmer" in result["reply_text"]

    result2 = mo.process_incoming_message(
        channel="whatsapp", sender_id=SENDER, message_type="text", text="oui", db=db,
    )
    assert "créé" in result2["reply_text"]
    assert db.query(Product).filter(Product.name == "Farine de maïs").first() is not None


def test_flux_complet_maj_prix_via_orchestrateur(db, monkeypatch):
    with_merchant(db, SENDER)
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100))
    db.commit()
    fake_action = {"type": "catalog_update_price", "product": "Riz", "price": 55000, "_missing_fields": []}
    monkeypatch.setattr(mo, "detect_intent", lambda text, db: dict(fake_action))

    mo.process_incoming_message(
        channel="whatsapp", sender_id=SENDER, message_type="text",
        text="Modifie le prix de vente du riz à 55000", db=db,
    )
    result = mo.process_incoming_message(
        channel="whatsapp", sender_id=SENDER, message_type="text", text="oui", db=db,
    )
    assert "mis à jour" in result["reply_text"]
    assert db.query(Product).filter(Product.name == "Riz").first().price == 55000
