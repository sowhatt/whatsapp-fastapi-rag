from types import SimpleNamespace
from unittest.mock import patch

from app.schemas.smart_catalog import SmartCatalogCandidate
from app.services.smart_catalog_service import (
    analyze_catalog_image,
    find_catalog_matches,
)


def test_find_catalog_matches_returns_close_existing_product():
    candidates = [
        SmartCatalogCandidate(
            name="Riz parfume 25 kg",
            packaging="25 kg",
            unit="sac",
            confidence=0.94,
        )
    ]
    products = [
        SimpleNamespace(id=10, name="Riz parfumé 25 kg"),
        SimpleNamespace(id=11, name="Huile végétale 1L"),
    ]

    matches = find_catalog_matches(candidates, products, threshold=0.70)

    assert 0 in matches
    assert matches[0][0].product_id == 10
    assert matches[0][0].score >= 0.70


def test_find_catalog_matches_ignores_unrelated_products():
    candidates = [SmartCatalogCandidate(name="Coca Cola 50 cl", confidence=0.9)]
    products = [SimpleNamespace(id=20, name="Riz parfumé 25 kg")]

    matches = find_catalog_matches(candidates, products, threshold=0.72)

    assert matches == {}


def test_analyze_catalog_image_parses_structured_candidates():
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"candidates":['
                        '{"name":"Coca-Cola","brand":"Coca-Cola",'
                        '"variant":null,"packaging":"50 cl","unit":"bouteille",'
                        '"barcode":"5449000000996","purchase_price":450,'
                        '"quantity":12,"confidence":0.96}'
                        ']}'
                    )
                )
            )
        ]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: completion)
        )
    )

    with patch(
        "app.services.smart_catalog_service._get_client",
        return_value=fake_client,
    ):
        candidates = analyze_catalog_image(
            b"fake-image",
            "image/jpeg",
            "product",
        )

    assert len(candidates) == 1
    assert candidates[0].name == "Coca-Cola"
    assert candidates[0].barcode == "5449000000996"
    assert candidates[0].packaging == "50 cl"
    assert candidates[0].quantity == 12
