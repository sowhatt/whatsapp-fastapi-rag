"""
Annulation d'une vente DÉJÀ ENREGISTRÉE (distincte de "non" qui
annule une vente encore en attente de confirmation) : "annule la
vente n°X" ou "annule ma dernière vente". Vérifie que le stock est
remis et la dette du client corrigée.
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

SENDER = "annulation-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_annulation_vente_confirmee_restaure_stock_et_dette():
    db = _fresh_db()
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50, initial_stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends deux sacs de riz à Awa à crédit", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=2, amount=100000, payment="credit", confidence=0.9)
    ))
    send("oui")
    result = send("oui")
    assert "Vente enregistrée" in result["reply_text"]

    riz = db.query(Product).filter(Product.name == "Riz").first()
    awa = db.query(Customer).filter(Customer.name == "Awa").first()
    assert riz.stock == 48
    assert awa.debt == 100000

    result = send("Annule la vente n°1")
    assert "Annuler la vente n°1" in result["reply_text"]
    result = send("oui")
    assert "annulée" in result["reply_text"]

    db.refresh(riz)
    db.refresh(awa)
    assert riz.stock == 50
    assert awa.debt == 0


def test_annuler_deux_fois_la_meme_vente_est_rejete():
    db = _fresh_db()
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
    send("oui")

    send("Annule la vente n°1")
    send("oui")

    result = send("Annule la vente n°1")
    assert "déjà annulée" in result["reply_text"]


def test_annuler_vente_inexistante():
    db = _fresh_db()
    result = mo.process_incoming_message(
        channel="whatsapp", sender_id=SENDER, message_type="text", text="Annule la vente n°999", db=db
    )
    assert "introuvable" in result["reply_text"]


def test_annuler_derniere_vente_sans_aucune_vente():
    db = _fresh_db()
    result = mo.process_incoming_message(
        channel="whatsapp", sender_id=SENDER, message_type="text", text="Annule ma dernière vente", db=db
    )
    assert "Aucune vente à annuler" in result["reply_text"]
