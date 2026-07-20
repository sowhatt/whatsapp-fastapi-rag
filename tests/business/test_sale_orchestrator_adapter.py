from decimal import Decimal

from app.business.commands import SaleCommand
from app.services.message_orchestrator import _sale_command_to_action


def test_converts_bottle_sale_to_orchestrator_action():
    command = SaleCommand(
        quantity=Decimal("2"),
        product="bouteilles d'eau",
        unit_price=Decimal("500"),
    )

    action = _sale_command_to_action(command)

    assert action["type"] == "sale"
    assert action["quantity"] == 2
    assert action["unit"] == "Bouteille"
    assert action["product"] == "eau"
    assert action["amount"] == 1000
    assert action["customer"] is None
    assert action["payment"] == "unknown"
    assert action["_missing_fields"] == ["customer"]


def test_converts_bag_sale():
    command = SaleCommand(
        quantity=Decimal("3"),
        product="sacs de riz",
        unit_price=Decimal("15000"),
        customer="Awa",
        payment_method="cash",
    )

    action = _sale_command_to_action(command)

    assert action["quantity"] == 3
    assert action["unit"] == "Sac"
    assert action["product"] == "riz"
    assert action["amount"] == 45000
    assert action["customer"] == "Awa"
    assert action["payment"] == "cash"
    assert action["_missing_fields"] == []


def test_marks_amount_as_missing_when_price_is_absent():
    command = SaleCommand(
        quantity=Decimal("10"),
        product="kg de sucre",
    )

    action = _sale_command_to_action(command)

    assert action["unit"] == "Kg"
    assert action["product"] == "sucre"
    assert action["amount"] is None
    assert action["_missing_fields"] == ["customer", "amount"]
