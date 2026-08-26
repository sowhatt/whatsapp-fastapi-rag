from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

from fastapi import HTTPException

from app.agents.intent_agent import (
    AIIntent,
    _to_business_action,
)
from app.db.base import Base
from app.db.tenant import set_current_merchant
from app.models.customer import Customer
from app.models.product import Product
from app.models.purchase import Purchase
from app.models.sale import Sale
from app.models.supplier import Supplier
from app.services import message_orchestrator as mo
from app.services.merchant_service import (
    get_or_create_merchant,
)
from app.state.pending_actions import pending_actions


def fresh_db(sender):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    merchant = get_or_create_merchant(
        sender,
        db,
    )
    set_current_merchant(
        db,
        merchant.id,
    )

    return db


def prepare_sale_catalog(db):
    customer = Customer(
        name="Awa",
        debt=0,
    )
    product = Product(
        name="Riz",
        unit="Sac",
        price=50000,
        purchase_price=40000,
        stock=50,
        initial_stock=50,
    )

    db.add_all([customer, product])
    db.commit()

    return customer, product


def sale_intent():
    return _to_business_action(
        AIIntent(
            type="sale",
            customer="Awa",
            product="Riz",
            unit="Sac",
            quantity=2,
            amount=100000,
            payment="cash",
            confidence=0.99,
        )
    )


def send(db, sender, text, fake=None):
    if fake is not None:
        mo.detect_intent = fake

    return mo.process_incoming_message(
        channel="whatsapp",
        sender_id=sender,
        message_type="text",
        text=text,
        db=db,
    )


def test_initial_sale_message_never_writes():
    sender = "confirm-sale-initial"
    pending_actions.pop(sender, None)

    db = fresh_db(sender)
    _, product = prepare_sale_catalog(db)

    result = send(
        db,
        sender,
        "Vends deux sacs de riz à Awa cash",
        fake=lambda text, session: sale_intent(),
    )

    assert "Confirmer" in result["reply_text"]
    assert db.query(Sale).count() == 0

    db.refresh(product)
    assert product.stock == 50


def test_only_explicit_yes_creates_sale_once():
    sender = "confirm-sale-once"
    pending_actions.pop(sender, None)

    db = fresh_db(sender)
    _, product = prepare_sale_catalog(db)

    send(
        db,
        sender,
        "Vends deux sacs de riz à Awa cash",
        fake=lambda text, session: sale_intent(),
    )

    assert db.query(Sale).count() == 0

    result = send(
        db,
        sender,
        "oui",
    )

    assert "Vente enregistrée" in result["reply_text"]
    assert db.query(Sale).count() == 1

    db.refresh(product)
    assert product.stock == 48

    duplicate = send(
        db,
        sender,
        "oui",
    )

    assert "Aucune action en attente" in (
        duplicate["reply_text"]
    )
    assert db.query(Sale).count() == 1


def test_non_cancels_pending_sale_without_write():
    sender = "confirm-sale-no"
    pending_actions.pop(sender, None)

    db = fresh_db(sender)
    _, product = prepare_sale_catalog(db)

    send(
        db,
        sender,
        "Vends deux sacs de riz à Awa cash",
        fake=lambda text, session: sale_intent(),
    )

    result = send(
        db,
        sender,
        "non",
    )

    assert "annul" in result["reply_text"].lower()
    assert db.query(Sale).count() == 0

    db.refresh(product)
    assert product.stock == 50


def test_pending_confirmation_is_isolated_by_sender():
    sender_a = "confirm-isolation-a"
    sender_b = "confirm-isolation-b"

    pending_actions.pop(sender_a, None)
    pending_actions.pop(sender_b, None)

    db_a = fresh_db(sender_a)
    prepare_sale_catalog(db_a)

    send(
        db_a,
        sender_a,
        "Vends deux sacs de riz à Awa cash",
        fake=lambda text, session: sale_intent(),
    )

    db_b = fresh_db(sender_b)

    result_b = send(
        db_b,
        sender_b,
        "oui",
    )

    assert "Aucune action en attente" in (
        result_b["reply_text"]
    )
    assert db_b.query(Sale).count() == 0
    assert db_a.query(Sale).count() == 0


def test_direct_execution_without_marker_is_blocked():
    sender = "confirm-direct-guard"
    pending_actions.pop(sender, None)

    db = fresh_db(sender)
    prepare_sale_catalog(db)

    action = sale_intent()
    action.pop(
        mo.CONFIRMATION_STATE_KEY,
        None,
    )

    with pytest.raises(HTTPException) as exc_info:
        mo.execute_confirmed_action(
            action,
            db,
        )

    assert exc_info.value.status_code == 409
    assert db.query(Sale).count() == 0


def test_initial_purchase_message_never_writes():
    sender = "confirm-purchase-initial"
    pending_actions.pop(sender, None)

    db = fresh_db(sender)

    supplier = Supplier(
        name="Soglo",
        debt=0,
    )
    product = Product(
        name="Riz",
        unit="Sac",
        price=60000,
        purchase_price=50000,
        stock=10,
        initial_stock=10,
    )

    db.add_all([supplier, product])
    db.commit()

    action = _to_business_action(
        AIIntent(
            type="purchase",
            supplier="Soglo",
            product="Riz",
            unit="Sac",
            quantity=10,
            amount=500000,
            payment="cash",
            confidence=0.99,
        )
    )

    result = send(
        db,
        sender,
        (
            "J'ai acheté dix sacs de riz "
            "chez Soglo cash"
        ),
        fake=lambda text, session: action,
    )

    assert "Confirmer" in result["reply_text"]
    assert db.query(Purchase).count() == 0

    db.refresh(product)
    assert product.stock == 10
