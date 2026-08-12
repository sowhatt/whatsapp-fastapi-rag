"""
Une confirmation de création de client/fournisseur en attente
("veux-tu créer ce fournisseur ?") ne doit pas bloquer indéfiniment
si le commerçant corrige en redisant toute l'opération (ex. le bon
nom de fournisseur cette fois) — elle doit remplacer proprement
l'ancienne opération, pas relancer sur l'ancien nom pour toujours.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, _to_business_action
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.services import message_orchestrator as mo
from app.services.merchant_service import get_or_create_merchant

SENDER = "correction-pytest"


def _fresh_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    merchant = get_or_create_merchant(SENDER, db)
    set_current_merchant(db, merchant.id)
    return db


def test_reformulation_complete_remplace_le_mauvais_fournisseur():
    db = _fresh_db()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    result = send("Achat cinq sacs de riz cassé, prix unitaire 45000 chez Sowo", fake=lambda t, d: _to_business_action(
        AIIntent(type="purchase", supplier="Sowo", product="Riz cassé", unit="Sac", quantity=5, amount=225000, confidence=0.9)
    ))
    assert "Sowo" in result["reply_text"]

    result = send("Achat cinq sacs de riz cassé, prix unitaire 45000, chez Soglo", fake=lambda t, d: _to_business_action(
        AIIntent(type="purchase", supplier="Soglo", product="Riz cassé", unit="Sac", quantity=5, amount=225000, confidence=0.9)
    ))
    assert "Soglo" in result["reply_text"]
    assert "Sowo" not in result["reply_text"]


def test_charabia_relance_toujours_sans_rien_perdre():
    db = _fresh_db()

    def send(text, fake=None):
        if fake:
            mo.detect_intent = fake
        return mo.process_incoming_message(channel="whatsapp", sender_id=SENDER, message_type="text", text=text, db=db)

    send("Achat cinq sacs de riz cassé, prix unitaire 45000 chez Sowo", fake=lambda t, d: _to_business_action(
        AIIntent(type="purchase", supplier="Sowo", product="Riz cassé", unit="Sac", quantity=5, amount=225000, confidence=0.9)
    ))
    result = send("miaou")
    assert "Sowo" in result["reply_text"]
    assert "Je n'ai pas compris" in result["reply_text"]
