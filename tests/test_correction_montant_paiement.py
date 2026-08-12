"""
Une correction explicite du montant ("montant deux millions") pendant
qu'une vente/achat attend le moyen de paiement doit être prise en
compte, pas silencieusement ignorée par la question de paiement en
cours.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, _to_business_action
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.product import Product
from app.models.supplier import Supplier
from app.services import message_orchestrator as mo
from app.services.merchant_service import get_or_create_merchant

SENDER = "correction-montant-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_correction_montant_pendant_attente_paiement():
    db = _fresh_db()
    db.add(Supplier(name="Soglo", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=60000, purchase_price=200000, stock=0))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Achat 50 sacs de riz chez Soglo pour dix millions", fake=lambda t, d: _to_business_action(
        AIIntent(type="purchase", supplier="Soglo", product="Riz", unit="Sac", quantity=50, amount=10000000, confidence=0.9)
    ))
    send("oui")

    result = send("Montant deux millions")
    assert "Cash, crédit, Moov ou MTN" in result["reply_text"]

    result = send("cash")
    assert "2 000 000 FCFA" in result["reply_text"]
    assert "10 000 000" not in result["reply_text"]
