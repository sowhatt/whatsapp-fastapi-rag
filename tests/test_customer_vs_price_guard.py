"""
Garde-fou déterministe : un nom de client qui est en réalité un
nombre écrit en toutes lettres (confusion « à cinq mille à Awa »)
doit être invalidé, jamais enregistré comme nom de client.
"""
from app.agents.intent_agent import AIIntent, _to_business_action


def test_customer_numerique_est_invalide_et_devient_amount():
    parsed = AIIntent(
        type="sale",
        customer="Cinq mille",
        product="riz",
        unit="sac",
        quantity=2,
        amount=None,
        payment="unknown",
        confidence=0.8,
    )
    action = _to_business_action(parsed)
    assert action is not None
    assert action["customer"] is None
    assert action["amount"] == 5000
    assert "customer" in action["_missing_fields"]


def test_vrai_nom_de_client_nest_pas_touche():
    parsed = AIIntent(
        type="sale",
        customer="Awa",
        product="riz",
        unit="sac",
        quantity=2,
        amount=100000,
        payment="cash",
        confidence=0.9,
    )
    action = _to_business_action(parsed)
    assert action is not None
    assert action["customer"] == "Awa"
    assert action["amount"] == 100000


def test_amount_deja_present_nest_pas_ecrase_par_le_faux_client():
    parsed = AIIntent(
        type="sale",
        customer="Trois mille",
        product="riz",
        unit="sac",
        quantity=2,
        amount=100000,
        payment="cash",
        confidence=0.8,
    )
    action = _to_business_action(parsed)
    assert action is not None
    assert action["customer"] is None
    assert action["amount"] == 100000
    assert "customer" in action["_missing_fields"]


def test_fournisseur_numerique_est_aussi_invalide():
    parsed = AIIntent(
        type="purchase",
        supplier="Dix mille",
        product="riz",
        unit="sac",
        quantity=2,
        amount=None,
        payment="unknown",
        confidence=0.8,
    )
    action = _to_business_action(parsed)
    assert action is not None
    assert action["supplier"] is None
    assert action["amount"] == 10000
