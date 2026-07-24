"""
Le bilan doit rester consultable pendant un workflow en attente
(exemple : question de paiement en cours), sans jamais être
détourné par une réponse de champ légitime au chiffre "8".
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.business.assistant import is_summary_keyword_request
from app.db.base import Base
from app.services import message_orchestrator as mo
from app.state.pending_actions import pending_actions

SENDER = "22990000001"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def teardown_function():
    pending_actions.pop(SENDER, None)


def test_bilan_consultable_pendant_question_paiement(db):
    mo.set_pending_action(
        SENDER,
        {
            "type": "sale",
            "customer": "Awa",
            "product": "Riz",
            "unit": "Sac",
            "quantity": 1,
            "amount": 5000,
            "_awaiting": "operation_payment",
        },
    )
    result = mo.process_incoming_message(
        channel="whatsapp",
        sender_id=SENDER,
        message_type="text",
        text="résumé du jour",
        db=db,
    )
    assert result["status"] == "reply"
    assert "Bilan du jour" in result["reply_text"]
    assert mo.get_pending_action(SENDER) is not None
    assert mo.get_pending_action(SENDER)["_awaiting"] == "operation_payment"


def test_chiffre_menu_ne_declenche_pas_le_bilan_en_plein_workflow():
    assert is_summary_keyword_request("8") is False
