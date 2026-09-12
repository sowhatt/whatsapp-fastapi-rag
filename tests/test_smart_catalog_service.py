from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.schemas.smart_catalog import SmartCatalogCandidate
from app.services.smart_catalog_service import (
    SmartCatalogError,
    analyze_catalog_image,
    find_catalog_matches,
    lookup_barcode_reference,
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


def test_lookup_barcode_reference_returns_public_product():
    response = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "status": 1,
            "product": {
                "product_name_fr": "Boisson Cola",
                "brands": "Marque Test",
                "quantity": "50 cl",
            },
        },
    )

    with patch("app.services.smart_catalog_service.requests.get", return_value=response):
        candidate = lookup_barcode_reference("5449000000996")

    assert candidate.name == "Boisson Cola"
    assert candidate.brand == "Marque Test"
    assert candidate.packaging == "50 cl"
    assert candidate.barcode == "5449000000996"
    assert candidate.confidence == 0.99


def test_lookup_barcode_reference_rejects_invalid_code():
    with pytest.raises(SmartCatalogError, match="Code-barres invalide"):
        lookup_barcode_reference("123")


def test_lookup_barcode_reference_reports_unknown_product():
    response = SimpleNamespace(status_code=200, json=lambda: {"status": 0})

    with patch("app.services.smart_catalog_service.requests.get", return_value=response):
        with pytest.raises(SmartCatalogError, match="absent des référentiels"):
            lookup_barcode_reference("1234567890123")


def test_catalog_response_never_matches_products_from_another_merchant():
    from unittest.mock import MagicMock, patch

    from app.routers.pwa_smart_catalog import _catalog_response
    from app.schemas.smart_catalog import SmartCatalogCandidate

    current_shop = SimpleNamespace(id=1, merchant_id=100)

    own_product = SimpleNamespace(
        id=10,
        merchant_id=100,
        name="Huile locale 1L",
    )

    candidate = SmartCatalogCandidate(
        name="Huile locale 1L",
        confidence=0.95,
    )

    db = MagicMock()

    query = db.query.return_value
    filtered = query.filter.return_value
    ordered = filtered.order_by.return_value
    ordered.all.return_value = [own_product]

    with patch(
        "app.routers.pwa_smart_catalog._current_shop",
        return_value=current_shop,
    ):
        response = _catalog_response(
            source="product",
            candidates=[candidate],
            db=db,
        )

    # Le filtre tenant doit impérativement être appliqué avant le matching.
    query.filter.assert_called_once()

    assert 0 in response.matches
    assert response.matches[0][0].product_id == 10
