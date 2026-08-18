"""
Un paiement client ("Awa paye X") doit se répartir sur TOUTES les
ventes ouvertes du client (les plus anciennes d'abord), pas
seulement la première trouvée — sinon un paiement dépassant la plus
ancienne vente impayée échouait, même si la dette TOTALE du client
suffisait à le couvrir. Bug trouvé en conditions réelles : "liste
des clients" affichait 180 000 FCFA de dette pour Awa, mais payer
100 000 FCFA échouait avec "dépasse le reste dû 30000" (le montant
de sa plus ancienne vente seulement).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, _to_business_action
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.services import message_orchestrator as mo
from app.services.merchant_service import get_or_create_merchant

SENDER = "paiement-multi-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_paiement_reparti_sur_deux_ventes_ouvertes():
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=30000, purchase_price=25000, stock=100))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Awa à crédit", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=1, amount=30000, payment="credit", confidence=0.9)
    ))
    send("oui")

    send("Vends cinq sacs de riz à Awa à crédit", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=5, amount=150000, payment="credit", confidence=0.9)
    ))
    send("oui")

    result = send("Awa paye cent mille", fake=lambda t, d: _to_business_action(
        AIIntent(type="payment", customer="Awa", amount=100000, confidence=0.9)
    ))
    assert "Confirmer" in result["reply_text"]
    result = send("oui")
    assert "enregistré" in result["reply_text"]
    assert "100 000" in result["reply_text"]

    ventes = db.query(Sale).filter(Sale.customer_id == 1).order_by(Sale.id).all()
    assert ventes[0].remaining_amount == 0
    assert ventes[1].remaining_amount == 80000

    customer = db.query(Customer).filter(Customer.id == 1).first()
    assert customer.debt == 80000


def test_paiement_qui_depasse_la_dette_totale_est_rejete():
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=30000, purchase_price=25000, stock=100))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Awa à crédit", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=1, amount=30000, payment="credit", confidence=0.9)
    ))
    send("oui")

    send("Awa paye deux cent mille", fake=lambda t, d: _to_business_action(
        AIIntent(type="payment", customer="Awa", amount=200000, confidence=0.9)
    ))
    result = send("oui")
    assert "❌" in result["reply_text"]
    assert "30000" in result["reply_text"]

    customer = db.query(Customer).filter(Customer.id == 1).first()
    assert customer.debt == 30000


def test_paiement_qui_solde_exactement_toutes_les_ventes():
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=30000, purchase_price=25000, stock=100))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Awa à crédit", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=1, amount=30000, payment="credit", confidence=0.9)
    ))
    send("oui")
    send("Vends cinq sacs de riz à Awa à crédit", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=5, amount=150000, payment="credit", confidence=0.9)
    ))
    send("oui")

    send("Awa paye cent quatre-vingt mille", fake=lambda t, d: _to_business_action(
        AIIntent(type="payment", customer="Awa", amount=180000, confidence=0.9)
    ))
    send("oui")

    customer = db.query(Customer).filter(Customer.id == 1).first()
    assert customer.debt == 0

    result = send("dette awa")
    assert "Aucune dette en cours" in result["reply_text"]
