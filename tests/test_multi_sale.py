"""
Vente multi-produits : ventilation des montants, coercition d'intention,
résumé de confirmation et payload de persistance.
"""
from types import SimpleNamespace

from app.agents.intent_agent import (
    AIIntent,
    AIIntentItem,
    _extract_ordered_quantities,
    _realign_item_quantities,
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
    text = (
        "Vends deux sacs de mais, deux cartons de tomates, deux sacs de "
        "riz, quatre sacs de riz parfume et six sacs de riz long a Fatima."
    )
    assert count_enumerated_products(text) == 5


def test_avertissement_affiche_si_items_incomplets():
    action = {
        "type": "sale",
        "customer": "Fatima",
        "amount": 415000,
        "payment": "cash",
        "remaining": 0,
        "items": [
            {"product": "Mais", "unit": "Sac", "quantity": 3, "amount": 375000},
            {"product": "Tomates", "unit": "Carton", "quantity": 2, "amount": 40000},
        ],
        "_original_text": (
            "Vends deux sacs de mais, deux cartons de tomates, deux sacs "
            "de riz, quatre sacs de riz parfume et six sacs de riz long "
            "a Fatima."
        ),
    }
    summary = build_operation_summary(action, confirm=True)
    assert "5 article(s)" in summary
    assert "seulement 2 ont" in summary


def test_pas_avertissement_si_items_complets():
    action = {
        "type": "sale",
        "customer": "Fatima",
        "amount": 415000,
        "payment": "cash",
        "remaining": 0,
        "items": [
            {"product": "Mais", "unit": "Sac", "quantity": 2, "amount": None},
            {"product": "Tomates", "unit": "Carton", "quantity": 2, "amount": None},
            {"product": "Riz", "unit": "Sac", "quantity": 2, "amount": None},
            {"product": "Riz parfume", "unit": "Sac", "quantity": 4, "amount": None},
            {"product": "Riz long", "unit": "Sac", "quantity": 6, "amount": None},
        ],
        "_original_text": (
            "Vends deux sacs de mais, deux cartons de tomates, deux sacs "
            "de riz, quatre sacs de riz parfume et six sacs de riz long "
            "a Fatima."
        ),
    }
    summary = build_operation_summary(action, confirm=True)
    assert "avertissement" not in summary.lower() and "seulement" not in summary


def test_extrait_les_quantites_dans_l_ordre_message_fatima_v2():
    """
    Reproduit le 2e vocal Fatima (2 mais, 2 tomates, 2 riz, 6 riz
    parfume, 5 riz long) : la regex doit extraire les quantites dans
    le bon ordre, y compris "six" et "cinq" en fin d'enumeration.
    """
    text = (
        "Vends deux sacs de mais, deux cartons de tomates, deux sacs "
        "de riz, six sacs de riz parfume, cinq sacs de riz long a "
        "Fatima."
    )
    assert _extract_ordered_quantities(text) == [2, 2, 2, 6, 5]


def test_realigne_quantites_hallucinees_par_le_llm():
    """
    Reproduit exactement le bug observe en prod : le LLM renvoie 5
    items (bon compte) mais avec les 2 dernieres quantites fausses
    (4 au lieu de 6, 6 au lieu de 5 -- un "4" jamais prononce). Le
    realignement deterministe doit corriger sans casser les 3
    premiers items, deja corrects.
    """
    text = (
        "Vends deux sacs de mais, deux cartons de tomates, deux sacs "
        "de riz, six sacs de riz parfume, cinq sacs de riz long a "
        "Fatima."
    )
    items_buggy = [
        {"product": "Mais", "unit": "Sac", "quantity": 2, "amount": None},
        {"product": "Tomates", "unit": "Carton", "quantity": 2, "amount": None},
        {"product": "Riz", "unit": "Sac", "quantity": 2, "amount": None},
        {"product": "Riz parfume", "unit": "Sac", "quantity": 4, "amount": None},
        {"product": "Riz long", "unit": "Sac", "quantity": 6, "amount": None},
    ]

    corrected = _realign_item_quantities(text, items_buggy)

    assert [item["quantity"] for item in corrected] == [2, 2, 2, 6, 5]


def test_ne_realigne_pas_si_le_compte_ne_correspond_pas():
    """
    Filet de securite du realignement lui-meme : si le nombre de
    quantites detectees par regex ne correspond pas au nombre
    d'items, on ne touche a rien plutot que de risquer un mauvais
    alignement positionnel.
    """
    text = "Vends deux sacs de riz et trois cartons de tomates a Awa."
    items = [
        {"product": "Riz", "unit": "Sac", "quantity": 99, "amount": None},
        {"product": "Tomates", "unit": "Carton", "quantity": 99, "amount": None},
        {"product": "Huile", "unit": "Bidon", "quantity": 99, "amount": None},
    ]

    corrected = _realign_item_quantities(text, items)

    assert [item["quantity"] for item in corrected] == [99, 99, 99]

