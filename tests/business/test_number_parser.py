from decimal import Decimal

import pytest

from app.business.parser.number_parser import parse_french_number


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2", Decimal("2")),
        ("2,5", Decimal("2.5")),
        ("deux", Decimal("2")),
        ("vingt", Decimal("20")),
        ("vingt-cinq", Decimal("25")),
        ("cinq cents", Decimal("500")),
        ("mille", Decimal("1000")),
        ("deux mille", Decimal("2000")),
        ("deux mille cinq cents", Decimal("2500")),
        ("quatre-vingts", Decimal("80")),
        ("quatre-vingt-cinq", Decimal("85")),
    ],
)
def test_parse_french_number(text, expected):
    assert parse_french_number(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "bonjour",
        "beaucoup",
    ],
)
def test_parse_french_number_returns_none_for_invalid_text(text):
    assert parse_french_number(text) is None
