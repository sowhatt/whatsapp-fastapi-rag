"""
Une vente/achat en attente du MONTANT ne doit pas rester bloquée si
le commerçant redécrit toute l'opération (articles, quantités,
client) sans encore donner le montant — précisément parce que c'est
ce qu'on lui redemande. La reformulation doit remplacer l'ancienne
opération, pas se faire avaler comme une mauvaise réponse numérique.

Vérifie aussi que le prix catalogue automatique fonctionne pour une
vente multi-produits, pas seulement à un seul produit.
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
    """
    Utilise des produits HORS catalogue exprès : le but ici est de
    tester la reformulation en attente du champ "montant" (donc le
    remplissage automatique par prix catalogue ne doit PAS s'activer
    dans ce test précis — sinon le montant serait rempli tout seul
    et la question ne serait jamais posée).
    """
    db = _fresh_db()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Je voudrais dix sacs de mil et deux cartons de mangues à Soglo", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Soglo", confidence=0.9, items=[
            AIIntentItem(product="Mil", unit="Sac", quantity=10),
            AIIntentItem(product="Mangue", unit="Carton", quantity=2),
        ])
    ))
    assert "montant" in result["reply_text"].lower()

    result = send("J'ai vendu cinq sacs de mil et deux cartons de mangues à Soglo", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Soglo", confidence=0.9, items=[
            AIIntentItem(product="Mil", unit="Sac", quantity=5),
            AIIntentItem(product="Mangue", unit="Carton", quantity=2),
        ])
    ))
    assert "Nouvelle opération détectée" in result["reply_text"]
    assert "Réponds avec un nombre" not in result["reply_text"]


def test_vente_multi_produits_sans_montant_utilise_le_prix_catalogue():
    """
    Complémentaire de la fonctionnalité "prix catalogue automatique"
    (déjà en place pour un seul produit) : doit aussi fonctionner
    pour une vente multi-produits, en additionnant le prix catalogue
    de chaque ligne.
    """
    db = _fresh_db()
    db.add(Customer(name="Fatima", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=50))
    db.add(Product(name="Tomate", unit="Carton", price=20000, purchase_price=15000, stock=30))
    db.commit()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Vends trois sacs de riz et trois cartons de tomates à Fatima", fake=lambda t, d: _to_business_action(
        AIIntent(type="sale", customer="Fatima", confidence=0.9, items=[
            AIIntentItem(product="Riz", unit="Sac", quantity=3),
            AIIntentItem(product="Tomate", unit="Carton", quantity=3),
        ])
    ))
    assert "210 000" in result["reply_text"]
    assert "Quel est le montant total" not in result["reply_text"]


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
