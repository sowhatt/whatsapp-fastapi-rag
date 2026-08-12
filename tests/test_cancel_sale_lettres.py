"""
"Annule la vente vingt-trois" (numéro en toutes lettres, fréquent
avec la transcription vocale) doit fonctionner aussi bien que
"annule la vente n°23" (chiffres).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, _to_business_action
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.product import Product
from app.services import message_orchestrator as mo
from app.services.merchant_service import get_or_create_merchant

SENDER = "cancel-lettres-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_annulation_avec_numero_en_toutes_lettres():
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50, initial_stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Awa cash", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=1, amount=50000, payment="cash", confidence=0.9)
    ))
    send("oui")

    result = send("Annule la vente un")
    assert "Annuler la vente n°1" in result["reply_text"]
    result = send("oui")
    assert "annulée" in result["reply_text"]

    riz = db.query(Product).filter(Product.name == "Riz").first()
    assert riz.stock == 50
