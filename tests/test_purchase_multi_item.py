"""
Achat multi-produits : mêmes garanties que la vente multi-produits
(ventilation, cohérence des montants) et correctif d'un bug préexistant
(le paiement annoncé dans la phrase n'était jamais capté pour un achat,
contrairement à une vente).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.intent_agent import AIIntent, AIIntentItem, _to_business_action
from app.agents.validation_agent import validate_before_confirmation
from app.db.base import Base
from app.models.product import Product
from app.models.supplier import Supplier
from app.services import message_orchestrator as mo
from app.services.purchases_service import (
    build_purchase_create_payload,
    resolve_purchase_intent,
)
from app.state.pending_actions import pending_actions

SENDER = "22990000005"


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


def test_paiement_capte_directement_pour_un_achat():
    parsed = AIIntent(
        type="purchase", supplier="Soglo", product="Riz", unit="Sac",
        quantity=5, amount=250000, payment="cash", confidence=0.9,
    )
    action = _to_business_action(parsed)
    assert action["payment"] == "cash"


def test_coercition_achat_multi_items_montant_global():
    parsed = AIIntent(
        type="purchase", supplier="Soglo", amount=250000, payment="cash", confidence=0.9,
        items=[
            AIIntentItem(product="riz", unit="sac", quantity=5),
            AIIntentItem(product="mil", unit="sac", quantity=3),
        ],
    )
    action = _to_business_action(parsed)
    assert action is not None
    assert len(action["items"]) == 2
    assert action["amount"] == 250000
    assert action["_missing_fields"] == []


def test_coercition_achat_multi_items_prix_detailles():
    parsed = AIIntent(
        type="purchase", supplier="Soglo", payment="cash", confidence=0.9,
        items=[
            AIIntentItem(product="riz", unit="sac", quantity=5, amount=200000),
            AIIntentItem(product="mil", unit="sac", quantity=3, amount=60000),
        ],
    )
    action = _to_business_action(parsed)
    assert action["amount"] == 260000
    assert action["_missing_fields"] == []


def test_resolution_achat_multi_lignes_montant_global(db):
    db.add(Supplier(name="Soglo", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100))
    db.add(Product(name="Mil", unit="Sac", price=30000, purchase_price=20000, stock=50))
    db.commit()
    intent = {
        "type": "purchase", "supplier": "Soglo", "payment": "cash", "amount": 250000,
        "items": [
            {"product": "Riz", "quantity": 5, "amount": None},
            {"product": "Mil", "quantity": 3, "amount": None},
        ],
    }
    resolved = resolve_purchase_intent(intent, db)
    assert len(resolved.lines) == 2
    assert sum(line.line_total for line in resolved.lines) == 250000
    payload = build_purchase_create_payload(resolved)
    assert len(payload.items) == 2


def test_resolution_achat_incoherence_entre_lignes_et_total(db):
    from app.services.purchases_service import PurchaseServiceError

    db.add(Supplier(name="Soglo", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100))
    db.add(Product(name="Mil", unit="Sac", price=30000, purchase_price=20000, stock=50))
    db.commit()
    intent = {
        "type": "purchase", "supplier": "Soglo", "payment": "cash", "amount": 300000,
        "items": [
            {"product": "Riz", "quantity": 5, "amount": 200000},
            {"product": "Mil", "quantity": 3, "amount": 60000},
        ],
    }
    with pytest.raises(PurchaseServiceError, match="ne correspondent pas"):
        resolve_purchase_intent(intent, db)


def test_validation_bloque_incoherence_achat_avant_confirmation():
    action = {
        "type": "purchase", "amount": 300000,
        "items": [
            {"product": "Riz", "quantity": 5, "amount": 200000},
            {"product": "Mil", "quantity": 3, "amount": 60000},
        ],
    }
    message = validate_before_confirmation(action, db=None)
    assert message is not None
    assert "260 000" in message
    assert "300 000" in message
    assert action["_awaiting_field"] == "amount"


def test_flux_complet_achat_multi_produits(db, monkeypatch):
    db.add(Supplier(name="Soglo", debt=0))
    db.add(Product(name="Riz", unit="Sac", price=50000, purchase_price=40000, stock=100))
    db.add(Product(name="Mil", unit="Sac", price=30000, purchase_price=20000, stock=50))
    db.commit()

    fake_action = {
        "type": "purchase", "supplier": "Soglo", "payment": "cash", "amount": 250000,
        "product": "Riz", "unit": "Sac", "quantity": 5,
        "items": [
            {"product": "Riz", "unit": "Sac", "quantity": 5, "amount": None},
            {"product": "Mil", "unit": "Sac", "quantity": 3, "amount": None},
        ],
        "_missing_fields": [],
    }
    monkeypatch.setattr(mo, "detect_intent", lambda text, db: dict(fake_action))

    result = mo.process_incoming_message(
        channel="whatsapp", sender_id=SENDER, message_type="text",
        text="Achat 5 sacs de riz et 3 sacs de mil chez Soglo pour 250000 cash", db=db,
    )
    assert "Confirmer" in result["reply_text"]
    assert "5 sac de riz" in result["reply_text"]
    assert "3 sac de mil" in result["reply_text"]

    result2 = mo.process_incoming_message(
        channel="whatsapp", sender_id=SENDER, message_type="text", text="oui", db=db,
    )
    assert "Achat enregistré" in result2["reply_text"]

    riz = db.query(Product).filter(Product.name == "Riz").first()
    mil = db.query(Product).filter(Product.name == "Mil").first()
    assert riz.stock == 105
    assert mil.stock == 53
