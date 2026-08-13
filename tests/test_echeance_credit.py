"""
Échéance de paiement pour une vente à crédit : "échéance dans X
jours" (relative) ou "échéance le DD/MM" (absolue), affichée dans la
confirmation, la fiche de vente et la fiche client — avec alerte si
dépassée.
"""
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, _to_business_action
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.product import Product
from app.models.sale import Sale
from app.services import message_orchestrator as mo
from app.services.merchant_service import get_or_create_merchant

SENDER = "echeance-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_echeance_relative_dans_x_jours():
    db = _fresh_db()
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends deux sacs de riz à Awa à crédit, échéance dans 15 jours", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=2, amount=100000, payment="credit", confidence=0.9)
    ))
    send("oui")
    result = send("oui")
    assert "enregistrée" in result["reply_text"]

    sale = db.query(Sale).filter(Sale.id == 1).first()
    assert sale.due_date == date.today() + timedelta(days=15)


def test_echeance_absolue_jour_mois():
    db = _fresh_db()
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Fanta à crédit, échéance le 30/08", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fanta", product="Riz", unit="Sac", quantity=1, amount=50000, payment="credit", confidence=0.9)
    ))
    send("oui")
    send("oui")

    sale = db.query(Sale).filter(Sale.id == 1).first()
    assert sale.due_date == date(date.today().year, 8, 30)


def test_alerte_echeance_depassee_dans_fiche_vente():
    db = _fresh_db()
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Awa à crédit", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=1, amount=50000, payment="credit", confidence=0.9)
    ))
    send("oui")
    send("oui")

    sale = db.query(Sale).filter(Sale.id == 1).first()
    sale.due_date = date.today() - timedelta(days=5)
    db.commit()

    result = send("vente 1")
    assert "⚠️ Échéance dépassée" in result["reply_text"]

    result = send("client Awa")
    assert "Ventes avec dette (1)" in result["reply_text"]
    assert "⚠️ échéance dépassée" in result["reply_text"]


def test_vente_sans_echeance_ne_montre_rien():
    """
    Garde-fou : une vente cash normale (sans mention d'échéance) ne
    doit jamais afficher de ligne "Échéance" vide ou erronée.
    """
    db = _fresh_db()
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends un sac de riz à Awa cash", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=1, amount=50000, payment="cash", confidence=0.9)
    ))
    result = send("oui")
    assert "Échéance" not in result["reply_text"]


def test_fiche_client_ne_montre_que_les_ventes_avec_dette():
    """
    Une vente payée cash ne doit jamais apparaître dans la liste
    "Ventes avec dette" — seules les ventes avec un reste dû y
    figurent, avec leur date et leur échéance.
    """
    db = _fresh_db()
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100))
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

    send("Vends deux sacs de riz à Awa à crédit, échéance dans 10 jours", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=2, amount=100000, payment="credit", confidence=0.9)
    ))
    result = send("oui")
    assert "Vente enregistrée" in result["reply_text"]

    result = send("dette awa")
    assert "Ventes avec dette (1)" in result["reply_text"]
    assert "#2" in result["reply_text"]
    assert "#1" not in result["reply_text"]
