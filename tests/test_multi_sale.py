"""
Vente multi-produits : ventilation des montants, coercition d'intention,
résumé de confirmation et payload de persistance.
"""
from types import SimpleNamespace

from app.agents.intent_agent import (
    AIIntent,
    AIIntentItem,
    _to_business_action,
    count_enumerated_products,
)
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


def test_compte_5_produits_enumeres_message_fatima():
    """
    Reproduit le vocal de la vente à Fatima (2 sacs de maïs, 2 cartons
    de tomates, 2 sacs de riz, 4 sacs de riz parfumé, 6 sacs de riz
    long) : le garde-fou doit détecter les 5 groupes quantité+unité,
    même avec trois occurrences distinctes de "riz".
    """
    text = (
        "Vends deux sacs de maïs, deux cartons de tomates, deux sacs de "
        "riz, quatre sacs de riz parfumé et six sacs de riz long à Fatima."
    )
    assert count_enumerated_products(text) == 5


def test_avertissement_affiche_si_items_incomplets():
    """
    Si l'IA n'a retenu que 2 items sur les 5 énumérés dans le texte
    d'origine, build_operation_summary doit afficher un avertissement
    au commerçant plutôt que de confirmer silencieusement une vente
    tronquée.
    """
    action = {
        "type": "sale",
        "customer": "Fatima",
        "amount": 415000,
        "payment": "cash",
        "remaining": 0,
        "items": [
            {"product": "Maïs", "unit": "Sac", "quantity": 3, "amount": 375000},
            {"product": "Tomates", "unit": "Carton", "quantity": 2, "amount": 40000},
        ],
        "_original_text": (
            "Vends deux sacs de maïs, deux cartons de tomates, deux sacs "
            "de riz, quatre sacs de riz parfumé et six sacs de riz long "
            "à Fatima."
        ),
    }
    summary = build_operation_summary(action, confirm=True)
    assert "5 article(s)" in summary
    assert "seulement 2 ont été compris" in summary


def test_pas_avertissement_si_items_complets():
    """
    Avec les 5 items correctement retenus, aucun avertissement ne doit
    apparaître (pas de faux positif qui fatiguerait le commerçant).
    """
    action = {
        "type": "sale",
        "customer": "Fatima",
        "amount": 415000,
        "payment": "cash",
        "remaining": 0,
        "items": [
            {"product": "Maïs", "unit": "Sac", "quantity": 2, "amount": None},
            {"product": "Tomates", "unit": "Carton", "quantity": 2, "amount": None},
            {"product": "Riz", "unit": "Sac", "quantity": 2, "amount": None},
            {"product": "Riz parfumé", "unit": "Sac", "quantity": 4, "amount": None},
            {"product": "Riz long", "unit": "Sac", "quantity": 6, "amount": None},
        ],
        "_original_text": (
            "Vends deux sacs de maïs, deux cartons de tomates, deux sacs "
            "de riz, quatre sacs de riz parfumé et six sacs de riz long "
            "à Fatima."
        ),
    }
    summary = build_operation_summary(action, confirm=True)
    assert "⚠️" not in summary

