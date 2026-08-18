"""
Vente multi-produits où l'un des articles a une unité incompatible
avec le catalogue : doit donner un message clair sur LE produit
précis en cause (pas juste "réponds avec un nombre" ou bloquer sur
le premier produit en ignorant les autres). Bug trouvé en conditions
réelles : "deux chaussures mocassins et deux chaussettes" bloquait
le bot dans une confusion répétée.
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

SENDER = "multi-produits-unite-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_unite_incompatible_donne_message_clair_sur_le_bon_produit():
    global SENDER
    SENDER = "multi-produits-unite-pytest-1"
    db = _fresh_db()
    db.add(Customer(name="Fataï", debt=0))
    db.add(Product(name="Chaussures mocassins", unit="Pièce", price=15000, purchase_price=10000, stock=20))
    db.add(Product(name="Chaussettes", unit="Pièce", price=2000, purchase_price=1000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends deux chaussures mocassins et deux chaussettes à Fataï", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fataï", confidence=0.9, items=[
            AIIntentItem(product="Chaussures mocassins", unit="Paire", quantity=2),
            AIIntentItem(product="Chaussettes", unit="Pièce", quantity=2),
        ])
    ))
    assert "Chaussures mocassins" in result["reply_text"]
    assert "Pièce" in result["reply_text"]
    assert "Réponds avec un nombre" not in result["reply_text"]


def test_reformulation_avec_bonne_unite_reussit():
    global SENDER
    SENDER = "multi-produits-unite-pytest-2"
    db = _fresh_db()
    db.add(Customer(name="Fataï", debt=0))
    db.add(Product(name="Chaussures mocassins", unit="Pièce", price=15000, purchase_price=10000, stock=20))
    db.add(Product(name="Chaussettes", unit="Pièce", price=2000, purchase_price=1000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends deux chaussures mocassins et deux chaussettes à Fataï", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fataï", confidence=0.9, items=[
            AIIntentItem(product="Chaussures mocassins", unit="Paire", quantity=2),
            AIIntentItem(product="Chaussettes", unit="Pièce", quantity=2),
        ])
    ))
    result = send("Vends deux pièces de chaussures mocassins et deux pièces de chaussettes à Fataï", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fataï", confidence=0.9, items=[
            AIIntentItem(product="Chaussures mocassins", unit="Pièce", quantity=2),
            AIIntentItem(product="Chaussettes", unit="Pièce", quantity=2),
        ])
    ))
    assert "34 000" in result["reply_text"]
    assert "chaussures mocassins" in result["reply_text"]
    assert "chaussettes" in result["reply_text"]


def test_stock_insuffisant_multi_produits_message_clair():
    global SENDER
    SENDER = "multi-produits-unite-pytest-3"
    db = _fresh_db()
    db.add(Customer(name="Fataï", debt=0))
    db.add(Product(name="Chaussures mocassins", unit="Pièce", price=15000, purchase_price=10000, stock=1))
    db.add(Product(name="Chaussettes", unit="Pièce", price=2000, purchase_price=1000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends deux chaussures mocassins et deux chaussettes à Fataï", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fataï", confidence=0.9, items=[
            AIIntentItem(product="Chaussures mocassins", unit="Pièce", quantity=2),
            AIIntentItem(product="Chaussettes", unit="Pièce", quantity=2),
        ])
    ))
    assert "Stock insuffisant pour Chaussures mocassins" in result["reply_text"]
