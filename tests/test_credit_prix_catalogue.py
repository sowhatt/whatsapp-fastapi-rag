"""
Une vente "à crédit" dictée SANS montant explicite (donc calculé
automatiquement depuis le prix catalogue) doit correctement fixer le
reste dû sur le vrai montant calculé, pas sur 0 comme si elle était
payée intégralement. Le bug : le reste dû se fixait AVANT que le
montant catalogue ne soit connu, restant à 0 par erreur.
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

SENDER = "credit-catalogue-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_vente_a_credit_sans_montant_fixe_le_bon_reste_du():
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=0))
    db.add(Product(name="Riz parfumé", unit="Sac", price=55000, purchase_price=45000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends deux sacs de riz parfumé à Awa à crédit", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz parfumé", unit="Sac", quantity=2, payment="credit", confidence=0.9)
    ))
    assert "Reste dû : 110 000 FCFA" in result["reply_text"]

    send("oui")

    result = send("vente 1")
    assert "À crédit" in result["reply_text"]
    assert "Payé : 0 FCFA" in result["reply_text"]
    assert "Reste dû : 110 000 FCFA" in result["reply_text"]


def test_vente_a_credit_multi_produits_sans_montant():
    db = _fresh_db()
    db.add(Customer(name="Fatima", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.add(Product(name="Tomate", unit="Carton", price=20000, purchase_price=15000, stock=30))
    db.commit()

    from app.agents.intent_agent import AIIntentItem

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends trois sacs de riz et trois cartons de tomates à Fatima à crédit", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fatima", payment="credit", confidence=0.9, items=[
            AIIntentItem(product="Riz", unit="Sac", quantity=3),
            AIIntentItem(product="Tomate", unit="Carton", quantity=3),
        ])
    ))
    assert "Reste dû : 210 000 FCFA" in result["reply_text"]
