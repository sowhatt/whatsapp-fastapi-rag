"""
Le prix catalogue automatique (vente sans montant) doit reconnaître
un nom de produit PARTIEL, pas seulement une correspondance exacte —
sinon dire "chaussures" pour un produit enregistré "Chaussures
mocassins" faisait abandonner tout le calcul automatique, redemandant
le montant total au lieu de le calculer.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, AIIntentItem, _to_business_action
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.product import Product
from app.services import message_orchestrator as mo
from app.services.merchant_service import get_or_create_merchant

SENDER = "recherche-souple-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_nom_partiel_multi_produits_utilise_le_prix_catalogue():
    global SENDER
    SENDER = "recherche-souple-pytest-1"
    db = _fresh_db()
    db.add(Product(name="Chaussures mocassins", unit="Pièce", price=15000, purchase_price=10000, stock=20))
    db.add(Product(name="Chaussettes", unit="Unités/pièces", price=2000, purchase_price=1000, stock=50))
    db.add(Customer(name="Fataï", debt=0))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends deux pièces de chaussures et deux pièces de chaussettes à Fataï", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fataï", confidence=0.9, items=[
            AIIntentItem(product="chaussures", unit="Pièce", quantity=2),
            AIIntentItem(product="chaussettes", unit="Unités/pièces", quantity=2),
        ])
    ))
    assert "34 000" in result["reply_text"]
    assert "Quel est le montant total" not in result["reply_text"]


def test_nom_partiel_produit_unique_utilise_le_prix_catalogue():
    global SENDER
    SENDER = "recherche-souple-pytest-2"
    db = _fresh_db()
    db.add(Product(name="Chaussures mocassins", unit="Pièce", price=15000, purchase_price=10000, stock=20))
    db.add(Customer(name="Fataï", debt=0))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends deux chaussures à Fataï", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fataï", product="chaussures", unit="Pièce", quantity=2, confidence=0.9)
    ))
    assert "30 000" in result["reply_text"]


def test_nom_ambigu_abandonne_proprement_sans_deviner():
    global SENDER
    SENDER = "recherche-souple-pytest-3"
    """
    Garde-fou : si le nom partiel correspond à PLUSIEURS produits du
    catalogue, le calcul automatique doit s'abstenir (pas deviner
    lequel), en redemandant le montant normalement.
    """
    db = _fresh_db()
    db.add(Product(name="Chaussures mocassins", unit="Pièce", price=15000, purchase_price=10000, stock=20))
    db.add(Product(name="Chaussures sport", unit="Pièce", price=20000, purchase_price=15000, stock=15))
    db.add(Customer(name="Fataï", debt=0))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends deux chaussures à Fataï", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fataï", product="chaussures", unit="Pièce", quantity=2, confidence=0.9)
    ))
    assert "Quel est le montant total" in result["reply_text"]
