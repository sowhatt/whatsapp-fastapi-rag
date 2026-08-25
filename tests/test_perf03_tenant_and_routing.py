from dataclasses import dataclass

from app.agents.normalization_agent import (
    _catalog_values,
)
from app.db.tenant import set_current_merchant
from app.services.inventory_queries_service import (
    detect_inventory_query,
)
from app.services.merchant_service import (
    get_or_create_merchant,
)


@dataclass
class FakeMerchant:
    id: int
    whatsapp_number: str


class FakeMerchantQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, _condition):
        return self

    def first(self):
        self.db.merchant_queries += 1
        return self.db.merchant


class FakeMerchantSession:
    def __init__(self):
        self.info = {}
        self.merchant_queries = 0
        self.merchant = FakeMerchant(
            id=7,
            whatsapp_number="22900000000",
        )

    def query(self, _model):
        return FakeMerchantQuery(self)


class FakeCatalogQuery:
    def __init__(self, db):
        self.db = db

    def all(self):
        self.db.catalog_queries += 1
        merchant_id = self.db.info.get(
            "merchant_id",
        )
        return [
            (f"Produit-{merchant_id}",),
        ]


class FakeCatalogSession:
    def __init__(self):
        self.info = {}
        self.catalog_queries = 0

    def query(self, _column):
        return FakeCatalogQuery(self)


def test_merchant_is_loaded_once_per_session():
    db = FakeMerchantSession()

    first = get_or_create_merchant(
        "22900000000",
        db,
    )
    second = get_or_create_merchant(
        "22900000000",
        db,
    )

    assert first is second
    assert db.merchant_queries == 1


def test_catalog_cache_is_separated_by_merchant():
    db = FakeCatalogSession()

    set_current_merchant(db, 1)
    merchant_one = _catalog_values(db)
    merchant_one_again = _catalog_values(db)

    set_current_merchant(db, 2)
    merchant_two = _catalog_values(db)

    assert merchant_one is merchant_one_again
    assert merchant_one is not merchant_two
    assert merchant_one["product"] == [
        "Produit-1",
    ]
    assert merchant_two["product"] == [
        "Produit-2",
    ]
    assert db.catalog_queries == 8


def test_inventory_overview_is_deterministic():
    questions = [
        "Quels produits ai-je dans mon stock ?",
        "Liste les produits que j'ai dans mon stock",
        "Montre les articles dans mon stock",
        "Quel stock me reste ?",
    ]

    for question in questions:
        assert (
            detect_inventory_query(question)
            == "inventory_overview"
        )


def test_specific_inventory_routes_keep_priority():
    assert (
        detect_inventory_query(
            "Quels produits dorment dans mon stock ?"
        )
        == "slow_movers"
    )
    assert (
        detect_inventory_query(
            "Quel produit risque une rupture ?"
        )
        == "stockout_risk"
    )
    assert (
        detect_inventory_query(
            "Quels produits tournent vite ?"
        )
        == "fast_movers"
    )
