"""
Lot de validation : cohérence des montants avant confirmation,
détecteur d'anomalie de prix (seuil 20 %), avertissements dans le
résumé, et question paiement propre en vente multiple.
"""
from types import SimpleNamespace

from app.agents.intent_agent import AIIntent, AIIntentItem, _to_business_action
from app.agents.validation_agent import (
    _price_anomaly_warning,
    validate_before_confirmation,
)
from app.services.message_orchestrator import build_operation_summary


class FakeDB:
    def __init__(self, product=None):
        self._product = product

    def query(self, model):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._product


def test_incoherence_bloquee_avant_confirmation():
    action = {
        "type": "sale",
        "amount": 200000,
        "quantity": 2,
        "items": [
            {"product": "Riz", "quantity": 2, "amount": 100000},
            {"product": "Tomate", "quantity": 3, "amount": 50000},
        ],
    }
    message = validate_before_confirmation(action, db=FakeDB())
    assert message is not None
    assert "150 000" in message
    assert "200 000" in message
    assert action["_awaiting_field"] == "amount"


def test_anomalie_au_dela_de_20_pourcent():
    produit = SimpleNamespace(price=50000, unit="Sac", name="Riz")
    warning = _price_anomaly_warning("Riz", 10, 100000, FakeDB(produit))
    assert warning is not None
    assert "10 000" in warning
    assert "50 000" in warning


def test_pas_d_anomalie_dans_la_marge_de_negociation():
    produit = SimpleNamespace(price=50000, unit="Sac", name="Riz")
    assert _price_anomaly_warning("Riz", 2, 110000, FakeDB(produit)) is None


def test_resume_affiche_l_avertissement_avant_confirmer():
    action = {
        "type": "sale",
        "customer": "Awa",
        "amount": 100000,
        "payment": "cash",
        "remaining": 0,
        "quantity": 10,
        "unit": "Sac",
        "product": "Riz",
        "_price_warnings": ["⚠️ Prix inhabituel : test"],
    }
    summary = build_operation_summary(action, confirm=True)
    assert "⚠️" in summary
    assert summary.index("⚠️") < summary.index("Confirmer")


def test_paiement_hors_des_champs_manquants_en_multi():
    parsed = AIIntent(
        type="sale",
        customer="Awa",
        amount=150000,
        payment="unknown",
        confidence=0.9,
        missing_fields=["payment"],
        items=[
            AIIntentItem(product="riz", unit="sac", quantity=2),
            AIIntentItem(product="tomate", unit="carton", quantity=3),
        ],
    )
    action = _to_business_action(parsed)
    assert action is not None
    assert "payment" not in action["_missing_fields"]
