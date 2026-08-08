"""
Test de bout en bout de l'isolation multi-tenant, via de vrais appels
à process_incoming_message (pas seulement des vérifications directes
en base) : deux commerçants réels, sur deux numéros WhatsApp réels,
doivent avoir des catalogues et un stock totalement séparés.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, _to_business_action
from app.db.base import Base
from app.models.product import Product
from app.services import message_orchestrator as mo
from app.services.merchant_service import get_or_create_merchant
from app.state.pending_actions import pending_actions

PATRON_1 = "22990000020"
PATRON_2 = "22990000021"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_deux_commercants_isoles_de_bout_en_bout_via_whatsapp():
    db = _fresh_db()

    def make_fake(parsed):
        return lambda t, d: _to_business_action(parsed)

    mo.detect_intent = make_fake(
        AIIntent(
            type="catalog_create", product="Riz", unit="Sac",
            price=50000, purchase_price=40000, stock=10, confidence=0.9,
        )
    )
    mo.process_incoming_message(
        channel="whatsapp", sender_id=PATRON_1, message_type="text",
        text="Crée le produit Riz, prix de vente 50000, prix d'achat 40000, stock 10, unité sac", db=db,
    )
    mo.process_incoming_message(channel="whatsapp", sender_id=PATRON_1, message_type="text", text="oui", db=db)

    mo.detect_intent = make_fake(
        AIIntent(
            type="catalog_create", product="Riz", unit="Sac",
            price=99000, purchase_price=80000, stock=3, confidence=0.9,
        )
    )
    mo.process_incoming_message(
        channel="whatsapp", sender_id=PATRON_2, message_type="text",
        text="Crée le produit Riz, prix de vente 99000, prix d'achat 80000, stock 3, unité sac", db=db,
    )
    mo.process_incoming_message(channel="whatsapp", sender_id=PATRON_2, message_type="text", text="oui", db=db)

    stock_1 = mo.process_incoming_message(
        channel="whatsapp", sender_id=PATRON_1, message_type="text", text="mon stock", db=db,
    )
    stock_2 = mo.process_incoming_message(
        channel="whatsapp", sender_id=PATRON_2, message_type="text", text="mon stock", db=db,
    )

    # Chacun ne voit qu'UNE seule ligne "Riz" (le sien), jamais deux.
    assert stock_1["reply_text"].count("Riz") == 1
    assert stock_2["reply_text"].count("Riz") == 1

    # Patron 1 a mis 10 en stock initial, Patron 2 en a mis 3 — les
    # deux tableaux doivent être différents l'un de l'autre.
    assert stock_1["reply_text"] != stock_2["reply_text"]
    ligne_riz_1 = [l for l in stock_1["reply_text"].split("\n") if "Riz" in l][0]
    ligne_riz_2 = [l for l in stock_2["reply_text"].split("\n") if "Riz" in l][0]
    assert "10" in ligne_riz_1
    assert "3" in ligne_riz_2
    assert ligne_riz_1 != ligne_riz_2

    pending_actions.pop(PATRON_1, None)
    pending_actions.pop(PATRON_2, None)
