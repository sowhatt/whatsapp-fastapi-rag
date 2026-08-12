"""
Une vente/achat en attente du MONTANT ne doit pas rester bloquée si
le commerçant redécrit toute l'opération (articles, quantités,
client) sans encore donner le montant — précisément parce que c'est
ce qu'on lui redemande. La reformulation doit remplacer l'ancienne
opération, pas se faire avaler comme une mauvaise réponse numérique.
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

SENDER = "reformulation-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_reformulation_sans_montant_remplace_la_vente_en_attente():
    db = _fresh_db()
    db.add(Customer(name="Soglo", debt=0))
    db.add(Product(name="Riz parfumé", unit="Sac", price=55000, purchase_price=45000, stock=50))
    db.add(Product(name="Tomate", unit="Carton", price=20000, purchase_price=15000, stock=30))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Je voudrais dix sacs de riz parfumé et deux cartons de tomates à Soglo", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Soglo", confidence=0.9, items=[
            AIIntentItem(product="Riz parfumé", unit="Sac", quantity=10),
            AIIntentItem(product="Tomate", unit="Carton", quantity=2),
        ])
    ))
    assert "montant" in result["reply_text"].lower()

    result = send("J'ai vendu cinq sacs de riz parfumé et deux cartons de tomates à Soglo", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Soglo", confidence=0.9, items=[
            AIIntentItem(product="Riz parfumé", unit="Sac", quantity=5),
            AIIntentItem(product="Tomate", unit="Carton", quantity=2),
        ])
    ))
    assert "Nouvelle opération détectée" in result["reply_text"]
    assert "Réponds avec un nombre" not in result["reply_text"]


def test_reponse_simple_ne_declenche_toujours_pas_de_remplacement():
    """
    Garde-fou : une réponse simple au champ demandé (ex. juste un
    nombre, ou "vingt sacs" sans verbe) ne doit JAMAIS être prise pour
    une reformulation complète — sinon on casse le flux normal de
    réponse à un champ manquant.
    """
    db = _fresh_db()
    db.add(Customer(name="Awa", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Vends deux sacs de riz à Awa", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Awa", product="Riz", unit="Sac", quantity=2, confidence=0.9)
    ))
    result = send("cent mille")
    assert "Nouvelle opération détectée" not in result["reply_text"]
