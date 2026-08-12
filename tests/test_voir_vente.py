"""
Consultation du détail d'une vente précise ("vente 23", "montre la
vente 23") : simple lecture à tout moment, avec ou sans article
("vente 23" comme "la vente 23"), chiffres ou nombre en toutes
lettres. Ne doit jamais entrer en collision avec une vraie nouvelle
vente en train d'être dictée.
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

SENDER = "voir-vente-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_voir_vente_forme_courte_sans_article():
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100, initial_stock=100))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends deux sacs de riz à Awa cash", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=2, amount=100000, payment="cash", confidence=0.9)
    ))
    send("oui")

    result = send("vente 1")
    assert "Vente n°1" in result["reply_text"]
    assert "Riz" in result["reply_text"]
    assert "100 000" in result["reply_text"]


def test_voir_vente_avec_verbe_et_nombre_en_lettres():
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100, initial_stock=100))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends deux sacs de riz à Awa cash", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=2, amount=100000, payment="cash", confidence=0.9)
    ))
    send("oui")

    result = send("Montre-moi la vente un")
    assert "Vente n°1" in result["reply_text"]


def test_vente_introuvable():
    db = _fresh_db()
    result = mo.process_incoming_message(
        channel="whatsapp", sender_id=SENDER, message_type="text", text="vente 999", db=db
    )
    assert "introuvable" in result["reply_text"]


def test_nouvelle_vente_pas_cassee_par_la_detection():
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100, initial_stock=100))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends deux sacs de riz à Awa cash", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=2, amount=100000, payment="cash", confidence=0.9)
    ))
    assert "Confirmer" in result["reply_text"]
    assert "introuvable" not in result["reply_text"]
