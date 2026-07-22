"""
Vente multi-produits : ventilation des montants, coercition d'intention,
résumé de confirmation et payload de persistance.
"""
from types import SimpleNamespace

from app.agents.intent_agent import AIIntent, AIIntentItem, _to_business_action
from app.services.message_orchestrator import build_operation_summary
from app.services.sales_service import (
    ResolvedSale,
    ResolvedSaleLine,
    _allocate_total,
    build_sale_create_payload,
)


def test_allocate_total_prorata_exact():
    assert _allocate_total([100, 300], 400) == [100, 300]


def test_allocate_total_corrige_les_arrondis():
    allocated = _allocate_total([1, 1, 1], 100)
    assert sum(allocated) == 100
    assert allocated == [33, 33, 34]


def test_allocate_total_sans_prix_catalogue():
    assert _allocate_total([0, 0], 100) == [50, 50]


def test_intention_multi_items_montants_par_produit():
    parsed = AIIntent(
        type="sale",
        customer="Awa",
        product="riz",
        unit="sac",
        quantity=2,
        payment="cash",
        confidence=0.9,
        items=[
            AIIntentItem(product="riz", unit="sac", quantity=2, amount=100000),
            AIIntentItem(product="tomate", unit="carton", quantity=3, amount=50000),
        ],
    )
    action = _to_business_action(parsed)
    assert action is not None
    assert len(action["items"]) == 2
    assert action["amount"] == 150000
    assert action["_missing_fields"] == []


def test_intention_multi_items_montant_global():
    parsed = AIIntent(
        type="sale",
        customer="Awa",
        amount=150000,
        payment="credit",
        confidence=0.9,
        items=[
            AIIntentItem(product="riz", unit="sac", quantity=2),
            AIIntentItem(product="tomate", unit="carton", quantity=3),
        ],
    )
    action = _to_business_action(parsed)
    assert action is not None
    assert action["product"] == "Riz"
    assert action["quantity"] == 2
    assert action["items"][1]["amount"] is None
    assert action["_missing_fields"] == []


def test_resume_multi_items():
    action = {
        "type": "sale",
        "customer": "Awa",
        "amount": 150000,
        "payment": "cash",
        "remaining": 0,
        "items": [
            {"product": "Riz", "unit": "Sac", "quantity": 2, "amount": 100000},
            {"product": "Tomate", "unit": "Carton", "quantity": 3, "amount": 50000},
        ],
    }
    summary = build_operation_summary(action, confirm=True)
    assert "2 sac de riz" in summary
    assert "3 carton de tomate" in summary
    assert "Montant total" in summary
    assert "Confirmer ?" in summary


def test_payload_multi_lignes():
    riz = SimpleNamespace(id=1, price=50000)
    tomate = SimpleNamespace(id=2, price=20000)
    resolved = ResolvedSale(
        customer=SimpleNamespace(id=7),
        product=riz,
        quantity=2,
        total_amount=150000,
        paid_amount=150000,
        remaining_amount=0,
        payment_channel="cash",
        lines=[
            ResolvedSaleLine(product=riz, quantity=2, line_total=100000),
            ResolvedSaleLine(product=tomate, quantity=3, line_total=50000),
        ],
    )
    payload = build_sale_create_payload(resolved)
    assert len(payload.items) == 2
    assert payload.items[0].line_total == 100000
    assert payload.items[1].unit_price == round(50000 / 3)
    assert sum(item.line_total for item in payload.items) == 150000


def test_payload_mono_ligne_conserve_le_montant_annonce():
    riz = SimpleNamespace(id=1, price=999999)
    resolved = ResolvedSale(
        customer=SimpleNamespace(id=7),
        product=riz,
        quantity=2,
        total_amount=250000,
        paid_amount=250000,
        remaining_amount=0,
        payment_channel="cash",
    )
    payload = build_sale_create_payload(resolved)
    assert len(payload.items) == 1
    assert payload.items[0].line_total == 250000
