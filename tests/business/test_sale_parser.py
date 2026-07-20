from decimal import Decimal

import pytest

from app.business.parser.sale_parser import parse_sale


@pytest.mark.parametrize(
    (
        "text",
        "expected_quantity",
        "expected_product",
        "expected_price",
    ),
    [
        (
            "Vends deux bouteilles d'eau à cinq cents francs",
            Decimal("2"),
            "bouteilles d'eau",
            Decimal("500"),
        ),
        (
            "Vente de 3 sacs de riz à 15000 FCFA",
            Decimal("3"),
            "sacs de riz",
            Decimal("15000"),
        ),
        (
            "Vente 10 kg de sucre",
            Decimal("10"),
            "kg de sucre",
            None,
        ),
        (
            "Vends une bouteille d'huile pour 750 francs",
            Decimal("1"),
            "bouteille d'huile",
            Decimal("750"),
        ),
        (
            "vendu quatre cartons de lait à deux mille cinq cents",
            Decimal("4"),
            "cartons de lait",
            Decimal("2500"),
        ),
    ],
)
def test_parse_sale(
    text,
    expected_quantity,
    expected_product,
    expected_price,
):
    command = parse_sale(text)

    assert command is not None
    assert command.quantity == expected_quantity
    assert command.product == expected_product
    assert command.unit_price == expected_price


def test_parse_sale_calculates_total():
    command = parse_sale(
        "Vends deux bouteilles d'eau à cinq cents francs",
    )

    assert command is not None
    assert command.total == Decimal("1000")
    assert command.is_complete is True


def test_parse_sale_detects_missing_price():
    command = parse_sale(
        "Vente 3 sacs de riz",
    )

    assert command is not None
    assert command.is_complete is False
    assert command.missing_fields == ("unit_price",)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "bonjour",
        "combien coûte le riz",
        "vente",
    ],
)
def test_parse_sale_returns_none_for_invalid_text(text):
    assert parse_sale(text) is None
