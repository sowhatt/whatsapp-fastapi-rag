"""
Résolution de client/fournisseur insensible aux accents : "Fatai"
(dicté sans tréma, fréquent avec la transcription vocale) doit
retrouver "Fataï" existant en base, à chaque point du parcours —
sans jamais proposer de créer un doublon.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, _to_business_action
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.product import Product
from app.models.supplier import Supplier
from app.services import message_orchestrator as mo
from app.services.merchant_service import get_or_create_merchant
from app.services.text_normalize import find_customer_accent_insensitive, find_supplier_accent_insensitive

SENDER = "accents-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_utilitaire_trouve_avec_et_sans_accent():
    db = _fresh_db()
    db.add(Customer(name="Fataï", debt=0))
    db.commit()

    assert find_customer_accent_insensitive("fatai", db) is not None
    assert find_customer_accent_insensitive("FATAI", db) is not None
    assert find_customer_accent_insensitive("Fataï", db) is not None
    assert find_customer_accent_insensitive("Personne", db) is None


def test_vente_a_fatai_ne_cree_pas_de_doublon():
    db = _fresh_db()
    db.add(Customer(name="Fataï", debt=0))
    db.add(Product(name="Chaussures", unit="Pièce", price=200000, purchase_price=150000, stock=10))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends deux pièces de chaussures à Fatai cash", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fatai", product="Chaussures", unit="Pièce", quantity=2, amount=400000, payment="cash", confidence=0.9)
    ))
    assert "Veux-tu créer ce client" not in result["reply_text"]
    assert "Confirmer" in result["reply_text"]

    send("oui")

    tous = db.query(Customer).all()
    assert len(tous) == 1
    assert tous[0].name == "Fataï"


def test_dette_fatai_trouve_fatai_avec_trema():
    db = _fresh_db()
    db.add(Customer(name="Fataï", debt=25000))
    db.commit()

    result = mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text="dette fatai", db=db)
    assert "Fataï" in result["reply_text"]
    assert "25 000" in result["reply_text"]
    assert "introuvable" not in result["reply_text"]


def test_achat_chez_fournisseur_sans_accent_ne_cree_pas_de_doublon():
    db = _fresh_db()
    db.add(Supplier(name="Sogloé", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Achat 5 sacs de riz chez Sogloe cash", fake=lambda t, d: _to_business_action(
        AIIntent(type="purchase", supplier="Sogloe", product="Riz", unit="Sac", quantity=5, amount=200000, payment="cash", confidence=0.9)
    ))
    assert "Veux-tu créer ce fournisseur" not in result["reply_text"]

    send("oui")
    tous = db.query(Supplier).all()
    assert len(tous) == 1
    assert tous[0].name == "Sogloé"
