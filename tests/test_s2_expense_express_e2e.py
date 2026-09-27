import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.financial_entry import FinancialEntry
from app.models.merchant_user import MerchantUser
from app.models.shop import Shop
from app.models.shop_operation import ShopOperation
from app.models.transaction_event import TransactionEvent
from app.routers.financial_entries import (
    create_financial_entry,
    list_financial_entries,
)
from app.services import message_orchestrator as mo
from app.services.summary_service import get_period_summary_data
from app.state.pending_actions import pending_actions
from tests.conftest import with_merchant


SENDER = "s2-expense-express-e2e"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def teardown_function():
    pending_actions.pop(SENDER, None)


def send(db, text, monkeypatch=None, fake_action=None):
    if monkeypatch is not None and fake_action is not None:
        monkeypatch.setattr(
            mo,
            "detect_intent",
            lambda text, db: dict(fake_action),
        )

    return mo.process_incoming_message(
        channel="whatsapp",
        sender_id=SENDER,
        message_type="text",
        text=text,
        db=db,
    )


def test_s2_3_depense_whatsapp_et_isolation_boutique(db, monkeypatch):
    """
    S2.3

    Boutique A :
        "J'ai payé 25 000 FCFA d'électricité en espèces."
        -> confirmation
        -> oui
        -> dépense 25 000
        -> catégorie electricite
        -> cash
        -> ShopOperation Boutique A
        -> TransactionEvent -25 000

    Boutique B :
        ne doit pas voir la dépense de Boutique A.
    """

    merchant = with_merchant(db, SENDER)

    shop_a = Shop(
        merchant_id=merchant.id,
        name="Boutique A",
        code="A",
    )
    shop_b = Shop(
        merchant_id=merchant.id,
        name="Boutique B",
        code="B",
    )

    db.add_all([shop_a, shop_b])
    db.commit()

    # ---------------------------------------------------------
    # 1. Contexte Boutique A
    # ---------------------------------------------------------
    db.info["pwa_shop_id"] = shop_a.id

    expense_action = {
        "type": "expense",
        "label": "Électricité",
        "amount": 25000,
        "channel": "cash",
        "category": "electricite",
        "_missing_fields": [],
    }

    result = send(
        db,
        "J'ai payé 25 000 FCFA d'électricité en espèces",
        monkeypatch,
        expense_action,
    )

    assert result["status"] == "reply"
    assert "Dépense" in result["reply_text"]
    assert "25" in result["reply_text"]
    assert "Confirmer" in result["reply_text"]

    # Rien ne doit être persisté avant confirmation.
    assert db.query(FinancialEntry).count() == 0

    # ---------------------------------------------------------
    # 2. Confirmation
    # ---------------------------------------------------------
    result = send(db, "oui")

    assert result["status"] == "reply"
    assert "Dépense enregistrée" in result["reply_text"]

    entry = db.query(FinancialEntry).one()

    assert entry.entry_type == "expense"
    assert entry.amount == 25000
    assert entry.channel == "cash"
    assert entry.category == "electricite"
    assert entry.label == "Électricité"
    assert entry.origin_kind == "manual"

    # ---------------------------------------------------------
    # 3. La dépense doit appartenir à Boutique A
    # ---------------------------------------------------------
    operation = (
        db.query(ShopOperation)
        .filter(
            ShopOperation.entity_type == "financial_entry",
            ShopOperation.entity_id == entry.id,
        )
        .one()
    )

    assert operation.merchant_id == merchant.id
    assert operation.shop_id == shop_a.id

    # ---------------------------------------------------------
    # 4. L'événement financier doit être négatif
    # ---------------------------------------------------------
    event = (
        db.query(TransactionEvent)
        .filter(
            TransactionEvent.entity_type == "financial_entry",
            TransactionEvent.entity_id == entry.id,
        )
        .one()
    )

    assert event.event_type == "expense"
    assert event.amount_signed == -25000

    # ---------------------------------------------------------
    # 5. Boutique A voit sa dépense
    # ---------------------------------------------------------
    db.info["pwa_shop_id"] = shop_a.id

    entries_a = list_financial_entries(db)

    assert len(entries_a) == 1
    assert entries_a[0].id == entry.id
    assert entries_a[0].amount == 25000

    # ---------------------------------------------------------
    # 6. Boutique B ne doit PAS voir la dépense de A
    # ---------------------------------------------------------
    db.info["pwa_shop_id"] = shop_b.id

    entries_b = list_financial_entries(db)

    assert entries_b == []

    # ---------------------------------------------------------
    # 7. Le bilan Boutique B ne doit pas intégrer la dépense A
    # ---------------------------------------------------------
    summary_b = get_period_summary_data(db, period="today")

    assert summary_b["expenses_total"] == 0

    # ---------------------------------------------------------
    # 8. Boutique A retrouve 25 000 de charges
    # ---------------------------------------------------------
    db.info["pwa_shop_id"] = shop_a.id

    summary_a = get_period_summary_data(db, period="today")

    assert summary_a["expenses_total"] == 25000
    assert summary_a["expenses_by_category"].get("electricite") == 25000
