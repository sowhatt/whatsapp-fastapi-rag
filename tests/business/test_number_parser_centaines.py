"""Régression : centaines suivies de « mille » (bug 50 100 au lieu de 150 000)."""
from app.business.parser.number_parser import parse_french_number


def test_cent_cinquante_mille():
    assert parse_french_number("cent cinquante mille") == 150000


def test_deux_cent_cinquante_mille():
    assert parse_french_number("deux cent cinquante mille") == 250000


def test_cent_mille():
    assert parse_french_number("cent mille") == 100000


def test_trois_cent_vingt_mille():
    assert parse_french_number("trois cent vingt mille") == 320000


def test_cinquante_mille_cinq_cents():
    assert parse_french_number("cinquante mille cinq cents") == 50500


def test_regressions_existantes():
    assert parse_french_number("quatre-vingt-trois mille") == 83000
    assert parse_french_number("deux cents") == 200
    assert parse_french_number("mille") == 1000
