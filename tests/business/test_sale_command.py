from decimal import Decimal

from app.business.commands import SaleCommand


def test_sale_command_uses_fcfa_as_default_currency():
    command = SaleCommand()

    assert command.currency == "FCFA"


def test_sale_command_calculates_total():
    command = SaleCommand(
        quantity=Decimal("2"),
        product="bouteilles d'eau",
        unit_price=Decimal("500"),
    )

    assert command.total == Decimal("1000")


def test_sale_command_total_is_none_without_quantity():
    command = SaleCommand(
        product="bouteilles d'eau",
        unit_price=Decimal("500"),
    )

    assert command.total is None


def test_sale_command_total_is_none_without_unit_price():
    command = SaleCommand(
        quantity=Decimal("2"),
        product="bouteilles d'eau",
    )

    assert command.total is None


def test_sale_command_is_complete():
    command = SaleCommand(
        quantity=Decimal("2"),
        product="bouteilles d'eau",
        unit_price=Decimal("500"),
    )

    assert command.is_complete is True
    assert command.missing_fields == ()


def test_sale_command_detects_missing_fields():
    command = SaleCommand(
        product="bouteilles d'eau",
    )

    assert command.is_complete is False
    assert command.missing_fields == (
        "quantity",
        "unit_price",
    )


def test_sale_command_rejects_blank_product():
    command = SaleCommand(
        quantity=Decimal("2"),
        product="   ",
        unit_price=Decimal("500"),
    )

    assert command.is_complete is False
    assert command.missing_fields == ("product",)


def test_sale_command_accepts_free_sale():
    command = SaleCommand(
        quantity=Decimal("1"),
        product="échantillon",
        unit_price=Decimal("0"),
    )

    assert command.is_complete is True
    assert command.total == Decimal("0")
